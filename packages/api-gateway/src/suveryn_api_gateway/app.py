"""FastAPI application: chat (plain or grounded in documents, JSON or streamed), documents, health.

Ownership: documents, uploads and their jobs belong to the user who uploaded them (``owner_of``);
every document endpoint and grounded chat sees only the caller's own, and another user's document
is answered with 404, like a missing one.

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

Conversations: each user's saved chat history (``conversations.py``), in the same PostgreSQL as the
documents (``SUVERYN_DATABASE_URL``); without a database the conversation endpoints answer 503 and
the UI keeps the conversation in memory only.

Token usage: every model call's token counts (counts only), stored per user (``usage.py``). Each
user can see their own (``/v1/usage``); administrators (Keycloak realm role ``suveryn-admin``) see the
office's, per user, with a notional cloud cost (``/v1/admin/usage``). Informational only: nothing
is ever limited because of it.

Limits: an upload larger than ``MAX_UPLOAD_BYTES`` (by its ``Content-Length``) is refused with 413
before its body is read, so it can't fill the disk; chat requests are bounded in ``ChatRequest``.
"""

import json
import logging
import os
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel
from suveryn_chat import ChatService, Delta, DocumentsUnavailable, Done, Status
from suveryn_engine import (
    BackendError,
    ChatRequest,
    ChatResponse,
    LlamaServerClient,
    LLMSettings,
    ModelInfo,
    StreamDelta,
    StreamError,
    StreamStatus,
    UsageRecord,
)

from .auth import (
    LOGIN_COOKIE,
    LOGIN_TTL_S,
    Authenticator,
    AuthError,
    AuthSettings,
    AuthUnavailable,
)
from .conversations import MAX_BODY_BYTES as MAX_CONVERSATION_BYTES
from .usage import AdminUsageReport, Rates, UsageReport, UsageSettings, UsageStore, parse_range
from .conversations import (
    Conversation,
    ConversationIn,
    ConversationSettings,
    ConversationStore,
    ConversationSummary,
)

try:  # document handling is optional (suveryn-rag is installed on the GPU machine only)
    from suveryn_rag.service import MAX_UPLOAD_BYTES, DocumentNotFound, SearchUnavailable, UploadRejected
except ImportError:
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024

    class DocumentNotFound(LookupError):  # stand-in; never raised without suveryn-rag
        pass

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


class StoreStatus(BaseModel):
    """State of a database-backed feature (saved conversations, token usage): "ready", "failed"
    (database unreachable) or "unavailable" (no database configured)."""

    status: str
    detail: str | None = None


HistoryStatus = StoreStatus


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str  # "ok" or "degraded" (model server not ready)
    backend: BackendStatus
    documents: DocumentsStatus
    auth: AuthStatus
    history: StoreStatus
    usage: StoreStatus


class Me(BaseModel):
    """The signed-in user, for the UI."""

    username: str
    name: str
    admin: bool = False  # may open the administration page (realm role ``suveryn-admin``)


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
UI_LANGUAGES = {"en", "nl", "fr"}  # the chat UI's languages, passed on to Keycloak's login page
ADMIN_ROLE = "suveryn-admin"  # Keycloak realm role for the administration page (usage per user, rates)
LOCAL_OWNER = "local-dev"  # owner of documents when sign-in is off (SUVERYN_AUTH=off, loopback only)


def owner_of(request: Request) -> str:
    """Whose documents this request may touch: the signed-in user's Keycloak id (``sub``)."""
    user = getattr(request.state, "user", None)
    return user.sub if user is not None else LOCAL_OWNER


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


class Database:
    """A database-backed store (conversations, token usage), connected on first use and again after a failure.

    ``store`` is an injected store (tests); otherwise ``connect`` makes one, and is None when no
    database is configured.
    """

    def __init__(self, name: str, store=None, connect: Callable[[], object] | None = None):
        self.name, self.store, self.connect, self.error = name, store, connect, None

    @property
    def configured(self) -> bool:
        return self.store is not None or self.connect is not None

    def get(self):
        """The store, or None if there is no database or it can't be reached (``error`` says why)."""
        if self.store is None and self.connect is not None:
            try:
                self.store = self.connect()
                self.error = None
            except Exception as e:  # noqa: BLE001 - reported in /health and as 503
                self.error = f"the database can't be reached ({type(e).__name__})"
                log.error("%s store unavailable: %s", self.name, type(e).__name__)
        return self.store

    def status(self) -> StoreStatus:
        if not self.configured:
            return StoreStatus(status="unavailable")
        return StoreStatus(status="ready") if self.store is not None else StoreStatus(status="failed", detail=self.error)


def _connector(factory, settings):
    """A ``Database.connect`` for ``factory(settings)``, or None without a database URL."""
    return (lambda: factory(settings)) if settings.database_url else None


def is_admin(request: Request, authenticator: Authenticator) -> bool:
    """Administrators have the Keycloak realm role ``suveryn-admin``; with sign-in off (loopback
    development only) the local user is one."""
    if not authenticator.enabled:
        return True
    user = getattr(request.state, "user", None)
    return user is not None and ADMIN_ROLE in user.roles


def create_app(client: LlamaServerClient | None = None, documents=None, *, load_documents: bool = True,
               auth: Authenticator | None = None, conversations=None, usage=None) -> FastAPI:
    """Build the FastAPI app.

    ``client``, ``documents``, ``auth``, ``conversations`` and ``usage`` let tests inject a fake model
    server, a fake document service, a sign-in with a fake Keycloak, a conversation store and a
    usage store; in production all are created from environment variables when the app starts.
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

        async def retriever(question: str, document_ids: list[str], k: int, owner: str):
            if docs is None or docs.state != "ready":
                raise DocumentsUnavailable("document search is not available right now")
            try:
                return await run_in_threadpool(docs.retrieve, question, document_ids, k, owner)
            except SearchUnavailable as e:
                raise DocumentsUnavailable(str(e)) from e

        app.state.chat = ChatService(app.state.llm, retriever)
        own_db = load_documents  # tests without documents don't connect to a database
        app.state.history = Database("conversation", conversations, None if conversations is not None or not own_db
                                     else _connector(ConversationStore, ConversationSettings.from_env()))
        app.state.usage = Database("token usage", usage, None if usage is not None or not own_db
                                   else _connector(UsageStore, UsageSettings.from_env()))
        for db in (app.state.history, app.state.usage):
            await run_in_threadpool(db.get)

        async def record_usage(r: UsageRecord) -> None:
            """The engine's usage hook: store the call's counts (lost, not retried, without a database)."""
            store = app.state.usage.get()
            if store is not None:
                await run_in_threadpool(store.record, r)

        if app.state.llm.on_usage is None:
            app.state.llm.on_usage = record_usage
        yield
        await app.state.llm.aclose()
        await authenticator.aclose()
        if docs is not None:
            docs.stop()
        for db, injected in ((app.state.history, conversations), (app.state.usage, usage)):
            if injected is None and db.store is not None:
                db.store.close()

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
    async def login(return_to: str = "/", lang: str | None = None):
        """Start signing in: redirect to the Keycloak login page, in the UI's language (``lang``: en, nl or fr)."""
        try:
            url, state = await authenticator.start_login(return_to)
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        if lang in UI_LANGUAGES:
            url += f"&ui_locales={lang}"  # OIDC: Keycloak shows its login page in this language
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
            return Me(username="dev", name="Development (sign-in off)", admin=True)
        try:
            user = await authenticator.session_user(request.cookies.get(settings.session_cookie))
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        if user is None:
            raise HTTPException(401, "Sign in to continue.")
        return Me(username=user.username, name=user.name, admin=ADMIN_ROLE in user.roles)

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
        if request.method == "PUT" and request.url.path.startswith("/v1/conversations/"):
            length = request.headers.get("content-length")
            if length is None or not length.isdigit() or int(length) > MAX_CONVERSATION_BYTES:
                return JSONResponse({"detail": "This conversation is too long to save."}, status_code=413)
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
            history=request.app.state.history.status(),
            usage=request.app.state.usage.status(),
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
              "description": "With stream=true: SSE events `status` ({step, ...}), `delta` ({text}), then `done` (a full ChatResponse) "
                             "or `error` ({message})."},
        404: {"description": "A document id doesn't exist or belongs to another user"},
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
        owner = owner_of(request)
        await _remember_user(request)
        if req.document_ids:
            # Before anything streams: only the caller's own documents (another user's id is answered
            # like a missing one). The retriever checks again when it reads the passages.
            docs = _docs_or_503(request)
            if not await run_in_threadpool(docs.owns, req.document_ids, owner):
                raise HTTPException(404, "Unknown document.")
        chat_service: ChatService = request.app.state.chat
        if not req.stream:
            try:
                return await chat_service.answer(req, owner)
            except DocumentNotFound as e:
                raise HTTPException(404, "Unknown document.") from e
            except DocumentsUnavailable as e:
                raise HTTPException(503, str(e)) from e
            except BackendError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
        return StreamingResponse(_stream(chat_service, req, owner), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/v1/documents", status_code=202, responses={
        411: {"description": "No Content-Length"}, 413: {"description": "File too large"},
        415: {"description": "Not a PDF"}, 503: {"description": "Unavailable"}})
    async def upload_document(request: Request, file: UploadFile = File(...)):
        """Add a PDF. Returns a job immediately; poll ``GET /v1/documents/jobs/{id}`` until it is
        ``ready`` (or ``needs_review``), then use its ``document_id`` in chat requests."""
        docs = _docs_or_503(request)
        try:
            job = await run_in_threadpool(docs.accept_upload, file.file, file.filename or "document.pdf", owner_of(request))
        except UploadRejected as e:
            raise HTTPException(e.status, str(e)) from e
        return job.public()

    @app.get("/v1/documents/jobs/{job_id}")
    async def document_job(job_id: str, request: Request):
        """State of one of the caller's uploads: queued, processing, ready, needs_review or failed."""
        job = _docs_or_503(request).job(job_id, owner_of(request))
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return job.public()

    @app.get("/v1/documents")
    async def list_documents(request: Request):
        """The caller's stored documents (newest first) and their uploads still being processed or failed."""
        docs, owner = _docs_or_503(request), owner_of(request)
        stored = await run_in_threadpool(docs.documents, owner)
        return {"documents": [dict(d, id=str(d["id"]), created_at=d["created_at"].isoformat()) for d in stored],
                "jobs": [j.public() for j in docs.pending_jobs(owner)]}

    @app.delete("/v1/documents/{document_id}", status_code=204)
    async def delete_document(document_id: str, request: Request):
        """Delete a document and its passages. See ``Store.delete_document`` for what deletion does and doesn't guarantee."""
        docs = _docs_or_503(request)
        try:
            uuid.UUID(document_id)
        except ValueError:
            raise HTTPException(422, "Not a document id.") from None
        if not await run_in_threadpool(docs.delete, document_id, owner_of(request)):
            raise HTTPException(404, "Unknown document.")
        return Response(status_code=204)

    def _history_or_503(request: Request) -> ConversationStore:
        history: Database = request.app.state.history
        if not history.configured:
            raise HTTPException(503, "Saved conversations are not available on this server.")
        store = history.get()
        if store is None:
            raise HTTPException(503, f"Saved conversations are not available right now: {history.error}.")
        return store

    def _conversation_id(conversation_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(conversation_id)
        except ValueError:
            raise HTTPException(422, "Not a conversation id.") from None

    @app.get("/v1/conversations", response_model=list[ConversationSummary])
    async def list_conversations(request: Request):
        """The caller's saved conversations, most recently changed first (titles and dates, no content)."""
        store = _history_or_503(request)
        return await run_in_threadpool(store.summaries, owner_of(request))

    @app.get("/v1/conversations/{conversation_id}", response_model=Conversation,
             responses={404: {"description": "Unknown, expired or another user's conversation"}})
    async def get_conversation(conversation_id: str, request: Request):
        """One of the caller's conversations with all its turns."""
        store, cid = _history_or_503(request), _conversation_id(conversation_id)
        found = await run_in_threadpool(store.get, cid, owner_of(request))
        if found is None:
            raise HTTPException(404, "Unknown conversation.")
        return found

    @app.put("/v1/conversations/{conversation_id}", status_code=204, responses={
        404: {"description": "The id belongs to another user's conversation"},
        413: {"description": f"Larger than {MAX_CONVERSATION_BYTES // (1024 * 1024)} MB"}})
    async def save_conversation(conversation_id: str, body: ConversationIn, request: Request):
        """Save the whole conversation under an id the client chose (a UUID), replacing an earlier save."""
        store, cid = _history_or_503(request), _conversation_id(conversation_id)
        if not await run_in_threadpool(store.save, cid, owner_of(request), body):
            raise HTTPException(404, "Unknown conversation.")
        return Response(status_code=204)

    @app.delete("/v1/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(conversation_id: str, request: Request):
        """Delete one of the caller's conversations."""
        store, cid = _history_or_503(request), _conversation_id(conversation_id)
        if not await run_in_threadpool(store.delete, cid, owner_of(request)):
            raise HTTPException(404, "Unknown conversation.")
        return Response(status_code=204)

    @app.delete("/v1/conversations")
    async def delete_all_conversations(request: Request):
        """Delete all of the caller's conversations (the "Delete history" choice when signing out)."""
        store = _history_or_503(request)
        return {"deleted": await run_in_threadpool(store.delete_all, owner_of(request))}

    # ------------------------------------------------------------------ token usage (suveryn-tracker#7)
    known_users: set[tuple[str, str, str]] = set()

    async def _remember_user(request: Request) -> None:
        """Keep the asker's username for the administrator's usage table (once per name change)."""
        user = getattr(request.state, "user", None)
        if user is None or (key := (user.sub, user.username, user.name)) in known_users:
            return
        store = request.app.state.usage.get()
        if store is not None:
            try:
                await run_in_threadpool(store.remember_user, *key)
                known_users.add(key)
            except Exception as e:  # noqa: BLE001 - informational; never blocks a question
                log.error("usage user not remembered: %s", type(e).__name__)

    def _usage_or_503(request: Request) -> UsageStore:
        db: Database = request.app.state.usage
        if not db.configured:
            raise HTTPException(503, "Token usage is not available on this server.")
        store = db.get()
        if store is None:
            raise HTTPException(503, f"Token usage is not available right now: {db.error}.")
        return store

    def _admin_or_403(request: Request) -> None:
        if not is_admin(request, authenticator):
            raise HTTPException(403, "Only administrators can see this.")

    def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
        try:
            return parse_range(start, end)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/v1/usage", response_model=UsageReport)
    async def my_usage(request: Request, start: datetime | None = None, end: datetime | None = None):
        """The caller's own token usage between ``start`` and ``end`` (ISO 8601 with a time zone;
        default: the last 24 hours): totals, a series of buckets in local time, per kind. Never a colleague's."""
        store, (a, b) = _usage_or_503(request), _range(start, end)
        return await run_in_threadpool(store.report, a, b, owner_of(request))

    @app.get("/v1/admin/usage", response_model=AdminUsageReport, responses={403: {"description": "Not an administrator"}})
    async def office_usage(request: Request, start: datetime | None = None, end: datetime | None = None):
        """Administrators: the office's token usage, per user and in total, with a notional cloud cost."""
        _admin_or_403(request)
        store, (a, b) = _usage_or_503(request), _range(start, end)
        return await run_in_threadpool(store.admin_report, a, b)

    @app.get("/v1/admin/usage/rates", response_model=Rates, responses={403: {"description": "Not an administrator"}})
    async def usage_rates(request: Request):
        """Administrators: the rates the notional cost uses, per million input and output tokens."""
        _admin_or_403(request)
        return await run_in_threadpool(_usage_or_503(request).rates)

    @app.put("/v1/admin/usage/rates", response_model=Rates, responses={403: {"description": "Not an administrator"}})
    async def set_usage_rates(rates: Rates, request: Request):
        """Administrators: change the rates (e.g. to a cloud model the office would otherwise use)."""
        _admin_or_403(request)
        user = getattr(request.state, "user", None)
        return await run_in_threadpool(_usage_or_503(request).set_rates, rates, user.username if user else "local-dev")

    return app


async def _stream(chat_service: ChatService, req: ChatRequest, owner: str):
    """Translate the chat service's events into the gateway's SSE contract.

    Event order: zero or more ``status`` events (pipeline steps before the first word: searching,
    loading_model, reading, writing), zero or more ``delta`` events, then exactly one of ``done`` (a complete
    ``ChatResponse``, the same shape as the JSON answer, with citations) or ``error``. A client
    that saw ``delta`` events followed by ``error`` must discard the partial answer.
    """
    try:
        async for event in chat_service.answer_stream(req, owner):
            if isinstance(event, Status):
                yield _sse("status", StreamStatus(step=event.step, passages=event.passages,
                                                  complete=event.complete, model=event.model))
            elif isinstance(event, Delta):
                yield _sse("delta", StreamDelta(text=event.text))
            elif isinstance(event, Done):
                yield _sse("done", event.response)
    except (BackendError, DocumentsUnavailable, json.JSONDecodeError) as e:
        yield _sse("error", StreamError(message=str(e)))
    except DocumentNotFound:
        yield _sse("error", StreamError(message="unknown document"))
    except Exception as e:  # noqa: BLE001 - the stream must end with an event; the client discards the partial answer
        log.error("chat stream failed: %s", type(e).__name__)  # the message may contain document text
        yield _sse("error", StreamError(message="the answer couldn't be completed because of a server error"))


app = create_app()
