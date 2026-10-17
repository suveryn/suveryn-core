"""What the route modules share: the caller, the scope, the stores, and the stand-ins for
``suveryn_rag`` when it isn't installed (the gateway runs without documents then)."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..auth import Authenticator
from ..cases import Case, CaseSettings, CaseStore, Principal, may
from ..conversations import ConversationStore
from ..directory import DirectoryUnavailable, Person
from ..usage import UsageStore

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

__all__ = ["MAX_UPLOAD_BYTES", "DocumentNotFound", "Scope", "SearchUnavailable", "UploadRejected"]

log = logging.getLogger("suveryn.gateway")

ADMIN_ROLE = "suveryn-admin"  # Keycloak realm role for the administration page (usage per user, rates)
LOCAL_OWNER = "local-dev"  # owner of documents when sign-in is off (SUVERYN_AUTH=off, loopback only)


class StoreStatus(BaseModel):
    """State of a database-backed feature (saved conversations, token usage): "ready", "failed"
    (database unreachable) or "unavailable" (no database configured)."""

    status: str
    detail: str | None = None


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


# ------------------------------------------------------------------ the caller
def owner_of(request: Request) -> str:
    """Whose documents this request may touch: the signed-in user's Keycloak id (``sub``)."""
    user = getattr(request.state, "user", None)
    return user.sub if user is not None else LOCAL_OWNER


def is_admin(request: Request, authenticator: Authenticator) -> bool:
    """Administrators have the Keycloak realm role ``suveryn-admin``; with sign-in off (loopback
    development only) the local user is one."""
    if not authenticator.enabled:
        return True
    user = getattr(request.state, "user", None)
    return user is not None and ADMIN_ROLE in user.roles


def principal(request: Request) -> Principal:
    return Principal(sub=owner_of(request), admin=is_admin(request, request.app.state.auth))


def who(request: Request) -> tuple[str, str]:
    """The caller's username and display name, for the member list."""
    user = getattr(request.state, "user", None)
    return (user.username, user.name) if user is not None else ("dev", "Development (sign-in off)")


def admin_or_403(request: Request) -> None:
    if not is_admin(request, request.app.state.auth):
        raise HTTPException(403, "Only administrators can see this.")


async def remember_user(request: Request) -> None:
    """Keep the asker's username for the administrator's usage table (once per name change)."""
    user = getattr(request.state, "user", None)
    known: set[tuple[str, str, str]] = request.app.state.known_users
    if user is None or (key := (user.sub, user.username, user.name)) in known:
        return
    store = request.app.state.usage.get()
    if store is not None:
        try:
            await run_in_threadpool(store.remember_user, *key)
            known.add(key)
        except Exception as e:  # noqa: BLE001 - informational; never blocks a question
            log.error("usage user not remembered: %s", type(e).__name__)


# ------------------------------------------------------------------ the stores
def docs_or_503(request: Request):
    docs = request.app.state.documents
    if docs is None:
        raise HTTPException(503, "Document handling is not available on this server.")
    if docs.state != "ready":
        raise HTTPException(503, f"Document handling is {docs.state}." + (f" {docs.error}" if docs.error else ""))
    return docs


def cases_or_503(request: Request) -> CaseStore:
    db: Database = request.app.state.cases
    if not db.configured:
        raise HTTPException(503, "Cases are not available on this server.")
    store = db.get()
    if store is None:
        raise HTTPException(503, f"Cases are not available right now: {db.error}.")
    return store


def history_or_none(request: Request) -> ConversationStore | None:
    history: Database = request.app.state.history
    return history.get() if history.configured else None


def history_or_503(request: Request) -> ConversationStore:
    history: Database = request.app.state.history
    if not history.configured:
        raise HTTPException(503, "Saved conversations are not available on this server.")
    store = history.get()
    if store is None:
        raise HTTPException(503, f"Saved conversations are not available right now: {history.error}.")
    return store


def usage_or_503(request: Request) -> UsageStore:
    db: Database = request.app.state.usage
    if not db.configured:
        raise HTTPException(503, "Token usage is not available on this server.")
    store = db.get()
    if store is None:
        raise HTTPException(503, f"Token usage is not available right now: {db.error}.")
    return store


# ------------------------------------------------------------------ cases and the scope
def case_settings(request: Request) -> CaseSettings:
    """The office's case settings as they apply now: what the appliance was provisioned with
    (``app.state.case_settings``, from the environment) with what an administrator chose since in
    the dashboard on top (``CaseStore.overrides``, stage 4). Without a case store, as provisioned."""
    base: CaseSettings = request.app.state.case_settings
    db: Database = request.app.state.cases
    store = db.get() if db.configured else None
    overrides = getattr(store, "overrides", None)
    return base.with_overrides(overrides()) if overrides is not None else base


def case_id_or_422(case_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(422, "Not a case id.") from None


async def visible_case(request: Request, case_id: str) -> tuple[CaseStore, uuid.UUID, Principal, Case]:
    """The case, if the caller may see it at all (read it, or list it as an administrator); else
    404, like a missing one. The caller decides the right for the action itself."""
    store, cid, caller = cases_or_503(request), case_id_or_422(case_id), principal(request)
    case = await run_in_threadpool(store.get, cid, caller.sub)
    office_wide = case_settings(request).office_wide
    if case is None or not (may(caller, case, case.my_role, "read", office_wide)
                            or may(caller, case, case.my_role, "list", office_wide)):
        raise HTTPException(404, "Unknown case.")
    if case.my_role is None and office_wide and case.access == "default":
        case = case.model_copy(update={"my_role": "reader"})  # rule 3, as the list reports it
    return store, cid, caller, case


async def case_for(request: Request, case_id: str, action: str) -> Case:
    """The case, if the caller may do ``action`` in it; else 404 (a case they may not see is
    answered like a missing one) or 403 (they may see it, not do this)."""
    _, _, caller, case = await visible_case(request, case_id)
    if not may(caller, case, case.my_role, action, case_settings(request).office_wide):
        raise HTTPException(403, "You may not do this in this case." if case.state == "open" else "This case is closed.")
    return case


async def log_access(request: Request, case_id: uuid.UUID | None, action: str, detail: dict | None = None) -> None:
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


async def person_or_404(request: Request, sub: str) -> Person:
    """A colleague by their id, from the office's directory (404 if not an enabled account)."""
    try:
        found = await request.app.state.directory.get(sub)
    except DirectoryUnavailable as e:
        raise HTTPException(503, f"The office's directory is not available right now: {e}.") from e
    if found is None:
        raise HTTPException(404, "Unknown user.")
    return found


async def scope_of(request: Request, case: str | None, action: str) -> Scope:
    """Where a request works: the caller's personal space, or the case ``case`` if they may do
    ``action`` in it (``read`` to list and ask, ``contribute`` to upload, ``manage`` to delete)."""
    if not case:
        return Scope.personal(owner_of(request))
    found = await case_for(request, case, action)
    return Scope.case(uuid.UUID(found.id))


async def touch_case(request: Request, scope: Scope) -> None:
    """Note activity in the scope's case, if it is one: the case list is ordered by it."""
    if scope.case_id is not None and (store := request.app.state.cases.get()) is not None:
        await run_in_threadpool(store.touch, scope.case_id)


async def delete_case_everywhere(app: FastAPI, case_id: uuid.UUID) -> bool:
    """Delete a case with its documents (and their index), conversations, members and log. False if
    the case doesn't exist. See ``Store.delete_document`` for what deletion does and doesn't guarantee."""
    docs = app.state.documents
    if docs is not None and docs.state == "ready":
        await run_in_threadpool(docs.delete_all, Scope.case(case_id))
    elif docs is not None:
        return False  # the documents can't be deleted now: the case stays, the next sweep tries again
    history: Database = app.state.history
    if history.configured and (store := history.get()) is not None:
        await run_in_threadpool(store.delete_case, case_id)
    cases: Database = app.state.cases
    store = cases.get()
    return store is not None and await run_in_threadpool(store.delete, case_id)
