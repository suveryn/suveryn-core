"""FastAPI application: chat (plain or grounded in documents, JSON or streamed), documents, health.

Scope: no auth yet. Because there is no auth, the gateway binds to 127.0.0.1 by default (see
``main.py``); exposing it on a network is only safe once Keycloak integration (development
context §5.2) exists.

Documents: available when ``suveryn-rag`` is installed (``uv sync --all-packages``, GPU machine)
and ``SUVERYN_DATABASE_URL`` is set; otherwise the document endpoints answer 503 and chat works
without grounding.

Data handling: request, answer and document text pass through but are not logged by this module.
Uvicorn's access log records only method, path and status code.
"""

import json
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from suveryn_chat import ChatService, Delta, DocumentsUnavailable, Done
from suveryn_engine import BackendError, ChatRequest, ChatResponse, LLMSettings, LlamaServerClient, StreamDelta, StreamError


class BackendStatus(BaseModel):
    """State of the model server as seen from the gateway."""

    reachable: bool
    status: str  # "ok", "loading", "error" or "unreachable"
    url: str
    model: str | None = None
    detail: str | None = None


class DocumentsStatus(BaseModel):
    """State of document handling: "ready", "starting", "failed" or "unavailable"."""

    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str  # "ok" or "degraded" (model server not ready)
    backend: BackendStatus
    documents: DocumentsStatus


def _sse(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


def _default_documents():
    """A started DocumentService if rag is installed and a database is configured, else None."""
    if not os.environ.get("SUVERYN_DATABASE_URL"):
        return None
    try:
        from suveryn_rag import RagSettings
        from suveryn_rag.service import DocumentService
    except ImportError:
        return None
    service = DocumentService(RagSettings.from_env())
    service.start()
    return service


def create_app(client: LlamaServerClient | None = None, documents=None, *, load_documents: bool = True) -> FastAPI:
    """Build the FastAPI app.

    ``client`` and ``documents`` let tests inject a fake model server and a fake document
    service; in production both are created from environment variables when the app starts.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm = client or LlamaServerClient(LLMSettings.from_env())
        app.state.documents = documents if documents is not None else (_default_documents() if load_documents else None)
        docs = app.state.documents

        async def retriever(question: str, document_ids: list[str], k: int):
            if docs is None or docs.state != "ready":
                raise DocumentsUnavailable("document search is not available right now")
            return await run_in_threadpool(docs.retrieve, question, document_ids, k)

        app.state.chat = ChatService(app.state.llm, retriever)
        yield
        await app.state.llm.aclose()
        if docs is not None:
            docs.stop()

    # FastAPI's /docs and /redoc pages load scripts, styles and fonts from public CDNs, which breaks
    # air-gapped installs and contacts third parties. Off unless explicitly enabled for development.
    # The OpenAPI schema itself (/openapi.json) is served locally and stays available.
    show_docs = os.environ.get("SUVERYN_API_DOCS") == "1"
    app = FastAPI(title="Sūveryn API", version="0.2.0", lifespan=lifespan,
                  docs_url="/docs" if show_docs else None, redoc_url=None)

    def _docs_or_503(request: Request):
        docs = request.app.state.documents
        if docs is None:
            raise HTTPException(503, "Document handling is not available on this server.")
        if docs.state != "ready":
            raise HTTPException(503, f"Document handling is {docs.state}." + (f" {docs.error}" if docs.error else ""))
        return docs

    @app.get("/health", response_model=HealthResponse,
             responses={503: {"model": HealthResponse, "description": "Model backend not ready"}})
    async def health(request: Request):
        """Report whether the model server is ready (and which model it serves) and whether documents work.

        200 when the model server is ready; 503 while it loads, fails or can't be reached. The
        ``documents`` part doesn't affect the status code: chat works without it.
        """
        llm: LlamaServerClient = request.app.state.llm
        h = await llm.health()
        docs = request.app.state.documents
        body = HealthResponse(
            status="ok" if h.status == "ok" else "degraded",
            backend=BackendStatus(reachable=h.reachable, status=h.status, url=llm.settings.base_url,
                                  model=h.model, detail=h.detail),
            documents=DocumentsStatus(status="unavailable" if docs is None else docs.state,
                                      detail=None if docs is None else docs.error),
        )
        return JSONResponse(body.model_dump(), status_code=200 if h.status == "ok" else 503)

    @app.post("/v1/chat", response_model=ChatResponse, responses={
        200: {"content": {"text/event-stream": {}},
              "description": "With stream=true: SSE events `delta` ({text}), then `done` (a full ChatResponse) "
                             "or `error` ({message})."},
        422: {"description": "Invalid request, e.g. a malformed document id"},
        502: {"description": "Model backend unreachable or returned an error"},
        503: {"description": "Grounded answer requested but document search is unavailable"},
    })
    async def chat(req: ChatRequest, request: Request):
        """Answer a conversation. With ``document_ids``, ground the answer in those documents.

        Grounded answers cite passages as [n], where [n] is ``citations[n-1]``. Without
        ``document_ids`` the answer is unsourced (``citations: []``) and must be shown as unverified.
        """
        for d in req.document_ids:
            try:
                uuid.UUID(d)
            except ValueError:
                raise HTTPException(422, f"Not a document id: {d!r}") from None
        chat_service: ChatService = request.app.state.chat
        if not req.stream:
            try:
                return await chat_service.answer(req)
            except DocumentsUnavailable as e:
                raise HTTPException(503, str(e)) from e
            except BackendError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
        return StreamingResponse(_stream(chat_service, req), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/v1/documents", status_code=202, responses={
        413: {"description": "File too large"}, 415: {"description": "Not a PDF"}, 503: {"description": "Unavailable"}})
    async def upload_document(request: Request, file: UploadFile = File(...)):
        """Add a PDF. Returns a job immediately; poll ``GET /v1/documents/jobs/{id}`` until it is
        ``ready`` (or ``needs_review``), then use its ``document_id`` in chat requests."""
        from suveryn_rag.service import UploadRejected

        docs = _docs_or_503(request)
        try:
            job = await run_in_threadpool(docs.accept_upload, file.file, file.filename or "document.pdf")
        except UploadRejected as e:
            raise HTTPException(415 if "PDF" in str(e) else 413, str(e)) from e
        return job.public()

    @app.get("/v1/documents/jobs/{job_id}")
    async def document_job(job_id: str, request: Request):
        """State of an upload: queued, processing, ready, needs_review or failed."""
        job = _docs_or_503(request).job(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return job.public()

    @app.get("/v1/documents")
    async def list_documents(request: Request):
        """Stored documents (newest first) and uploads that are still being processed or failed."""
        docs = _docs_or_503(request)
        stored = await run_in_threadpool(docs.documents)
        return {"documents": [dict(d, id=str(d["id"]), created_at=d["created_at"].isoformat()) for d in stored],
                "jobs": [j.public() for j in docs.pending_jobs()]}

    @app.delete("/v1/documents/{document_id}", status_code=204)
    async def delete_document(document_id: str, request: Request):
        """Delete a document and its passages. See ``Store.delete_document`` for what deletion does and doesn't guarantee."""
        docs = _docs_or_503(request)
        try:
            uuid.UUID(document_id)
        except ValueError:
            raise HTTPException(422, "Not a document id.") from None
        if not await run_in_threadpool(docs.delete, document_id):
            raise HTTPException(404, "Unknown document.")
        return Response(status_code=204)

    return app


async def _stream(chat_service: ChatService, req: ChatRequest):
    """Translate the chat service's events into the gateway's SSE contract.

    Event order: zero or more ``delta`` events, then exactly one of ``done`` (a complete
    ``ChatResponse``, the same shape as the JSON answer, with citations) or ``error``. A client
    that saw ``delta`` events followed by ``error`` must discard the partial answer.
    """
    try:
        async for event in chat_service.answer_stream(req):
            if isinstance(event, Delta):
                yield _sse("delta", StreamDelta(text=event.text))
            elif isinstance(event, Done):
                yield _sse("done", event.response)
    except (BackendError, DocumentsUnavailable, json.JSONDecodeError) as e:
        yield _sse("error", StreamError(message=str(e)))


app = create_app()
