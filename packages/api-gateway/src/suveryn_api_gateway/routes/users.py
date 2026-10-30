"""Administration › Users (docs/design/admin.md, artboards 32 and 34): the office's accounts, administrators only.

The gateway holds the rules, not only the page:
- **always one administrator**: removing the rights of, or switching off, the last administrator is refused;
- **not your own account**: an administrator can't switch their own account off;
- **cases first**: an account that manages cases is switched off only once each has a new manager (the
  hand-over of ``POST /v1/cases/{id}/handover``), so no case is left without one (cases.md decision 6).

Every call to Keycloak is made as the administrator who asked, with their own access token (``accounts.py``):
a fresh one from their session, or the bearer token a non-browser client sent. Keycloak's admin events are
the record of what changed and who changed it; the gateway keeps none of its own.

A temporary password is in the answer once and nowhere else: not logged, not stored.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..accounts import Account, AccountEvent, AccountRefused, Accounts, AccountsUnavailable, RightsRefused
from ..auth import AuthError, AuthUnavailable
from .common import Scope, admin_or_403, case_settings, cases_or_503, docs_or_503, history_or_503, owner_of

log = logging.getLogger("suveryn.gateway")
router = APIRouter()


class UsersOut(BaseModel):
    users: list[Account]
    # how many accounts the support agreement covers, once the appliance reads it (suveryn-tracker#41)
    agreement_users: int | None = None


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    admin: bool = False


class Temporary(BaseModel):
    """A temporary password to pass on, shown once: where to sign in, and with what."""

    user: Account
    address: str
    password: str


class AdminIn(BaseModel):
    admin: bool


class EnabledIn(BaseModel):
    enabled: bool


async def as_admin(request: Request) -> tuple[Accounts, str]:
    """The accounts, and the access token to change them with: the administrator's own (a 403 for anyone else)."""
    admin_or_403(request)
    accounts: Accounts = request.app.state.accounts
    if not accounts.configured:
        raise HTTPException(503, "Account management isn't configured on this server.")
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return accounts, header[7:].strip()
    auth = request.app.state.auth
    try:
        return accounts, await auth.fresh_access_token(request.cookies.get(auth.settings.session_cookie))
    except AuthError as e:
        raise HTTPException(401, "Sign in to continue.") from e
    except AuthUnavailable as e:
        raise HTTPException(503, "The sign-in service can't be reached.") from e


async def _do(call):
    try:
        return await call
    except AccountRefused as e:
        if e.code == "not_found":
            raise HTTPException(404, "No such account.") from e
        if e.code == "exists":
            raise HTTPException(409, "An account with this e-mail address exists.") from e
        raise HTTPException(409, e.code) from e
    except RightsRefused:
        raise  # app.py: 503 with reason "rights", which the page says in its own sentence
    except AccountsUnavailable as e:
        raise HTTPException(503, str(e)) from e


def _temporary(request: Request, user: Account, password: str) -> Temporary:
    address = request.app.state.auth.settings.public_url or str(request.base_url).rstrip("/")
    return Temporary(user=user, address=address, password=password)


def _admin_changes(request: Request) -> asyncio.Lock:
    """One change at a time that could leave the office without an administrator: the check and the change
    happen under this lock, so two administrators removing each other's rights in the same instant can't both
    pass the check (external review, pass 7). One gateway per appliance, so a lock in it is enough; a change
    made in Keycloak's own console is outside it, as it is outside every rule here."""
    lock = getattr(request.app.state, "admin_changes", None)
    if lock is None:
        lock = request.app.state.admin_changes = asyncio.Lock()
    return lock


async def _admins(accounts: Accounts, token: str) -> list[Account]:
    return [a for a in await _do(accounts.everyone(token)) if a.admin and a.enabled]


@router.get("/v1/admin/users", response_model=UsersOut, responses={403: {"description": "Not an administrator"}})
async def users(request: Request):
    """Every person's account: name, e-mail, administrator or not, on or off, last sign-in."""
    accounts, token = await as_admin(request)
    return UsersOut(users=await _do(accounts.everyone(token)))


@router.post("/v1/admin/users", response_model=Temporary, status_code=201,
             responses={403: {"description": "Not an administrator"}, 409: {"description": "The e-mail address has an account"}})
async def add_user(body: NewUser, request: Request):
    """A new account, with a temporary password to pass on (shown once). The person signs in with the e-mail
    address, then chooses a password, and sets up two-step sign-in when the office requires it (Settings)."""
    accounts, token = await as_admin(request)
    user, password = await _do(accounts.add(token, body.name, body.email, body.admin, two_step=case_settings(request).two_step))
    return _temporary(request, user, password)


@router.put("/v1/admin/users/{sub}/admin", response_model=Account, responses={
    403: {"description": "Not an administrator"}, 409: {"description": "The last administrator"}})
async def set_admin(sub: str, body: AdminIn, request: Request):
    """Make someone an administrator, or remove the rights; never the last administrator's."""
    accounts, token = await as_admin(request)
    async with _admin_changes(request):
        user = await _do(accounts.get(token, sub))
        if not body.admin and user.admin and [a.sub for a in await _admins(accounts, token)] == [sub]:
            raise HTTPException(409, "There must always be one administrator.")
        if user.admin != body.admin:
            await _do(accounts.set_admin(token, sub, body.admin))
    return user.model_copy(update={"admin": body.admin})


@router.post("/v1/admin/users/{sub}/password", response_model=Temporary, responses={403: {"description": "Not an administrator"}})
async def reset_password(sub: str, request: Request):
    """A new temporary password: the current one stops working."""
    accounts, token = await as_admin(request)
    user = await _do(accounts.get(token, sub))
    password = await _do(accounts.reset_password(token, sub))
    return _temporary(request, user, password)


@router.post("/v1/admin/users/{sub}/two-step", status_code=204, responses={403: {"description": "Not an administrator"}})
async def reset_two_step(sub: str, request: Request):
    """The authenticator app removed (a lost phone): the person sets it up again at the next sign-in when the office
    requires two-step sign-in, and may otherwise."""
    accounts, token = await as_admin(request)
    await _do(accounts.reset_two_step(token, sub, require=case_settings(request).two_step))


@router.post("/v1/admin/users/{sub}/sign-out", status_code=204, responses={403: {"description": "Not an administrator"}})
async def sign_out(sub: str, request: Request):
    """Signed out on every device; they can sign in again straight away."""
    accounts, token = await as_admin(request)
    await _do(accounts.sign_out(token, sub))
    request.app.state.auth.drop_user(sub)  # this gateway's own sessions too, not only Keycloak's


@router.put("/v1/admin/users/{sub}/enabled", response_model=Account, responses={
    403: {"description": "Not an administrator"},
    409: {"description": "Your own account, the last administrator, or the account still manages cases"}})
async def set_enabled(sub: str, body: EnabledIn, request: Request):
    """Switch an account off, or on again. Off: not your own, not the last administrator, and only once every
    case it manages has a new manager."""
    accounts, token = await as_admin(request)
    async with _admin_changes(request):
        user = await _do(accounts.get(token, sub))
        if not body.enabled:
            if sub == owner_of(request):
                raise HTTPException(409, "You can't switch your own account off.")
            if user.admin and [a.sub for a in await _admins(accounts, token)] == [sub]:
                raise HTTPException(409, "There must always be one administrator.")
            cases = request.app.state.cases
            store = cases.get() if cases.configured else None
            if store is not None and (n := await run_in_threadpool(store.manages, sub)):
                raise HTTPException(409, f"This account still manages {n} case{'s' if n != 1 else ''}: hand them over first.")
        if user.enabled != body.enabled:
            await _do(accounts.set_enabled(token, sub, body.enabled))
            if not body.enabled:
                request.app.state.auth.drop_user(sub)  # signed out here too, at once
    return user.model_copy(update={"enabled": body.enabled})


@router.get("/v1/admin/users/events", response_model=list[AccountEvent], responses={403: {"description": "Not an administrator"}})
async def events(request: Request, limit: int = 20):
    """*Sign-ins and changes*, newest first: Keycloak's sign-in events and its admin events on accounts, kept 180
    days, each change with the administrator who made it. Names and actions only."""
    accounts, token = await as_admin(request)
    limit = max(1, min(limit, 200))
    known = {a.sub: a.name for a in await _do(accounts.everyone(token))}
    cases = request.app.state.cases
    store = cases.get() if cases.configured else None
    if store is not None:  # a deleted account's sign-ins and its deletion keep its name
        known = {**await run_in_threadpool(store.departed_names), **known}
    return await _do(accounts.events(token, known, limit))


# ------------------------------------------------------------------ deleting an account
class Deletion(BaseModel):
    """What deleting an account removes (its own space) and what stays with its cases."""

    documents: int = 0              # its own documents, outside any case
    conversations: int = 0          # its conversations nobody else can read
    shared_conversations: int = 0   # shared with a case: they stay there, under its name


def _stores(request: Request):
    """Every store the account's own space is in; a configured one that can't be reached stops the deletion (503),
    so nothing is half deleted. One that isn't configured here (a development machine) holds nothing."""
    docs = docs_or_503(request) if request.app.state.documents is not None else None
    history = history_or_503(request) if request.app.state.history.configured else None
    avatars_db = request.app.state.avatars
    avatars = avatars_db.get() if avatars_db.configured else None
    if avatars_db.configured and avatars is None:
        raise HTTPException(503, "Pictures are not available right now.")
    return docs, history, avatars


async def _deletable(request: Request, accounts: Accounts, token: str, sub: str) -> Account:
    user = await _do(accounts.get(token, sub))
    if sub == owner_of(request):
        raise HTTPException(409, "You can't delete your own account.")
    if user.enabled:
        raise HTTPException(409, "Switch the account off first.")  # Filip, 29 October: a deliberate second step
    if request.app.state.cases.configured and (n := await run_in_threadpool(cases_or_503(request).manages, sub)):
        raise HTTPException(409, f"This account still manages {n} case{'s' if n != 1 else ''}: hand them over first.")
    return user


@router.get("/v1/admin/users/{sub}/deletion", response_model=Deletion, responses={
    403: {"description": "Not an administrator"}, 409: {"description": "Your own account, one that is on, or one that manages cases"}})
async def deletion(sub: str, request: Request):
    """What deleting this account would remove, for the confirmation: counts only."""
    accounts, token = await as_admin(request)
    await _deletable(request, accounts, token, sub)
    docs, history, _ = _stores(request)
    out = Deletion()
    if docs is not None:
        out.documents = len(await run_in_threadpool(docs.documents, Scope.personal(sub)))
    if history is not None:
        out.conversations = await run_in_threadpool(history.personal, sub)
        out.shared_conversations = await run_in_threadpool(history.shared_count, sub)
    return out


@router.delete("/v1/admin/users/{sub}", status_code=204, responses={
    403: {"description": "Not an administrator"}, 409: {"description": "Your own account, one that is on, or one that manages cases"}})
async def delete_user(sub: str, request: Request):
    """Delete an account (Filip, 29 October). Only one that is switched off, so its cases are handed over already.
    Its own space goes with it: its documents outside a case, the conversations nobody else can read, its picture,
    its pins. What it did in its cases stays with them under its name: documents it added, conversations it
    shared, the access log. Then the account itself, in Keycloak. Usage keeps its counts. Repeatable: a step
    that failed is done again."""
    accounts, token = await as_admin(request)
    user = await _deletable(request, accounts, token, sub)
    docs, history, avatars = _stores(request)
    cases = cases_or_503(request) if request.app.state.cases.configured else None
    # Every store was reached above; nothing is deleted yet. From here a failed step leaves the account in
    # Keycloak, switched off, with part of its own space gone: said in its own sentence, not "unavailable",
    # and deleting again finishes it, as every step is repeatable (external audit, 29 October).
    try:
        if docs is not None:
            await run_in_threadpool(docs.delete_all, Scope.personal(sub))
        if history is not None:
            await run_in_threadpool(history.delete_personal, sub)
        if avatars is not None:
            await run_in_threadpool(avatars.remove, sub)
        if cases is not None:
            await run_in_threadpool(cases.depart, sub, user.username, user.name, owner_of(request))
        try:
            await accounts.delete(token, sub)
        except AccountRefused as e:
            if e.code != "not_found":  # not found: gone already, which is what was asked
                raise
    except RightsRefused:
        raise  # its own sentence (app.py); deleting again once the rights are back finishes it
    except Exception as e:  # noqa: BLE001 - whichever step failed, the answer is the same
        log.warning("account %s: deletion stopped partway (%s); deleting again finishes it", sub, type(e).__name__)
        return JSONResponse({"detail": "The deletion stopped partway: the account is still there, switched off, and part "
                                       "of its own space may be gone. Delete it again to finish.", "reason": "unfinished"},
                            status_code=503)
    request.app.state.auth.drop_user(sub)
    log.info("account %s deleted by an administrator", sub)
