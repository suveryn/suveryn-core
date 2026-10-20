"""Documents: upload (a job, polled until ready), list, delete, which conversations cite one, and
answers saved to a case.
Available when ``suveryn-rag`` is installed and a database is configured; otherwise 503."""

import json
import uuid
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..conversations import ConversationSummary
from .common import (
    UploadRejected,
    docs_or_503,
    history_or_none,
    log_access,
    owner_of,
    readable_case_ids,
    scope_of,
    touch_case,
    who,
)

router = APIRouter()


def _document_id(document_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(422, "Not a document id.") from None


@router.post("/v1/documents", status_code=202, responses={
    411: {"description": "No Content-Length"}, 413: {"description": "File too large"},
    415: {"description": "Not a PDF, Word, Excel, Markdown or CSV file"}, 503: {"description": "Unavailable"}})
async def upload_document(request: Request, file: UploadFile = File(...), case: str | None = None):  # noqa: B008 - FastAPI's way to declare a form file
    """Add a document to the caller's personal space, or to the case ``case`` (a contributor's right): a PDF,
    Word (.docx), Excel (.xlsx), Markdown (.md) or CSV file, recognised by its extension and first bytes.
    Returns a job immediately; poll ``GET /v1/documents/jobs/{id}`` until it is ``ready`` (or
    ``needs_review``), then use its ``document_id`` in chat requests."""
    docs = docs_or_503(request)
    scope = await scope_of(request, case, "contribute")
    try:
        job = await run_in_threadpool(docs.accept_upload, file.file, file.filename or "document.pdf", owner_of(request),
                                      scope.case_id)
    except UploadRejected as e:
        raise HTTPException(e.status, str(e)) from e
    await touch_case(request, scope)
    await log_access(request, scope.case_id, "uploaded", {"job": job.id})
    return job.public()


@router.get("/v1/documents/jobs/{job_id}")
async def document_job(job_id: str, request: Request):
    """State of one of the caller's uploads: queued, processing, ready, needs_review, failed or cancelled;
    while processing, how far reading has got (``progress``: step, pages done, pages); when failed, why
    (``error``, in English, and ``error_code`` with ``error_detail`` for the interface to say in its language)."""
    job = docs_or_503(request).job(job_id, owner_of(request))
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job.public()


@router.delete("/v1/documents/jobs/{job_id}", status_code=204, responses={
    404: {"description": "Unknown job"}, 409: {"description": "Already read: it is a document, delete that instead"}})
async def cancel_job(job_id: str, request: Request):
    """Cancel one of the caller's uploads (docs/design/sidebar.md §5, the attachment card's ×): one still
    waiting is never read; one being read is stopped, its reader with it, before it is stored. One
    already being stored finishes. Noted in the case's access log."""
    docs, owner = docs_or_503(request), owner_of(request)
    job = docs.job(job_id, owner)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    done = await run_in_threadpool(docs.cancel, job_id, owner)
    if done is None:
        raise HTTPException(404, "Unknown job.")
    if done is False:
        raise HTTPException(409, "This upload has been read: it is a document now.")
    await log_access(request, job.case_id, "upload_cancelled", {"job": job_id})
    return Response(status_code=204)


@router.get("/v1/documents/all")
async def list_all_documents(request: Request):
    """Every document the caller may see, newest first, with its ``case_id`` (null: their personal
    space): the sidebar's "Documents" (docs/design/sidebar.md). No jobs: those are per place."""
    docs = docs_or_503(request)
    stored = await run_in_threadpool(docs.documents_many, owner_of(request), await readable_case_ids(request))
    return {"documents": [dict(d, id=str(d["id"]), case_id=str(d["case_id"]) if d.get("case_id") else None,
                               created_at=d["created_at"].isoformat()) for d in stored]}


@router.get("/v1/documents")
async def list_documents(request: Request, case: str | None = None):
    """The stored documents (newest first) in the caller's personal space, or in the case ``case``,
    and the caller's uploads there still being processed or failed."""
    docs, owner = docs_or_503(request), owner_of(request)
    scope = await scope_of(request, case, "read")
    stored = await run_in_threadpool(docs.documents, scope)
    return {"documents": [dict(d, id=str(d["id"]), created_at=d["created_at"].isoformat()) for d in stored],
            "jobs": [j.public() for j in docs.pending_jobs(owner, scope)]}


@router.delete("/v1/documents/{document_id}", status_code=204)
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
    except HTTPException as e:
        # A contributor may delete what they put there themselves, in two cases (docs/design/sidebar.md):
        # their upload that carries sūveryn's export mark and that nobody confirmed yet (the card's
        # delete action, §6), and an answer they saved to the case (*Undo*, §5).
        if e.status_code != 403 or not case:
            raise
        scope = await scope_of(request, case, "contribute")
        mine = [d for d in await run_in_threadpool(docs.documents, scope) if str(d["id"]) == document_id]
        prov = (mine[0].get("provenance") or {}) if mine else {}
        noticed = "noticed" in prov and "confirmed" not in prov
        saved = mine and mine[0].get("origin") == "answer"
        if not (mine and mine[0].get("uploaded_by") == owner and (noticed or saved)):
            raise
    if not await run_in_threadpool(docs.delete, document_id, scope):
        raise HTTPException(404, "Unknown document.")
    await log_access(request, scope.case_id, "document_deleted", {"document": document_id})
    if scope.case_id is not None and (runs := request.app.state.runs.get()) is not None:
        await run_in_threadpool(runs.mark_out_of_date, scope.case_id, document_id)  # a run that read it (docs/design/playbooks.md)
    if (store := history_or_none(request)) is not None:
        # In a case every member's conversations may cite the document: all of them are cleaned (or deleted).
        await run_in_threadpool(store.remove_document, owner, did, conversations == "delete", scope.case_id)
    return Response(status_code=204)


@router.post("/v1/documents/{document_id}/source", responses={404: {"description": "Not here, or nothing was noticed"}})
async def use_as_source(document_id: str, request: Request, case: str | None = None):
    """Use an upload that carries sūveryn's own export mark as a source anyway (docs/design/sidebar.md
    §6): the person decides, the system only said what it
    noticed. The uploader's right in their personal space, a contributor's in a case (as uploading);
    in a case the decision goes to its access log. Idempotent."""
    docs = docs_or_503(request)
    _document_id(document_id)
    scope = await scope_of(request, case, "contribute")
    noticed = await run_in_threadpool(docs.confirm_source, document_id, scope, who(request)[0])
    if noticed is None:
        raise HTTPException(404, "Unknown document, or nothing to confirm.")
    await log_access(request, scope.case_id, "source_confirmed", {"document": document_id, "ref": noticed.get("ref")})
    return {"id": document_id, "source": True}


@router.get("/v1/documents/{document_id}/conversations", response_model=list[ConversationSummary])
async def document_conversations(document_id: str, request: Request, case: str | None = None):
    """The saved conversations that cite or attach this document (asked before deleting it): the
    caller's own, or in the case ``case`` (its manager, who may delete there) everyone's."""
    did = _document_id(document_id)
    store = history_or_none(request)
    if store is None:
        return []
    scope = await scope_of(request, case, "manage")
    return await run_in_threadpool(store.using_document, owner_of(request), did, scope.case_id)


# ---------------------------------------------------------------------- answers saved to a case
MAX_CONTENT_BYTES = 2_000_000  # an answer, its sources' passages and its checks; a long one is ~100 kB


class SavedCitation(BaseModel):
    """A source of the saved answer, as the chat shows it; checked so a deleted document can be taken out."""

    model_config = ConfigDict(extra="allow")
    text: str = Field(max_length=200_000)
    source: dict | None = None


class AnswerContent(BaseModel):
    """What rebuilds the Word file (the chat UI's own data): the question, the answer as written, its
    sources and checks, and the file names of the sources as they were."""

    model_config = ConfigDict(extra="allow")
    question: str = Field(max_length=20_000)
    answer: str = Field(max_length=200_000)
    citations: list[SavedCitation] = Field(default_factory=list, max_length=200)
    filenames: dict[str, str] = Field(default_factory=dict)


class SaveAnswerIn(BaseModel):
    """Body of ``POST /v1/cases/{id}/documents``: an answer saved to the case (docs/design/sidebar.md §5)."""

    filename: str = Field(min_length=6, max_length=200, pattern=r"^[^/\\\x00-\x1f]+\.docx$")
    text: str = Field(min_length=1, max_length=200_000)  # what search finds: the question and the answer
    content: AnswerContent
    conversation_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    message_id: str = Field(min_length=1, max_length=100)

    @field_validator("content")
    @classmethod
    def not_too_large(cls, v: AnswerContent) -> AnswerContent:
        if len(v.model_dump_json()) > MAX_CONTENT_BYTES:
            raise ValueError("the answer is too large to save")
        return v


@router.post("/v1/cases/{case_id}/documents", status_code=201, responses={
    200: {"description": "This answer was saved before: that document"},
    403: {"description": "Not a contributor, or the case is closed"}, 404: {"description": "No such case here"}})
async def save_answer(case_id: str, body: SaveAnswerIn, request: Request, response: Response):
    """Save an answer to its case, as a document with origin ``answer`` (docs/design/sidebar.md §5): a
    contributor's right in an open case. Never a source (cases.md decision 7); listed, searchable,
    deleted with the case. Its file is rebuilt by the chat from ``content`` (``GET .../content``).
    Saving the same message again gives the document already saved. Logged as ``answer_saved``."""
    docs = docs_or_503(request)
    scope = await scope_of(request, case_id, "contribute")
    owner = owner_of(request)
    found = await run_in_threadpool(docs.saved_answer, scope, body.message_id)
    if found:
        response.status_code = 200
        return {"id": found[0], "filename": found[1], "created": False}
    provenance = {"conversation": body.conversation_id, "message": body.message_id}
    document_id = await run_in_threadpool(docs.store_text, body.filename, body.text, scope, "answer", provenance,
                                          json.loads(body.content.model_dump_json()), owner)
    await touch_case(request, scope)
    await log_access(request, scope.case_id, "answer_saved", {"document": document_id})
    return {"id": document_id, "filename": body.filename, "created": True}


@router.get("/v1/documents/{document_id}/content", responses={404: {"description": "Not here, or nothing to rebuild"}})
async def document_content(document_id: str, request: Request, case: str | None = None):
    """What rebuilds a document sūveryn made (a saved answer's Word file, built in the browser): for
    whoever may read it."""
    docs = docs_or_503(request)
    _document_id(document_id)
    scope = await scope_of(request, case, "read")
    found = await run_in_threadpool(docs.content, document_id, scope)
    if found is None:
        raise HTTPException(404, "Unknown document.")
    filename, origin, content = found
    return {"id": document_id, "filename": filename, "origin": origin, "content": content}
