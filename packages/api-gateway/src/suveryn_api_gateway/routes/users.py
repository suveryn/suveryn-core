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

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..accounts import Account, AccountEvent, AccountRefused, Accounts, AccountsUnavailable, RightsRefused
from ..auth import AuthError, AuthUnavailable
from .common import admin_or_403, owner_of

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
    address, then chooses a password and sets up two-step sign-in."""
    accounts, token = await as_admin(request)
    user, password = await _do(accounts.add(token, body.name, body.email, body.admin))
    return _temporary(request, user, password)


@router.put("/v1/admin/users/{sub}/admin", response_model=Account, responses={
    403: {"description": "Not an administrator"}, 409: {"description": "The last administrator"}})
async def set_admin(sub: str, body: AdminIn, request: Request):
    """Make someone an administrator, or remove the rights; never the last administrator's."""
    accounts, token = await as_admin(request)
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
    """The person sets up two-step sign-in again at the next sign-in."""
    accounts, token = await as_admin(request)
    await _do(accounts.reset_two_step(token, sub))


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
    return await _do(accounts.events(token, known, limit))
