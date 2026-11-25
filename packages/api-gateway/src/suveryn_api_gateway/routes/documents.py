"""Documents: upload (a job, polled until ready), list, delete, which conversations cite one, and
answers saved to a case.
Available when ``suveryn-rag`` is installed and a database is configured; otherwise 503."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Request, Response, UploadFile
from suveryn_harness.messages import Problem, stored
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError, model_serializer

from ..conversations import ConversationSummary, SavedAnswer, file_name, search_text
from ..description import Answer
from ..problems import Message, refusals
from .status import disk_low
from .common import (
    Scope,
    case_for,
    docs_or_503,
    holds_documents,
    history_or_503,
    flush_soon,
    history_or_none,
    log_access,
    owner_of,
    readable_case_ids,
    scope_of,
    touch_case,
    who,
)

log = logging.getLogger("suveryn.gateway")
router = APIRouter(tags=["documents"])  # the group its operations are in, in the description (description.py)
BINARY = {"schema": {"type": "string", "format": "binary"}}

# What document handling says, listed here for the description: suveryn-rag is an optional package (the GPU machine
# only; routes/common.py), so the gateway can't take its lists from it. Each names the rag's own, and a test holds
# the two together (tests/test_documents.py).
UploadStatus = Literal["receiving", "queued", "processing", "ready", "needs_review", "failed", "cancelled"]  # service.JobStatus
ReadingStep = Literal["read", "ocr", "layout", "store"]                                                       # reading.Step
DocumentStatus = Literal["ok", "needs_review"]                                                                # store.STATUSES
Origin = Literal["uploaded", "generated", "playbook", "answer"]                                               # store.ORIGINS
# The files an upload can be, as its original is sent back (formats.CONTENT_TYPE; anything else as bytes).
ORIGINALS = ("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "message/rfc822", "text/plain",
             "application/octet-stream")


class ReadingWarning(Message):
    """What a reading noticed (``suveryn_rag.integrity``): a warning of the registry with its page, and the detail,
    in English, for developers."""

    model_config = Answer.model_config
    detail: str = ""


class Noticed(Answer):
    """sūveryn's own export mark found in an upload (docs/design/chat-ui.md §6): the line as it stands in the file."""

    ref: str
    kind: Literal["answer", "playbook"]
    line: str


class Progress(Answer):
    """How far reading has got: the step, and its pages done and in all when the step counts pages."""

    step: ReadingStep
    done: int | None
    total: int | None


class Upload(Answer):
    """One uploaded document on its way into the store (``suveryn_rag.service.Job.public``): no document text, but
    the line sūveryn's own mark stands on when one was noticed."""

    id: str
    filename: str
    case_id: str | None           # the case it goes into; None: the uploader's personal space
    status: UploadStatus
    document_id: str | None       # once it is a document
    error: str | None             # why it failed, in English, for developers
    failure: Message | None       # why it failed, a code of the registry with its numbers: the interface words it
    pages: int | None
    ocr_pages: int | None
    warnings: list[ReadingWarning]
    created_at: float
    finished_at: float | None
    noticed: Noticed | None       # the file carries sūveryn's export mark: not a source until someone says so
    progress: Progress | None     # while it is read
    already_present: bool         # the same file was stored here before: the stored copy, not read again
    archive: str | None           # the .zip it came from, by name


class Skipped(Answer):
    """A file of an archive that was left out, and why."""

    name: str
    failure: Message


class ArchiveUpload(Answer):
    """What an uploaded .zip became: an upload per document in it, and the files left out."""

    archive: str
    jobs: list[Upload]
    skipped: list[Skipped]


class By(Answer):
    """Who did something to a document, and when."""

    by: str
    at: str


class Withdrawn(By):
    reason: str


class Provenance(BaseModel):
    """More about where a document came from: only what is known of it is sent, so no member is always there (the
    description's test names them, ``SOMETIMES``). A playbook's result: the playbook, its version and the run. A saved
    answer: its conversation and message. An upload that carries sūveryn's own mark: what was noticed, and who chose
    to use it as a source anyway. A result whose run was cancelled: withdrawn, by whom and why."""

    playbook: str | None = None
    version: str | None = None
    run: str | None = None
    conversation: str | None = None
    message: str | None = None
    noticed: Noticed | None = None
    confirmed: By | None = None
    withdrawn: Withdrawn | None = None

    @model_serializer(mode="wrap")
    def _what_is_known(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


class StoredDocument(Answer):
    """A stored document, without its text."""

    id: str
    filename: str
    pages: int
    ocr_pages: int
    status: DocumentStatus
    warnings: list[ReadingWarning]
    created_at: str
    origin: Origin                # only uploaded documents are sources for answers (suveryn-tracker#10)
    uploaded_by: str | None
    source: bool                  # the model may read and cite it (cases.md decision 7)
    provenance: Provenance | None


class PlacedDocument(StoredDocument):
    case_id: str | None           # None: the caller's personal space


class Documents(Answer):
    """A place's documents, newest first, and the caller's uploads there still being read or failed."""

    documents: list[StoredDocument]
    jobs: list[Upload]


class AllDocuments(Answer):
    """Every document the caller may see, newest first, each with where it is."""

    documents: list[PlacedDocument]


class UsedAsSource(Answer):
    id: str
    source: bool


class SavedAnswerDocument(Answer):
    """The document an answer was saved as; ``created`` false: it was saved before, and this is that document."""

    id: str
    filename: str
    created: bool


class DocumentContent(Answer):
    """What rebuilds an answer saved to its case: the answer as the server copied it from the one it stored
    (``conversations.SavedAnswer``, #251)."""

    id: str
    filename: str
    origin: Origin
    content: dict


def _document_id(document_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(document_id)
    except ValueError:
        raise Problem("request.invalid", "Not a document id.") from None


@router.post("/v1/documents", status_code=202, response_model=Upload | ArchiveUpload, responses=refusals(404, 411, 413, 415, 422, 429, 507))
async def create_upload(request: Request, file: UploadFile = File(...), case: str | None = None):  # noqa: B008 - FastAPI's way to declare a form file
    """Add a document to the caller's personal space, or to the case ``case`` (a contributor's right): a PDF,
    Word (.docx), Excel (.xlsx), Markdown (.md), CSV, TSV, text (.txt), JSON, XML or HTML file, recognised by its
    extension and first bytes. Returns a job immediately; poll ``GET /v1/documents/jobs/{id}`` until it is
    ``ready`` (or ``needs_review``), then use its ``document_id`` in chat requests.

    A .zip archive adds each of those files inside it as a document of its own: the answer is then
    ``{"archive": name, "jobs": [job, …], "skipped": [{"name", "failure"}, …]}``, a job per document and
    the entries left out, each with why as a message of the registry (``failure``: another kind of file, an
    archive or email inside it, encrypted, too large, empty, not what its extension says, or damaged). With nothing readable in it, ``jobs`` is empty.
    An email (.eml) answers the same way: a job for the message itself (sender, recipients, date, subject, body)
    and one per attachment of those kinds. Either is one upload against the queue limits, however many documents
    it holds."""
    docs = docs_or_503(request)
    scope = await scope_of(request, case, "contribute")
    if await run_in_threadpool(disk_low):
        raise Problem("upload.disk_full", "The appliance's disk is nearly full: no documents can be added until there is room.")
    filename = file.filename or "document.pdf"
    archive = holds_documents(filename)
    # an upload refused (UploadRejected) is a Problem with its own code, upload.*: answered as it is (problems.py)
    if archive:
        result = await run_in_threadpool(docs.accept_archive, file.file, filename, owner_of(request), scope.case_id)
    else:
        result = await run_in_threadpool(docs.accept_upload, file.file, filename, owner_of(request), scope.case_id)
    await touch_case(request, scope)
    for job in (result.jobs if archive else [result]):
        await log_access(request, scope.case_id, "uploaded", {"job": job.id})
    said = result.public()
    return dict(said, jobs=[_upload(j) for j in said["jobs"]]) if archive else _upload(said)


@router.get("/v1/documents/jobs/{job_id}", response_model=Upload, responses=refusals(404, 422))
async def get_upload(job_id: str, request: Request):
    """State of one of the caller's uploads: queued, processing, ready, needs_review, failed or cancelled;
    while processing, how far reading has got (``progress``: step, pages done, pages); when failed, why
    (``error``, in English, for developers, and ``failure``: a code of the registry's ``document`` area with its numbers,
    which the interface words in its language)."""
    job = docs_or_503(request).job(job_id, owner_of(request))
    if job is None:
        raise Problem("request.not_found", "Unknown job.")
    return _upload(job.public())


@router.delete("/v1/documents/jobs/{job_id}", status_code=204, responses=refusals(404, 409, 422))
async def cancel_upload(job_id: str, request: Request):
    """Cancel one of the caller's uploads (docs/design/chat-ui.md §5, the attachment card's ×): one still
    waiting is never read; one being read is stopped, its reader with it, before it is stored. One
    already being stored finishes. Noted in the case's access log."""
    docs, owner = docs_or_503(request), owner_of(request)
    job = docs.job(job_id, owner)
    if job is None:
        raise Problem("request.not_found", "Unknown job.")
    done = await run_in_threadpool(docs.cancel, job_id, owner)
    if done is None:
        raise Problem("request.not_found", "Unknown job.")
    if done is False:
        raise Problem("upload.already_read", "This upload has been read: it is a document now.")
    await log_access(request, job.case_id, "upload_cancelled", {"job": job_id})
    return Response(status_code=204)


def _warning(kept) -> dict:
    """A warning as it was kept with its document. One that isn't a warning as the description has it (a document
    read before 12 November 2026, when warnings became codes of the registry) is read back by the registry
    (``stored``): it says that something went wrong and no more, and never makes a list unreadable."""
    try:
        ReadingWarning.model_validate(kept)
    except ValidationError:
        return stored(kept) or stored("?")
    return kept


def _upload(said: dict) -> dict:
    """An upload as document handling says it; the warnings of a file stored before come from its document."""
    return dict(said, warnings=[_warning(w) for w in said["warnings"]])


def _listed(document: dict, **more) -> dict:
    """A stored document as it is listed."""
    return dict(document, id=str(document["id"]), created_at=document["created_at"].isoformat(),
                warnings=[_warning(w) for w in document["warnings"]], **more)


@router.get("/v1/documents/all", response_model=AllDocuments, responses=refusals())
async def list_all_documents(request: Request):
    """Every document the caller may see, newest first, with its ``case_id`` (null: their personal
    space): the sidebar's "Documents" (docs/design/chat-ui.md). No jobs: those are per place."""
    docs = docs_or_503(request)
    stored = await run_in_threadpool(docs.documents_many, owner_of(request), await readable_case_ids(request))
    return {"documents": [_listed(d, case_id=str(d["case_id"]) if d.get("case_id") else None) for d in stored]}


@router.get("/v1/documents", response_model=Documents, responses=refusals(404, 422))
async def list_documents(request: Request, case: str | None = None):
    """The stored documents (newest first) in the caller's personal space, or in the case ``case``,
    and the caller's uploads there still being processed or failed."""
    docs, owner = docs_or_503(request), owner_of(request)
    scope = await scope_of(request, case, "read")
    stored = await run_in_threadpool(docs.documents, scope)
    return {"documents": [_listed(d) for d in stored], "jobs": [_upload(j.public()) for j in docs.pending_jobs(owner, scope)]}


@router.delete("/v1/documents/{document_id}", status_code=204, response_class=Response, responses={
    202: {"description": "Deleted; the conversations that cite it are cleaned by the next sweep"}, **refusals(404, 422)})
async def delete_document(document_id: str, request: Request, conversations: Literal["clean", "delete"] = "clean",
                          case: str | None = None):
    """Delete a document and its passages: one of the caller's own, or one in the case ``case``
    (its manager's right). See ``Store.delete_document`` for what deletion does and doesn't guarantee.

    Saved conversations that cite it (suveryn-tracker#12): with ``conversations=clean`` (the default)
    its passages are taken out of them; with ``conversations=delete`` those conversations are deleted.
    """
    docs, did, owner = docs_or_503(request), _document_id(document_id), owner_of(request)
    try:
        scope = await scope_of(request, case, "manage")
    except Problem as e:
        # A contributor may delete what they put there themselves, in two cases (docs/design/chat-ui.md):
        # their upload that carries sūveryn's export mark and that nobody confirmed yet (the card's
        # delete action, §6), and an answer they saved to the case (*Undo*, §5).
        if e.status != 403 or not case:
            raise
        scope = await scope_of(request, case, "contribute")
        mine = [d for d in await run_in_threadpool(docs.documents, scope) if str(d["id"]) == document_id]
        prov = (mine[0].get("provenance") or {}) if mine else {}
        noticed = "noticed" in prov and "confirmed" not in prov
        saved = mine and mine[0].get("origin") == "answer"
        if not (mine and mine[0].get("uploaded_by") == owner and (noticed or saved)):
            raise
    # The conversations that cite it are cleaned after it is gone. If their store can't be reached,
    # nothing is deleted (audit of 21 October 2026, finding 3: before, the document went and its
    # passages stayed in them); the cleaning is noted first, so the sweep finishes one that fails.
    store = history_or_none(request)
    if request.app.state.history.configured and store is None:
        raise Problem("conversation.unavailable", "Saved conversations can't be reached, so the document was not deleted: "
                      "its passages would stay in them. Try again shortly.")
    delete = conversations == "delete"
    if store is not None:
        await run_in_threadpool(store.note_cleanup, owner, did, delete, scope.case_id)
    if not await run_in_threadpool(docs.delete, document_id, scope):
        if store is not None:
            await run_in_threadpool(store.cleanup_done, owner, did)
        raise Problem("request.not_found", "Unknown document.")
    await log_access(request, scope.case_id, "document_deleted", {"document": document_id})
    flush_soon(request.app)  # once the conversations are cleaned too: a deletion close by shares the flush
    if scope.case_id is not None and (runs := request.app.state.runs.get()) is not None:
        await run_in_threadpool(runs.mark_out_of_date, scope.case_id, document_id)  # a run that read it (docs/design/playbooks.md)
    if store is not None:
        # In a case every member's conversations may cite the document: all of them are cleaned (or deleted).
        try:
            await run_in_threadpool(store.remove_document, owner, did, delete, scope.case_id)
            await run_in_threadpool(store.cleanup_done, owner, did)
        except Exception as e:  # noqa: BLE001 - the document is gone; the sweep finishes the cleaning
            log.error("conversations not cleaned yet after deleting a document: %s", type(e).__name__)
            return Response(status_code=202)  # accepted: the cleaning is still to be done
    return Response(status_code=204)


@router.post("/v1/documents/{document_id}/source", response_model=UsedAsSource, responses=refusals(404, 422))
async def use_document_as_source(document_id: str, request: Request, case: str | None = None):
    """Use an upload that carries sūveryn's own export mark as a source anyway (docs/design/chat-ui.md
    §6): the person decides, the system only said what it
    noticed. The uploader's right in their personal space, a contributor's in a case (as uploading);
    in a case the decision goes to its access log. Idempotent."""
    docs = docs_or_503(request)
    _document_id(document_id)
    scope = await scope_of(request, case, "contribute")
    noticed = await run_in_threadpool(docs.confirm_source, document_id, scope, who(request)[0])
    if noticed is None:
        raise Problem("request.not_found", "Unknown document, or nothing to confirm.")
    await log_access(request, scope.case_id, "source_confirmed", {"document": document_id, "ref": noticed.get("ref")})
    return {"id": document_id, "source": True}


@router.get("/v1/documents/{document_id}/conversations", response_model=list[ConversationSummary], responses=refusals(404, 422))
async def list_document_conversations(document_id: str, request: Request, case: str | None = None):
    """The saved conversations that cite or attach this document (asked before deleting it): the
    caller's own, or in the case ``case`` (its manager, who may delete there) everyone's."""
    did = _document_id(document_id)
    store = history_or_none(request)
    if store is None:
        return []
    scope = await scope_of(request, case, "manage")
    return await run_in_threadpool(store.using_document, owner_of(request), did, scope.case_id)


# ---------------------------------------------------------------------- answers saved to a case
@router.post("/v1/conversations/{conversation_id}/turns/{seq}/document", status_code=201, response_model=SavedAnswerDocument,
             responses={200: {"model": SavedAnswerDocument, "description": "This answer was saved before: that document"},
                        **refusals(404, 409, 422)})
async def save_turn_as_document(conversation_id: str, seq: int, request: Request, response: Response):
    """Save an answer the server stored (suveryn-tracker#251, step 2) to its conversation's case, as a document with
    origin ``answer`` (docs/design/chat-ui.md §5): the browser names the answer, and the server copies it as it was
    written, with its question, passages, checks and its sources' file names. A contributor's right in an open case;
    the conversation's owner only (404 otherwise, or for no such answer); 409 for an answer that wasn't written out,
    or a conversation that isn't in a case. Saving it again gives the document already saved. Logged as
    ``answer_saved``."""
    store, docs = history_or_503(request), docs_or_503(request)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise Problem("request.invalid", "Not a conversation id.") from None
    place = await run_in_threadpool(store.place, cid)
    if place is None or place[0] != owner_of(request) or place[2]:
        raise Problem("request.not_found", "Unknown conversation.")
    turns = {t.seq: t for t in await run_in_threadpool(store.turns_of, cid)}
    answer = turns.get(seq)
    if answer is None or answer.role != "assistant" or answer.meta.get("kind") != "answer":
        raise Problem("request.not_found", "No such answer in this conversation.")
    question = turns.get(answer.meta.get("parent"))
    if answer.meta.get("outcome") != "done" or question is None:
        raise Problem("request.conflict", "Only an answer written out is saved.")
    if place[1] is None:
        raise Problem("request.conflict", "The conversation isn't in a case.")
    case = await case_for(request, str(place[1]), "contribute")
    scope = Scope.case(uuid.UUID(case.id))
    message = f"{cid}/{seq}"
    found = await run_in_threadpool(docs.saved_answer, scope, message)
    if found:
        response.status_code = 200
        return {"id": found[0], "filename": found[1], "created": False}
    meta = answer.meta
    citations = meta.get("citations", [])  # as stored: a deleted document's passage stays out, marked removed
    cited = {c["source"]["document_id"] for c in citations if c.get("source") and not c.get("removed")}
    names = {str(d["id"]): d["filename"] for d in await run_in_threadpool(docs.documents, scope) if str(d["id"]) in cited}
    content = SavedAnswer(question=question.text, answer=answer.text, answered_on=datetime.now(UTC), model=meta.get("model"),
                          citations=citations, calculations=meta.get("calculations", []),
                          unverified_figures=meta.get("unverified_figures", []), citation_issues=meta.get("citation_issues", []),
                          support_spans=meta.get("support_spans", []), instruction_like_sources=meta.get("instruction_like_sources", []),
                          filenames=names, turn_id=message, case_ref=case.reference)
    filename = file_name(question.text)
    document_id = await run_in_threadpool(docs.store_text, filename, search_text(question.text, answer.text), scope, "answer",
                                          {"conversation": str(cid), "message": message, "turn": seq}, content.model_dump(mode="json"),
                                          owner_of(request))
    await touch_case(request, scope)
    await log_access(request, scope.case_id, "answer_saved", {"document": document_id})
    return {"id": document_id, "filename": filename, "created": True}


@router.get("/v1/documents/{document_id}/original", response_class=Response, responses={
    200: {"content": {kind: BINARY for kind in ORIGINALS}, "description": "The file, as uploaded"}, **refusals(404, 422)})
async def get_document_original(document_id: str, request: Request, case: str | None = None):
    """The file a document was read from, as uploaded (board G11, "Open document at p. 3"): for whoever may read
    its passages, and noted in the case's access log. A PDF opens in the browser (the page follows as
    ``#page=3``), text files (Markdown, CSV, TSV, text, JSON, XML, HTML) show as plain text, never as a page;
    Word, Excel and an email are downloaded. Text sūveryn stored
    itself (a saved answer, a playbook's summary) has none (404)."""
    docs = docs_or_503(request)
    _document_id(document_id)
    scope = await scope_of(request, case, "read")
    found = await run_in_threadpool(docs.original, document_id, scope)
    if found is None:
        raise Problem("request.not_found", "This document has no uploaded file.")
    filename, original = found
    await log_access(request, scope.case_id, "document_opened", {"document": document_id})
    shown = original.content_type == "application/pdf" or original.content_type.startswith("text/plain")
    headers = {"Content-Disposition": disposition("inline" if shown else "attachment", filename),
               "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if original.content_type.startswith("text/"):
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"  # text, never a page
    return Response(original.data, media_type=original.content_type, headers=headers)


def disposition(kind: str, filename: str) -> str:
    """A Content-Disposition with the document's name: plain ASCII for old readers, the name itself (RFC 6266)."""
    plain = "".join(c if c.isascii() and c.isprintable() and c not in '"\\;' else "_" for c in filename) or "document"
    return f"{kind}; filename=\"{plain}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("/v1/documents/{document_id}/content", response_model=DocumentContent, responses=refusals(404, 422))
async def get_document_content(document_id: str, request: Request, case: str | None = None):
    """What rebuilds a document sūveryn made (a saved answer's Word file, built in the browser): for
    whoever may read it."""
    docs = docs_or_503(request)
    _document_id(document_id)
    scope = await scope_of(request, case, "read")
    found = await run_in_threadpool(docs.content, document_id, scope)
    if found is None:
        raise Problem("request.not_found", "Unknown document.")
    filename, origin, content = found
    return {"id": document_id, "filename": filename, "origin": origin, "content": content}
