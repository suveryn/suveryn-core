"""FastAPI application: chat (plain or grounded in documents, JSON or streamed), documents, health.

Sign-in: every ``/v1/...`` request needs a signed-in user (see ``auth.py``): a session cookie set
by the OIDC login with the local Keycloak, or a bearer access token. Requests that change something
(POST, DELETE, ...) with a session cookie must also come from the UI's own origin (``Origin``
header), which blocks cross-site request forgery on top of the SameSite cookie. ``/health``,
``/auth/...`` and ``/openapi.json`` are public. Without sign-in configured the API answers 503;
``SUVERYN_AUTH=off`` turns sign-in off for development on a loopback address only.

Documents: available when ``suveryn-rag`` is installed (``uv sync --all-packages``, GPU machine)
and ``SUVERYN_DATABASE_URL`` is set; otherwise the document endpoints answer 503 and chat works
without grounding.

Data handling: request, answer and document text pass through but are not logged by this module.
Uvicorn's access log records only method, path and status code. An unexpected error during a
streamed answer is reported to the client as a generic ``error`` event and logged by exception type
only, because exception messages can contain document text.

Limits: an upload larger than ``MAX_UPLOAD_BYTES`` (by its ``Content-Length``) is refused with 413
before its body is read, so it can't fill the disk; chat requests are bounded in ``ChatRequest``.
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel
from suveryn_chat import ChatService, Delta, DocumentsUnavailable, Done
from suveryn_engine import (
    BackendError,
    ChatRequest,
    ChatResponse,
    LlamaServerClient,
    LLMSettings,
    ModelInfo,
    StreamDelta,
    StreamError,
)

from .auth import (
    LOGIN_COOKIE,
    LOGIN_TTL_S,
    Authenticator,
    AuthError,
    AuthSettings,
    AuthUnavailable,
)

try:  # document handling is optional (suveryn-rag is installed on the GPU machine only)
    from suveryn_rag.service import MAX_UPLOAD_BYTES, SearchUnavailable, UploadRejected
except ImportError:
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024

    class SearchUnavailable(RuntimeError):  # stand-in; never raised without suveryn-rag
        pass

    class UploadRejected(ValueError):  # stand-in; never raised without suveryn-rag
        status = 415

log = logging.getLogger("suveryn.gateway")
MULTIPART_OVERHEAD = 64 * 1024  # form boundaries and headers around the file


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


class AuthStatus(BaseModel):
    """State of sign-in: "ready", "unavailable" (Keycloak unreachable), "not_configured" or "disabled"."""

    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str  # "ok" or "degraded" (model server not ready)
    backend: BackendStatus
    documents: DocumentsStatus
    auth: AuthStatus


class Me(BaseModel):
    """The signed-in user, for the UI."""

    username: str
    name: str


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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


def create_app(client: LlamaServerClient | None = None, documents=None, *, load_documents: bool = True,
               auth: Authenticator | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``client``, ``documents`` and ``auth`` let tests inject a fake model server, a fake document
    service and a sign-in with a fake Keycloak; in production all are created from environment
    variables when the app starts.
    """
    authenticator = auth or Authenticator(AuthSettings.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm = client or LlamaServerClient(LLMSettings.from_env())
        app.state.documents = documents if documents is not None else (_default_documents() if load_documents else None)
        docs = app.state.documents
        if documents is None and docs is not None:
            # Uploads are spooled to a temporary file: keep it out of /tmp even when the app is started
            # with bare `uvicorn` instead of `suveryn-gateway` (which already did this).
            from .main import private_tmp

            private_tmp()

        async def retriever(question: str, document_ids: list[str], k: int):
            if docs is None or docs.state != "ready":
                raise DocumentsUnavailable("document search is not available right now")
            try:
                return await run_in_threadpool(docs.retrieve, question, document_ids, k)
            except SearchUnavailable as e:
                raise DocumentsUnavailable(str(e)) from e

        app.state.chat = ChatService(app.state.llm, retriever)
        yield
        await app.state.llm.aclose()
        await authenticator.aclose()
        if docs is not None:
            docs.stop()

    # FastAPI's /docs and /redoc pages load scripts, styles and fonts from public CDNs, which breaks
    # air-gapped installs and contacts third parties. Off unless explicitly enabled for development.
    # The OpenAPI schema itself (/openapi.json) is served locally and stays available.
    show_docs = os.environ.get("SUVERYN_API_DOCS") == "1"
    app = FastAPI(title="Sūveryn API", version="0.2.0", lifespan=lifespan,
                  docs_url="/docs" if show_docs else None, redoc_url=None)

    app.state.auth = authenticator
    settings = authenticator.settings

    @app.middleware("http")
    async def require_sign_in(request: Request, call_next):
        """Gate ``/v1/...``: a valid session (plus same-origin for changes) or bearer token, else 401/403/503."""
        if not request.url.path.startswith("/v1/") or not authenticator.enabled:
            request.state.user = None
            return await call_next(request)
        header = request.headers.get("authorization", "")
        try:
            if header.lower().startswith("bearer "):
                user = await authenticator.bearer_user(header[7:].strip())
            else:
                user = await authenticator.session_user(request.cookies.get(settings.session_cookie))
                if user is not None and request.method in UNSAFE_METHODS:
                    origin = request.headers.get("origin")
                    if origin != settings.public_origin:
                        return JSONResponse({"detail": "Request from another site refused."}, status_code=403)
        except AuthUnavailable as e:
            return JSONResponse({"detail": f"Sign-in is not available: {e}."}, status_code=503)
        except AuthError:
            user = None
        if user is None:
            return JSONResponse({"detail": "Sign in to continue."}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer realm="suveryn"'})
        request.state.user = user
        return await call_next(request)

    def _cookie(response: Response, name: str, value: str, max_age: int | None) -> None:
        response.set_cookie(name, value, max_age=max_age, path="/", httponly=True, samesite="lax",
                            secure=settings.secure_cookies)

    @app.get("/auth/login", include_in_schema=False)
    async def login(return_to: str = "/"):
        """Start signing in: redirect to the Keycloak login page."""
        try:
            url, state = await authenticator.start_login(return_to)
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        response = RedirectResponse(url, status_code=303)
        _cookie(response, LOGIN_COOKIE, state, LOGIN_TTL_S)
        return response

    @app.get("/auth/callback", include_in_schema=False)
    async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        """Keycloak sends the browser back here with a code; exchange it and start a session."""
        if error or not code or not state:
            raise HTTPException(400, "Sign-in was cancelled or failed. Close this page and sign in again.")
        try:
            session, return_to = await authenticator.finish_login(code, state, request.cookies.get(LOGIN_COOKIE))
        except AuthError as e:
            raise HTTPException(400, f"Sign-in failed: {e}.") from e
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        response = RedirectResponse(return_to, status_code=303)
        response.delete_cookie(LOGIN_COOKIE, path="/")
        _cookie(response, settings.session_cookie, session.id, None)  # a browser-session cookie
        return response

    @app.get("/auth/me", response_model=Me, responses={401: {"description": "Not signed in"}})
    async def me(request: Request):
        """The signed-in user (username and display name), or 401."""
        if not authenticator.enabled:
            return Me(username="dev", name="Development (sign-in off)")
        try:
            user = await authenticator.session_user(request.cookies.get(settings.session_cookie))
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        if user is None:
            raise HTTPException(401, "Sign in to continue.")
        return Me(username=user.username, name=user.name)

    @app.post("/auth/logout")
    async def logout(request: Request):
        """End the session; ``logout_url`` ends the Keycloak session too (the UI navigates there)."""
        origin = request.headers.get("origin")
        if authenticator.enabled and origin is not None and origin != settings.public_origin:
            raise HTTPException(403, "Request from another site refused.")
        url = await authenticator.logout(request.cookies.get(settings.session_cookie))
        response = JSONResponse({"logout_url": url})
        response.delete_cookie(settings.session_cookie, path="/")
        return response

    @app.exception_handler(SearchUnavailable)
    async def search_unavailable(request: Request, exc: SearchUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.middleware("http")
    async def limit_upload_size(request: Request, call_next):
        """Refuse an oversized upload by its Content-Length, before Starlette spools the body to disk."""
        if request.method == "POST" and request.url.path == "/v1/documents":
            length = request.headers.get("content-length")
            if length is None:
                return JSONResponse({"detail": "Uploads need a Content-Length header."}, status_code=411)
            if not length.isdigit() or int(length) > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD:
                return JSONResponse({"detail": f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."},
                                    status_code=413)
        return await call_next(request)

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
            auth=AuthStatus(**dict(zip(("status", "detail"), await authenticator.status(), strict=True))),
        )
        return JSONResponse(body.model_dump(), status_code=200 if h.status == "ok" else 503)

    @app.get("/v1/models", response_model=list[ModelInfo], responses={502: {"description": "Model backend unreachable"}})
    async def models(request: Request):
        """The models installed on this appliance, which one is the default, and which is loaded now.

        Choosing a model that isn't loaded makes the next answer wait while it loads (seconds when
        it was used recently, up to about half a minute otherwise), and other people's questions
        wait too: the GPU holds one model at a time.
        """
        llm: LlamaServerClient = request.app.state.llm
        try:
            return await llm.list_models()
        except BackendError as e:
            raise HTTPException(502, str(e)) from e

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
        if req.model is not None:
            try:
                installed = {m.id for m in await request.app.state.llm.list_models()}
            except BackendError as e:
                raise HTTPException(502, str(e)) from e
            if req.model not in installed:
                raise HTTPException(422, f"No such model on this appliance: {req.model!r}")
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
        411: {"description": "No Content-Length"}, 413: {"description": "File too large"},
        415: {"description": "Not a PDF"}, 503: {"description": "Unavailable"}})
    async def upload_document(request: Request, file: UploadFile = File(...)):
        """Add a PDF. Returns a job immediately; poll ``GET /v1/documents/jobs/{id}`` until it is
        ``ready`` (or ``needs_review``), then use its ``document_id`` in chat requests."""
        docs = _docs_or_503(request)
        try:
            job = await run_in_threadpool(docs.accept_upload, file.file, file.filename or "document.pdf")
        except UploadRejected as e:
            raise HTTPException(e.status, str(e)) from e
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
    except Exception as e:  # noqa: BLE001 - the stream must end with an event; the client discards the partial answer
        log.error("chat stream failed: %s", type(e).__name__)  # the message may contain document text
        yield _sse("error", StreamError(message="the answer couldn't be completed because of a server error"))


app = create_app()
