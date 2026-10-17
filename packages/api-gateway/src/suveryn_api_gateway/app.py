"""FastAPI application: builds the app, gates it, and includes the routes (``routes/``).

The routes are one module per area in ``routes/`` (sign-in, health, cases, chat, documents,
conversations, usage); they read what they need from ``app.state``, which ``create_app`` sets.
This module keeps what is about the app as a whole: its lifespan (the model client, the document
service, the stores, the hourly case sweep), the sign-in middleware with the rate limits, the
upload-size limit, and the access-log filter.

Ownership: a document, its upload and job, and a conversation are in one scope: the uploader's
personal space, or a case (``cases.py``, suveryn-tracker#10). A request names the case it works
in (``?case=`` on documents and conversations, ``case_id`` in a chat request); without one it is
in the caller's personal space. The scope is decided once per request (``routes.common.scope_of``): the personal
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

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from suveryn_chat import ChatService, DocumentsUnavailable
from suveryn_engine import LlamaServerClient, LLMSettings, UsageRecord

from . import routes
from .auth import Authenticator, AuthError, AuthSettings, AuthUnavailable
from .cases import CaseSettings, CaseStore
from .conversations import MAX_BODY_BYTES as MAX_CONVERSATION_BYTES
from .conversations import ConversationSettings, ConversationStore
from .directory import Directory, DirectorySettings, LocalDirectory
from .ratelimit import RateLimiter, RateLimits
from .routes.common import (
    ADMIN_ROLE,
    LOCAL_OWNER,
    MAX_UPLOAD_BYTES,
    Database,
    DocumentNotFound,
    Scope,
    SearchUnavailable,
    UploadRejected,
    delete_case_everywhere,
    owner_of,
)
from .usage import UsageSettings, UsageStore

# Names other modules and the tests take from here; the routes own them now.
_delete_case_everywhere = delete_case_everywhere
__all__ = ["ADMIN_ROLE", "LOCAL_OWNER", "MAX_UPLOAD_BYTES", "DocumentNotFound", "Scope", "SearchUnavailable",
           "UploadRejected", "create_app", "owner_of"]

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

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# With sign-in off, only these clients may use /v1: this machine ("testclient" is Starlette's test client).
LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}
SWEEP_INTERVAL_S = 3600  # how often closed cases past their keep period are deleted


def _too_many(wait: int) -> JSONResponse:
    return JSONResponse({"detail": f"Too many requests. Try again in {wait} seconds."}, status_code=429,
                        headers={"Retry-After": str(wait)})


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


def _connector(factory, settings):
    """A ``Database.connect`` for ``factory(settings)``, or None without a database URL."""
    return (lambda: factory(settings)) if settings.database_url else None


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

        async def sweep_due_cases() -> None:
            """Delete the closed cases whose keep period has passed (docs/design/cases.md, decision 11),
            with their documents, conversations and log: once an hour, for as long as the app runs."""
            while True:
                try:
                    store = app.state.cases.get()
                    if store is not None:
                        for cid in await run_in_threadpool(store.due_for_deletion):
                            if await delete_case_everywhere(app, cid):
                                log.info("case %s deleted: its keep period passed", cid)
                except Exception as e:  # noqa: BLE001 - the sweep must outlive any one failure
                    log.error("case sweep: %s", type(e).__name__)
                await asyncio.sleep(SWEEP_INTERVAL_S)

        app.state.sweep = asyncio.create_task(sweep_due_cases()) if app.state.cases.configured else None
        yield
        if app.state.sweep is not None:
            app.state.sweep.cancel()
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

    # What the routes read (routes/common.py): set before the app starts, unchanged after.
    app.state.auth = authenticator
    app.state.case_settings = cases_settings
    app.state.known_users = set()  # (sub, username, name) already stored for the usage table
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

    # The order matters where paths overlap: /v1/cases/due before /v1/cases/{case_id} (both in cases).
    for module in (routes.signin, routes.health, routes.cases, routes.chat, routes.documents, routes.conversations, routes.usage):
        app.include_router(module.router)
    return app


app = create_app()
