"""FastAPI application: chat (plain or grounded in documents, JSON or streamed), documents, health.

Ownership: a document, its upload and job, and a conversation are in one scope: the uploader's
personal space, or a case (``cases.py``, suveryn-tracker#10). A request names the case it works
in (``?case=`` on documents and conversations, ``case_id`` in a chat request); without one it is
in the caller's personal space. The scope is decided once per request (``_scope``): the personal
space is the caller's own, and a case needs the right in ``cases.may``. Everything outside the
scope is answered with 404, like a missing document or conversation.

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
Uvicorn's access log records only method, path and status code: query strings are cut off
(``StripQueryString``), since /auth/callback carries the sign-in code and state there. An unexpected error during a
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
Sign-in (per client address), questions and uploads (per user) are rate-limited (``ratelimit.py``):
over the limit the answer is 429 with ``Retry-After``.
"""

import json
import logging
import os
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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
from .cases import (
    Case,
    CaseEvent,
    CaseIn,
    CaseSettings,
    CaseStore,
    CaseUpdate,
    DuplicateReference,
    HandoverIn,
    Member,
    MemberIn,
    Principal,
    may,
)
from .conversations import MAX_BODY_BYTES as MAX_CONVERSATION_BYTES
from .conversations import (
    Conversation,
    ConversationIn,
    ConversationSettings,
    ConversationStore,
    ConversationSummary,
    cited_documents,
)
from .directory import (
    Directory,
    DirectorySettings,
    DirectoryUnavailable,
    LocalDirectory,
    Person,
)
from .ratelimit import RateLimiter, RateLimits
from .usage import (
    AdminUsageReport,
    Rates,
    UsageReport,
    UsageSettings,
    UsageStore,
    parse_range,
)

try:  # document handling is optional (suveryn-rag is installed on the GPU machine only)
    from suveryn_rag.service import (
        MAX_UPLOAD_BYTES,
        DocumentNotFound,
        SearchUnavailable,
        UploadRejected,
    )
    from suveryn_rag.store import Scope
except ImportError:
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024

    @dataclass(frozen=True)
    class Scope:  # stand-in with the same shape; without suveryn-rag it only names where conversations are
        owner: str | None = None
        case_id: uuid.UUID | None = None

        @classmethod
        def personal(cls, owner):
            return cls(owner=owner)

        @classmethod
        def case(cls, case_id):
            return cls(case_id=case_id)

    class DocumentNotFound(LookupError):  # stand-in; never raised without suveryn-rag
        pass

    class SearchUnavailable(RuntimeError):  # stand-in; never raised without suveryn-rag
        pass

    class UploadRejected(ValueError):  # stand-in; never raised without suveryn-rag
        status = 415

log = logging.getLogger("suveryn.gateway")


class StripQueryString(logging.Filter):
    """Drops the query string from uvicorn access-log lines.

    /auth/callback?code=...&state=... would otherwise put the one-time sign-in code in the log. It is
    useless without the PKCE verifier and expires within a minute, but secrets don't belong in logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            record.args = (*record.args[:2], record.args[2].split("?", 1)[0], *record.args[3:])
        return True


_access_log = logging.getLogger("uvicorn.access")
if not any(isinstance(f, StripQueryString) for f in _access_log.filters):
    _access_log.addFilter(StripQueryString())
MULTIPART_OVERHEAD = 64 * 1024  # form boundaries and headers around the file


class BackendStatus(BaseModel):
    """State of the model server as seen from the gateway."""

    reachable: bool
    status: str  # "ok", "loading", "error" or "unreachable"
    url: str | None = None  # not reported: /health is public (the server log has it)
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



class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str  # "ok" or "degraded" (model server not ready)
    backend: BackendStatus
    documents: DocumentsStatus
    auth: AuthStatus
    history: StoreStatus
    usage: StoreStatus
    cases: StoreStatus
    directory: StoreStatus  # the office's accounts from Keycloak, to add colleagues to a case


class Me(BaseModel):
    """The signed-in user, for the UI."""

    username: str
    name: str
    admin: bool = False  # may open the administration page (realm role ``suveryn-admin``)
    office_wide: bool = False  # the appliance's default access for cases (SUVERYN_CASES_DEFAULT_ACCESS=office)


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
UI_LANGUAGES = {"en", "nl", "fr"}  # the chat UI's languages, passed on to Keycloak's login page
# With sign-in off, only these clients may use /v1: this machine ("testclient" is Starlette's test client).
LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}
ADMIN_ROLE = "suveryn-admin"  # Keycloak realm role for the administration page (usage per user, rates)
LOCAL_OWNER = "local-dev"  # owner of documents when sign-in is off (SUVERYN_AUTH=off, loopback only)


def owner_of(request: Request) -> str:
    """Whose documents this request may touch: the signed-in user's Keycloak id (``sub``)."""
    user = getattr(request.state, "user", None)
    return user.sub if user is not None else LOCAL_OWNER


def _too_many(wait: int) -> JSONResponse:
    return JSONResponse({"detail": f"Too many requests. Try again in {wait} seconds."}, status_code=429,
                        headers={"Retry-After": str(wait)})


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
               auth: Authenticator | None = None, conversations=None, usage=None, cases=None,
               case_settings: CaseSettings | None = None, directory=None,
               rate_limits: RateLimits | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``client``, ``documents``, ``auth``, ``conversations``, ``usage`` and ``cases`` let tests inject a
    fake model server, a fake document service, a sign-in with a fake Keycloak, a conversation store,
    a usage store and a case store; in production all are created from environment variables when
    the app starts. ``case_settings`` sets the appliance's default access for cases (tests);
    ``directory`` injects the office's user list (``directory.py``).
    """
    authenticator = auth or Authenticator(AuthSettings.from_env())
    cases_settings = case_settings or CaseSettings.from_env()
    limits = rate_limits or RateLimits.from_env()
    sign_in_limit = RateLimiter(limits.sign_in)
    per_user_limits = {("POST", "/v1/chat"): RateLimiter(limits.chat),
                       ("POST", "/v1/documents"): RateLimiter(limits.uploads)}

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

        async def retriever(question: str, document_ids: list[str], k: int, owner: str, case_id: str | None):
            # The chat route has checked the caller may read the case; here the scope only says where to look.
            if docs is None or docs.state != "ready":
                raise DocumentsUnavailable("document search is not available right now")
            scope = Scope.case(uuid.UUID(case_id)) if case_id else Scope.personal(owner)
            try:
                return await run_in_threadpool(docs.retrieve, question, document_ids, k, scope)
            except SearchUnavailable as e:
                raise DocumentsUnavailable(str(e)) from e

        app.state.chat = ChatService(app.state.llm, retriever)
        own_db = load_documents  # tests without documents don't connect to a database
        app.state.history = Database("conversation", conversations, None if conversations is not None or not own_db
                                     else _connector(ConversationStore, ConversationSettings.from_env()))
        app.state.usage = Database("token usage", usage, None if usage is not None or not own_db
                                   else _connector(UsageStore, UsageSettings.from_env()))
        app.state.cases = Database("case", cases, None if cases is not None or not own_db
                                   else _connector(CaseStore, cases_settings))
        if directory is not None:
            app.state.directory = directory
        elif not authenticator.enabled:
            app.state.directory = LocalDirectory(LOCAL_OWNER)
        else:
            app.state.directory = Directory(DirectorySettings.from_env())
        for db in (app.state.history, app.state.usage, app.state.cases):
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
        if directory is None:
            await app.state.directory.aclose()
        if docs is not None:
            docs.stop()
        for db, injected in ((app.state.history, conversations), (app.state.usage, usage), (app.state.cases, cases)):
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
        """Gate ``/v1/...``: a valid session (plus same-origin for changes) or bearer token, else 401/403/503.

        Also applies the rate limits: sign-in per client address, questions and uploads per user (429).
        """
        if request.url.path in ("/auth/login", "/auth/callback"):
            wait = sign_in_limit.hit(request.client.host if request.client else "unknown")
            if wait is not None:
                return _too_many(wait)
        if not authenticator.enabled and request.url.path.startswith("/v1/"):
            # Sign-in off is for development on one machine. main.py refuses a network address, but the
            # app can also be started with bare uvicorn: refuse anyone who isn't on this machine.
            host = request.client.host if request.client else None
            if host not in LOCAL_CLIENTS:
                return JSONResponse({"detail": "Sign-in is turned off; only this machine may use the API."},
                                    status_code=403)
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
        limiter = per_user_limits.get((request.method, request.url.path))
        if limiter is not None and (wait := limiter.hit(user.sub)) is not None:
            return _too_many(wait)
        return await call_next(request)

    def _cookie(response: Response, name: str, value: str, max_age: int | None) -> None:
        response.set_cookie(name, value, max_age=max_age, path="/", httponly=True, samesite="lax",
                            secure=settings.secure_cookies)

    @app.get("/auth/login", include_in_schema=False)
    async def login(return_to: str = "/", lang: str | None = None):
        """Start signing in: redirect to the Keycloak login page, in the UI's language (``lang``: en, nl or fr)."""
        try:
            url, login_cookie = await authenticator.start_login(return_to)
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        if lang in UI_LANGUAGES:
            url += f"&ui_locales={lang}"  # OIDC: Keycloak shows its login page in this language
        response = RedirectResponse(url, status_code=303)
        _cookie(response, LOGIN_COOKIE, login_cookie, LOGIN_TTL_S)
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
            return Me(username="dev", name="Development (sign-in off)", admin=True, office_wide=cases_settings.office_wide)
        try:
            user = await authenticator.session_user(request.cookies.get(settings.session_cookie))
        except AuthUnavailable as e:
            raise HTTPException(503, f"Sign-in is not available: {e}.") from e
        if user is None:
            raise HTTPException(401, "Sign in to continue.")
        return Me(username=user.username, name=user.name, admin=ADMIN_ROLE in user.roles, office_wide=cases_settings.office_wide)

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
        ``documents`` part doesn't affect the status code: chat works without it. Public (no sign-in),
        so it gives states only: no internal addresses or error texts (those are in the server log).
        """
        llm: LlamaServerClient = request.app.state.llm
        h = await llm.health()
        docs = request.app.state.documents
        body = HealthResponse(
            status="ok" if h.status == "ok" else "degraded",
            backend=BackendStatus(reachable=h.reachable, status=h.status, model=h.model),
            documents=DocumentsStatus(status="unavailable" if docs is None else docs.state),
            auth=AuthStatus(status=(await authenticator.status())[0]),
            history=request.app.state.history.status(),
            usage=request.app.state.usage.status(),
            cases=request.app.state.cases.status(),
            directory=StoreStatus(status="ready" if request.app.state.directory.configured else "unavailable"),
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

    # ------------------------------------------------------------------ cases (suveryn-tracker#10)
    def _cases_or_503(request: Request) -> CaseStore:
        db: Database = request.app.state.cases
        if not db.configured:
            raise HTTPException(503, "Cases are not available on this server.")
        store = db.get()
        if store is None:
            raise HTTPException(503, f"Cases are not available right now: {db.error}.")
        return store

    def _principal(request: Request) -> Principal:
        return Principal(sub=owner_of(request), admin=is_admin(request, authenticator))

    def _case_id(case_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(case_id)
        except ValueError:
            raise HTTPException(422, "Not a case id.") from None

    async def _case_for(request: Request, case_id: str, action: str) -> Case:
        """The case, if the caller may do ``action`` in it; else 404 (a case they may not see is
        answered like a missing one) or 403 (they may see it, not do this)."""
        store, cid, who = _cases_or_503(request), _case_id(case_id), _principal(request)
        case = await run_in_threadpool(store.get, cid, who.sub)
        office_wide = cases_settings.office_wide
        if case is None or not (may(who, case, case.my_role, "read", office_wide) or may(who, case, case.my_role, "list", office_wide)):
            raise HTTPException(404, "Unknown case.")
        if not may(who, case, case.my_role, action, office_wide):
            raise HTTPException(403, "You may not do this in this case."
                                if case.state == "open" else "This case is closed.")
        return case

    async def _log(request: Request, case_id: uuid.UUID | None, action: str, detail: dict | None = None) -> None:
        """A line in the case's access log (decision 15). Never fails a request: the log is
        informational, the server log says when it couldn't be written."""
        if case_id is None:
            return
        store = request.app.state.cases.get()
        if store is None:
            return
        try:
            await run_in_threadpool(store.log, case_id, owner_of(request), action, detail)
        except Exception as e:  # noqa: BLE001 - informational; never blocks the request
            log.error("case access log not written: %s", type(e).__name__)

    def _who(request: Request) -> tuple[str, str]:
        """The caller's username and display name, for the member list."""
        user = getattr(request.state, "user", None)
        return (user.username, user.name) if user is not None else ("dev", "Development (sign-in off)")

    async def _person_or_404(request: Request, sub: str) -> Person:
        """A colleague by their id, from the office's directory (404 if not an enabled account)."""
        try:
            found = await request.app.state.directory.get(sub)
        except DirectoryUnavailable as e:
            raise HTTPException(503, f"The office's directory is not available right now: {e}.") from e
        if found is None:
            raise HTTPException(404, "Unknown user.")
        return found

    async def _scope(request: Request, case: str | None, action: str) -> Scope:
        """Where a request works: the caller's personal space, or the case ``case`` if they may do
        ``action`` in it (``read`` to list and ask, ``contribute`` to upload, ``manage`` to delete)."""
        if not case:
            return Scope.personal(owner_of(request))
        found = await _case_for(request, case, action)
        return Scope.case(uuid.UUID(found.id))

    @app.get("/v1/cases", response_model=list[Case])
    async def list_cases(request: Request, closed: bool = False):
        """The cases the caller may see: open ones first, most recently active first. Closed cases
        only with ``closed=true``. ``my_role`` is the caller's role in each."""
        store, who = _cases_or_503(request), _principal(request)
        return await run_in_threadpool(store.list, who.sub, office_wide=cases_settings.office_wide,
                                       admin=who.admin, closed=closed)

    @app.post("/v1/cases", response_model=Case, status_code=201, responses={409: {"description": "A case with this reference exists"}})
    async def create_case(body: CaseIn, request: Request):
        """Open a new case. The caller becomes its manager and first member.
        The reference is the office's own file number, unique on this appliance; never put a client's
        name in it or the name."""
        store = _cases_or_503(request)
        await _remember_user(request)
        try:
            return await run_in_threadpool(store.create, body, owner_of(request), *_who(request))
        except DuplicateReference:
            raise HTTPException(409, "A case with this reference already exists.") from None

    @app.get("/v1/cases/{case_id}", response_model=Case, responses={404: {"description": "Unknown case"}})
    async def get_case(case_id: str, request: Request):
        """One case the caller may see."""
        case = await _case_for(request, case_id, "read")
        await _log(request, uuid.UUID(case.id), "opened")
        return case

    @app.patch("/v1/cases/{case_id}", response_model=Case, responses={
        403: {"description": "Not the case's manager, or the case is closed"}, 404: {"description": "Unknown case"},
        409: {"description": "A case with this reference exists"}})
    async def update_case(case_id: str, body: CaseUpdate, request: Request):
        """Change a case's reference, name, type, subject or access (its manager only)."""
        case = await _case_for(request, case_id, "manage")
        try:
            changed = await run_in_threadpool(_cases_or_503(request).update, uuid.UUID(case.id), body)
        except DuplicateReference:
            raise HTTPException(409, "A case with this reference already exists.") from None
        fields = body.model_dump(exclude_none=True)
        if "access" in fields and fields["access"] != case.access:
            await _log(request, uuid.UUID(case.id), "access_changed", {"access": fields["access"]})
        if set(fields) - {"access"}:
            await _log(request, uuid.UUID(case.id), "changed", {"fields": sorted(set(fields) - {"access"})})
        return changed.model_copy(update={"my_role": case.my_role}) if changed else changed

    @app.delete("/v1/cases/{case_id}", status_code=204, responses={
        403: {"description": "Not the case's manager"}, 404: {"description": "Unknown case"}})
    async def delete_case(case_id: str, request: Request):
        """Delete a case with its documents and conversations (its manager only). Closing and the
        keep period (docs/design/cases.md, stage 3) are the office's way; this is for a case opened
        by mistake. See ``Store.delete_document`` for what deletion does and doesn't guarantee."""
        case = await _case_for(request, case_id, "manage")
        cid = uuid.UUID(case.id)
        docs = request.app.state.documents
        if docs is not None:
            if docs.state != "ready":
                raise HTTPException(503, f"Document handling is {docs.state}; the case's documents can't be deleted now.")
            await run_in_threadpool(docs.delete_all, Scope.case(cid))
        if (history := _history_or_none(request)) is not None:
            await run_in_threadpool(history.delete_case, cid)
        if not await run_in_threadpool(_cases_or_503(request).delete, cid):
            raise HTTPException(404, "Unknown case.")
        return Response(status_code=204)

    @app.get("/v1/users", response_model=list[Person], responses={503: {"description": "The directory is not available"}})
    async def list_users(request: Request, q: str = ""):
        """The office's accounts (id, username, name) whose username, name or email contains ``q``,
        to add a colleague to a case. From Keycloak, through the ``suveryn-directory`` client."""
        try:
            return await request.app.state.directory.search(q)
        except DirectoryUnavailable as e:
            raise HTTPException(503, f"The office's directory is not available right now: {e}.") from e

    @app.get("/v1/cases/{case_id}/members", response_model=list[Member], responses={404: {"description": "Unknown case"}})
    async def list_members(case_id: str, request: Request):
        """The case's members and their roles, the manager first (anyone who may read the case)."""
        case = await _case_for(request, case_id, "read")
        return await run_in_threadpool(_cases_or_503(request).members, uuid.UUID(case.id))

    @app.put("/v1/cases/{case_id}/members/{user}", response_model=Member, responses={
        403: {"description": "Not the case's manager, or the case is closed"},
        404: {"description": "Unknown case or user"}, 422: {"description": "The manager's role is changed by handing over"}})
    async def set_member(case_id: str, user: str, body: MemberIn, request: Request):
        """Add a colleague to the case as a reader or contributor, or change a member's role (the
        manager's right). The colleague must be one of the office's accounts. To make someone the
        manager, hand the case over (``POST .../handover``)."""
        case = await _case_for(request, case_id, "manage")
        if body.role == "manager":
            raise HTTPException(422, "Hand the case over to make someone its manager.")
        person = await _person_or_404(request, user)
        store, cid = _cases_or_503(request), uuid.UUID(case.id)
        before = await run_in_threadpool(store.role_of, cid, user)
        try:
            member = await run_in_threadpool(store.set_member, cid, user, body.role, owner_of(request),
                                             person.username, person.name)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        await _log(request, cid, "member_added" if before is None else "role_changed", {"user": user, "role": body.role})
        return member

    @app.delete("/v1/cases/{case_id}/members/{user}", status_code=204, responses={
        403: {"description": "Not the case's manager, or the case is closed"},
        404: {"description": "Unknown case or not a member"}, 422: {"description": "The manager can't be removed"}})
    async def remove_member(case_id: str, user: str, request: Request):
        """Take a member out of the case (the manager's right). The manager can't be removed: hand
        the case over first."""
        case = await _case_for(request, case_id, "manage")
        if user == case.manager:
            raise HTTPException(422, "Hand the case over before removing its manager.")
        store, cid = _cases_or_503(request), uuid.UUID(case.id)
        if not await run_in_threadpool(store.remove_member, cid, user):
            raise HTTPException(404, "Not a member of this case.")
        await _log(request, cid, "member_removed", {"user": user})
        return Response(status_code=204)

    @app.post("/v1/cases/{case_id}/handover", response_model=Case, responses={
        403: {"description": "Neither the case's manager nor an administrator"}, 404: {"description": "Unknown case or user"}})
    async def handover(case_id: str, body: HandoverIn, request: Request):
        """Make another colleague the case's manager: the current manager may, and an administrator
        (decision 6: an account can't go while it manages a case). The previous manager stays on as
        a contributor."""
        store, cid, who = _cases_or_503(request), _case_id(case_id), _principal(request)
        case = await run_in_threadpool(store.get, cid, who.sub)
        office_wide = cases_settings.office_wide
        if case is None or not (may(who, case, case.my_role, "read", office_wide) or may(who, case, case.my_role, "list", office_wide)):
            raise HTTPException(404, "Unknown case.")
        if not (may(who, case, case.my_role, "handover", office_wide) or may(who, case, case.my_role, "manage", office_wide)):
            raise HTTPException(403, "Only the case's manager or an administrator can hand a case over.")
        person = await _person_or_404(request, body.user)
        handed = await run_in_threadpool(store.set_manager, cid, body.user, who.sub, person.username, person.name)
        if handed is None:
            raise HTTPException(404, "Unknown case.")
        await _log(request, cid, "handed_over", {"manager": body.user})
        return handed

    @app.get("/v1/cases/{case_id}/events", response_model=list[CaseEvent], responses={
        403: {"description": "Neither the case's manager nor an administrator"}, 404: {"description": "Unknown case"}})
    async def case_events(case_id: str, request: Request):
        """The case's access log, newest first: who did what, when (decision 15). For its manager
        and the administrators; kept 180 days, as the sign-in events."""
        store, cid, who = _cases_or_503(request), _case_id(case_id), _principal(request)
        case = await run_in_threadpool(store.get, cid, who.sub)
        office_wide = cases_settings.office_wide
        if case is None or not (may(who, case, case.my_role, "read", office_wide) or may(who, case, case.my_role, "list", office_wide)):
            raise HTTPException(404, "Unknown case.")
        if not may(who, case, case.my_role, "read_log", office_wide):
            raise HTTPException(403, "Only the case's manager or an administrator can see its access log.")
        return await run_in_threadpool(store.events, cid)

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
        # The case the question is about, if any: asking is a contributor's right (a reader may only
        # read; 404 for a case the caller may not see at all).
        scope = await _scope(request, req.case_id, "contribute")
        if req.document_ids:
            # Before anything streams: only documents in that scope, and only uploaded ones (sūveryn's
            # own output is never a source). An id elsewhere is answered like a missing one. The
            # retriever checks again when it reads the passages.
            docs = _docs_or_503(request)
            if not await run_in_threadpool(docs.in_scope, req.document_ids, scope, True):
                raise HTTPException(404, "Unknown document.")
            if scope.case_id is not None and (store := request.app.state.cases.get()) is not None:
                await run_in_threadpool(store.touch, scope.case_id)
        await _log(request, scope.case_id, "asked", {"documents": req.document_ids})
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
    async def upload_document(request: Request, file: UploadFile = File(...), case: str | None = None):  # noqa: B008 - FastAPI's way to declare a form file
        """Add a PDF to the caller's personal space, or to the case ``case`` (a contributor's right).
        Returns a job immediately; poll ``GET /v1/documents/jobs/{id}`` until it is ``ready`` (or
        ``needs_review``), then use its ``document_id`` in chat requests."""
        docs = _docs_or_503(request)
        scope = await _scope(request, case, "contribute")
        try:
            job = await run_in_threadpool(docs.accept_upload, file.file, file.filename or "document.pdf", owner_of(request),
                                          scope.case_id)
        except UploadRejected as e:
            raise HTTPException(e.status, str(e)) from e
        if scope.case_id is not None and (store := request.app.state.cases.get()) is not None:
            await run_in_threadpool(store.touch, scope.case_id)
        await _log(request, scope.case_id, "uploaded", {"job": job.id})
        return job.public()

    @app.get("/v1/documents/jobs/{job_id}")
    async def document_job(job_id: str, request: Request):
        """State of one of the caller's uploads: queued, processing, ready, needs_review or failed."""
        job = _docs_or_503(request).job(job_id, owner_of(request))
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return job.public()

    @app.get("/v1/documents")
    async def list_documents(request: Request, case: str | None = None):
        """The stored documents (newest first) in the caller's personal space, or in the case ``case``,
        and the caller's uploads there still being processed or failed."""
        docs, owner = _docs_or_503(request), owner_of(request)
        scope = await _scope(request, case, "read")
        stored = await run_in_threadpool(docs.documents, scope)
        return {"documents": [dict(d, id=str(d["id"]), created_at=d["created_at"].isoformat()) for d in stored],
                "jobs": [j.public() for j in docs.pending_jobs(owner, scope)]}

    def _document_id(document_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(document_id)
        except ValueError:
            raise HTTPException(422, "Not a document id.") from None

    def _history_or_none(request: Request) -> ConversationStore | None:
        history: Database = request.app.state.history
        return history.get() if history.configured else None

    @app.delete("/v1/documents/{document_id}", status_code=204)
    async def delete_document(document_id: str, request: Request, conversations: Literal["clean", "delete"] = "clean",
                              case: str | None = None):
        """Delete a document and its passages: one of the caller's own, or one in the case ``case``
        (its manager's right). See ``Store.delete_document`` for what deletion does and doesn't guarantee.

        Saved conversations that cite it (suveryn-tracker#12): with ``conversations=clean`` (the default)
        its passages are taken out of them; with ``conversations=delete`` those conversations are deleted.
        """
        docs, did, owner = _docs_or_503(request), _document_id(document_id), owner_of(request)
        scope = await _scope(request, case, "manage")
        if not await run_in_threadpool(docs.delete, document_id, scope):
            raise HTTPException(404, "Unknown document.")
        await _log(request, scope.case_id, "document_deleted", {"document": document_id})
        if (store := _history_or_none(request)) is not None:
            await run_in_threadpool(store.remove_document, owner, did, conversations == "delete")
        return Response(status_code=204)

    @app.get("/v1/documents/{document_id}/conversations", response_model=list[ConversationSummary])
    async def document_conversations(document_id: str, request: Request):
        """The caller's saved conversations that cite or attach this document (asked before deleting it)."""
        did = _document_id(document_id)
        store = _history_or_none(request)
        return await run_in_threadpool(store.using_document, owner_of(request), did) if store is not None else []

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
    async def list_conversations(request: Request, case: str | None = None):
        """The caller's saved conversations in their personal space, or in the case ``case``, most
        recently changed first (titles and dates, no content)."""
        store = _history_or_503(request)
        scope = await _scope(request, case, "read")
        return await run_in_threadpool(store.summaries, owner_of(request), scope.case_id)

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
        """Save the whole conversation under an id the client chose (a UUID), replacing an earlier save.
        ``case_id`` puts a new conversation in that case (the caller must be able to read it); a
        saved conversation stays where it was first saved."""
        store, cid, owner = _history_or_503(request), _conversation_id(conversation_id), owner_of(request)
        scope = await _scope(request, body.case_id, "read")
        gone = await run_in_threadpool(_deleted_documents, request, body, scope)
        if not await run_in_threadpool(store.save, cid, owner, body, gone):
            raise HTTPException(404, "Unknown conversation.")
        return Response(status_code=204)

    def _deleted_documents(request: Request, body: ConversationIn, scope: Scope):
        """Which documents the conversation cites that no longer exist (suveryn-tracker#12): a tab that
        was open while one was deleted must not save its passages back. None if that can't be known."""
        docs = request.app.state.documents
        if docs is None or docs.state != "ready":
            return None
        cited = cited_documents([t.model_dump() for t in body.turns])
        valid = []
        for d in cited:
            try:
                valid.append(str(uuid.UUID(d)))
            except ValueError:
                continue
        existing = docs.existing(valid, scope) if valid else set()
        return lambda d: d not in existing

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
