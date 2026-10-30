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
import re
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from suveryn_harness import (
    ChatService,
    DocumentsUnavailable,
    LlamaServerClient,
    LLMSettings,
    Meaning,
    UsageRecord,
)

from . import routes
from .auth import Authenticator, AuthError, AuthSettings, AuthUnavailable
from .avatars import MAX_UPLOAD_BYTES as AVATAR_MAX_BYTES
from .avatars import AvatarStore
from .cases import CaseSettings, CaseStore
from .conversations import MAX_BODY_BYTES as MAX_CONVERSATION_BYTES
from .conversations import ConversationSettings, ConversationStore
from .directory import Directory, DirectorySettings, LocalDirectory
from .accounts import Accounts, AccountsSettings, RightsRefused
from .playbooks import RunStore
from .ratelimit import RateLimiter, RateLimits
from .routes.common import (
    ADMIN_ROLE,
    LOCAL_OWNER,
    MAX_UPLOAD_BYTES,
    CleanupUnavailable,
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
SWEEP_RETRY_S = 120  # sooner when a case couldn't be deleted for a store not yet reachable (a restart: VM regression, finding 4)
STALE_RUN_S = 30 * 60    # a playbook run reading this long has lost its model call


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


_RUN_PATH = re.compile(r"^/v1/cases/[^/]+/playbooks/[^/]+/runs$")


def _limit_path(path: str) -> str:
    """The path a per-user limit is keyed on: starting a playbook run is a model call like a question,
    so it shares the chat limit (review 2026-10-17)."""
    return "/v1/chat" if _RUN_PATH.match(path) else path


def _connector(factory, settings):
    """A ``Database.connect`` for ``factory(settings)``, or None without a database URL."""
    return (lambda: factory(settings)) if settings.database_url else None



def sign_in_unavailable(e: Exception) -> JSONResponse:
    """Keycloak can't be reached or has a problem (its database stopped): 503, with ``reason`` for the page."""
    return JSONResponse({"detail": f"Sign-in is not available: {e}.", "reason": "signin"}, status_code=503)

def create_app(client: LlamaServerClient | None = None, documents=None, *, load_documents: bool = True,
               auth: Authenticator | None = None, conversations=None, usage=None, cases=None,
               case_settings: CaseSettings | None = None, directory=None,
               rate_limits: RateLimits | None = None, runs=None, avatars=None, accounts=None) -> FastAPI:
    """Build the FastAPI app.

    ``client``, ``documents``, ``auth``, ``conversations``, ``usage`` and ``cases`` let tests inject a
    fake model server, a fake document service, a sign-in with a fake Keycloak, a conversation store,
    a usage store and a case store; in production all are created from environment variables when
    the app starts. ``case_settings`` sets the appliance's default access for cases (tests);
    ``directory`` injects the office's user list (``directory.py``), ``accounts`` the account management
    of Administration › Users (``accounts.py``).
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

        async def similarity(claims: list[str], sentences: list[str]) -> list[list[float]]:
            # Marking by meaning (suveryn-tracker#25): the search's embedding model, off the event loop.
            if docs is None:
                raise DocumentsUnavailable("document search is not available right now")
            return await run_in_threadpool(docs.similarity, claims, sentences)

        minimum = getattr(getattr(docs, "settings", None), "mark_by_meaning", 0.0) or 0.0
        app.state.chat = ChatService(app.state.llm, retriever, similarity if minimum > 0 else None,
                                     Meaning(minimum) if minimum > 0 else None)
        own_db = load_documents  # tests without documents don't connect to a database
        app.state.history = Database("conversation", conversations, None if conversations is not None or not own_db
                                     else _connector(ConversationStore, ConversationSettings.from_env()))
        app.state.usage = Database("token usage", usage, None if usage is not None or not own_db
                                   else _connector(UsageStore, UsageSettings.from_env()))
        app.state.cases = Database("case", cases, None if cases is not None or not own_db
                                   else _connector(CaseStore, cases_settings))
        # Playbook runs (suveryn-tracker#51) live in the cases' database: no cases, no runs.
        app.state.runs = Database("playbook run", runs, None if runs is not None or not own_db or not cases_settings.database_url
                                  else (lambda: RunStore(cases_settings.database_url)))
        app.state.running = set()  # the asyncio tasks reading for a run, kept until they finish
        app.state.avatars = Database("avatar", avatars, None if avatars is not None or not own_db or not cases_settings.database_url
                                     else (lambda: AvatarStore(cases_settings.database_url)))
        # Administration › Users: Keycloak's accounts, as the administrator who asks (accounts.py)
        app.state.accounts = accounts if accounts is not None else Accounts(AccountsSettings.from_env())
        if directory is not None:
            app.state.directory = directory
        elif not authenticator.enabled:
            app.state.directory = LocalDirectory(LOCAL_OWNER)
        else:
            app.state.directory = Directory(DirectorySettings.from_env())
        for db in (app.state.history, app.state.usage, app.state.cases, app.state.runs, app.state.avatars):
            await run_in_threadpool(db.get)
        # A run reading when the gateway stopped is dead: its model call lived in this process.
        run_store = app.state.runs.get()
        if run_store is not None and (n := await run_in_threadpool(run_store.interrupt, 0)):
            log.warning("%d playbook run(s) interrupted by the restart", n)

        async def record_usage(r: UsageRecord) -> None:
            """The harness's usage hook: store the call's counts (lost, not retried, without a database)."""
            store = app.state.usage.get()
            if store is not None:
                await run_in_threadpool(store.record, r)

        if app.state.llm.on_usage is None:
            app.state.llm.on_usage = record_usage

        async def sweep_due_cases() -> None:
            """Once an hour, for as long as the app runs: delete the closed cases whose keep period has
            passed (docs/design/cases.md, decision 11), with their documents, conversations and log; the
            conversations whose own keep period has passed (the data lifecycle, suveryn-tracker#31); the
            access-log lines older than their retention, and the raw token usage older than its own
            (audit of 21 October 2026, findings 4 and 10); and finish the cleaning of conversations a
            document's deletion left unfinished (finding 3)."""
            while True:
                waiting = False  # a due case left for a store not reachable yet: look again soon, not in an hour
                try:
                    store = app.state.cases.get() if app.state.cases.configured else None
                    if store is not None:
                        await run_in_threadpool(store.purge_events)
                        for cid in await run_in_threadpool(store.due_for_deletion):
                            try:
                                if await delete_case_everywhere(app, cid):
                                    log.info("case %s deleted: its keep period passed", cid)
                            except CleanupUnavailable:
                                waiting = True
                                log.warning("case %s not deleted yet: a store it is in can't be reached", cid)
                    runs_store = app.state.runs.get() if app.state.runs.configured else None
                    if runs_store is not None:
                        await run_in_threadpool(runs_store.interrupt, STALE_RUN_S)  # reading longer than any model call takes
                    history = app.state.history.get() if app.state.history.configured else None
                    if history is not None:
                        settings: CaseSettings = app.state.case_settings
                        if store is not None:
                            settings = settings.with_overrides(await run_in_threadpool(store.overrides))
                        history.keep = settings.conversations_keep
                        await run_in_threadpool(history.purge)
                        if n := await run_in_threadpool(history.finish_cleanups):
                            log.info("%d unfinished conversation cleaning(s) finished", n)
                    usage_store = app.state.usage.get() if app.state.usage.configured else None
                    if usage_store is not None:
                        await run_in_threadpool(usage_store.purge)
                except Exception as e:  # noqa: BLE001 - the sweep must outlive any one failure
                    log.error("sweep: %s", type(e).__name__)
                await asyncio.sleep(SWEEP_RETRY_S if waiting else SWEEP_INTERVAL_S)

        app.state.sweep = (asyncio.create_task(sweep_due_cases())
                           if app.state.cases.configured or app.state.history.configured or app.state.usage.configured else None)
        # Administration › Status: the checks every minute, so a failure's time is when it began (routes/status.py)
        monitor = asyncio.create_task(app.state.status.run(app.state))
        yield
        monitor.cancel()
        if app.state.sweep is not None:
            app.state.sweep.cancel()
        await app.state.llm.aclose()
        await authenticator.aclose()
        if accounts is None:
            await app.state.accounts.aclose()
        if directory is None:
            await app.state.directory.aclose()
        if docs is not None:
            docs.stop()
        for task in list(app.state.running):
            task.cancel()
        for db, injected in ((app.state.history, conversations), (app.state.usage, usage), (app.state.cases, cases),
                             (app.state.runs, runs), (app.state.avatars, avatars)):
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
    app.state.status = routes.status.StatusMonitor()
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
            return sign_in_unavailable(e)
        except AuthError:
            user = None
        if user is None:
            return JSONResponse({"detail": "Sign in to continue."}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer realm="suveryn"'})
        request.state.user = user
        if request.url.path.startswith("/v1/admin/") and ADMIN_ROLE not in user.roles:
            # Administration, refused before anything reads the request's body: a malformed body from someone
            # who isn't an administrator got 422, not 403 (VM regression of 29 October, finding 11). Each route
            # still checks for itself.
            return JSONResponse({"detail": "Only administrators can see this."}, status_code=403)
        limiter = per_user_limits.get((request.method, _limit_path(request.url.path)))
        if limiter is not None and (wait := limiter.hit(user.sub)) is not None:
            return _too_many(wait)
        return await call_next(request)

    @app.exception_handler(SearchUnavailable)
    async def search_unavailable(request: Request, exc: SearchUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(psycopg.OperationalError)
    async def database_unavailable(request: Request, exc: psycopg.OperationalError):
        """The database can't be reached (stopped, restarting): 503 and a sentence, not a 500. The
        next request reconnects (db.PgStore). The error's own text may name the server: not sent."""
        log.error("database unavailable: %s", type(exc).__name__)
        # ``reason``: the page says which part is down in the person's language (api.ts httpErrorText).
        return JSONResponse({"detail": "The database can't be reached right now. Try again shortly.", "reason": "database"},
                            status_code=503)

    @app.exception_handler(RightsRefused)
    async def rights_refused(request: Request, exc: RightsRefused):
        """Users: Keycloak refused the administrator's rights. Two causes, each with its own sentence: the
        caller's rights were removed meanwhile, by another administrator (their session still says
        administrator until it is renewed; VM check of 29 October, round 3, finding 2: the one who lost a
        race was told to reinstall), or the role lost its rights, which an install brings back (VM check of
        28 October, finding 11). The directory's service account tells which."""
        directory = getattr(app.state, "directory", None)
        holds = await directory.holds_admin(owner_of(request)) if directory is not None and hasattr(directory, "holds_admin") else None
        if holds is False:
            log.info("accounts: an administrator's rights were removed meanwhile")
            return JSONResponse({"detail": "Your administrator rights were removed meanwhile.", "reason": "rights_removed"},
                                status_code=403)
        log.warning("accounts: %s", exc)
        return JSONResponse({"detail": str(exc), "reason": "rights"}, status_code=503)

    @app.exception_handler(AuthUnavailable)
    async def auth_unavailable(request: Request, exc: AuthUnavailable):
        return sign_in_unavailable(exc)

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
        if request.method == "PUT" and request.url.path == "/v1/me/avatar":
            length = request.headers.get("content-length")
            if length is None or not length.isdigit() or int(length) > AVATAR_MAX_BYTES:
                return JSONResponse({"detail": "The picture is larger than 2 MB."}, status_code=413)
        if request.method == "PUT" and request.url.path.startswith("/v1/conversations/"):
            length = request.headers.get("content-length")
            if length is None or not length.isdigit() or int(length) > MAX_CONVERSATION_BYTES:
                return JSONResponse({"detail": "This conversation is too long to save."}, status_code=413)
        return await call_next(request)

    for module in (routes.signin, routes.health, routes.cases, routes.playbooks, routes.avatars, routes.chat, routes.documents,
                   routes.conversations, routes.usage, routes.backups, routes.status, routes.users):
        app.include_router(module.router)
    return app


app = create_app()
