"""Documents: upload (a job, polled until ready), list, delete, and which conversations cite one.
Available when ``suveryn-rag`` is installed and a database is configured; otherwise 503."""

import uuid
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..conversations import ConversationSummary
from .common import (
    UploadRejected,
    docs_or_503,
    history_or_none,
    log_access,
    owner_of,
    scope_of,
    touch_case,
)

router = APIRouter()


def _document_id(document_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(422, "Not a document id.") from None


@router.post("/v1/documents", status_code=202, responses={
    411: {"description": "No Content-Length"}, 413: {"description": "File too large"},
    415: {"description": "Not a PDF"}, 503: {"description": "Unavailable"}})
async def upload_document(request: Request, file: UploadFile = File(...), case: str | None = None):  # noqa: B008 - FastAPI's way to declare a form file
    """Add a PDF to the caller's personal space, or to the case ``case`` (a contributor's right).
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
    """State of one of the caller's uploads: queued, processing, ready, needs_review or failed."""
    job = docs_or_503(request).job(job_id, owner_of(request))
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job.public()


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
    scope = await scope_of(request, case, "manage")
    if not await run_in_threadpool(docs.delete, document_id, scope):
        raise HTTPException(404, "Unknown document.")
    await log_access(request, scope.case_id, "document_deleted", {"document": document_id})
    if (store := history_or_none(request)) is not None:
        await run_in_threadpool(store.remove_document, owner, did, conversations == "delete")
    return Response(status_code=204)


@router.get("/v1/documents/{document_id}/conversations", response_model=list[ConversationSummary])
async def document_conversations(document_id: str, request: Request):
    """The caller's saved conversations that cite or attach this document (asked before deleting it)."""
    did = _document_id(document_id)
    store = history_or_none(request)
    return await run_in_threadpool(store.using_document, owner_of(request), did) if store is not None else []
