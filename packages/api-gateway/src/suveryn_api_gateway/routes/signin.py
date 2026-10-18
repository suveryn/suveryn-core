"""Sign-in: the OIDC login with the local Keycloak (``auth.py``), who is signed in, and logout.

Public (no session needed): these are how one gets a session. The middleware that gates ``/v1``
is in ``app.py``.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..auth import LOGIN_COOKIE, LOGIN_TTL_S, Authenticator, AuthError, AuthUnavailable
from .common import ADMIN_ROLE, LOCAL_OWNER, case_settings

UI_LANGUAGES = {"en", "nl", "fr"}  # the chat UI's languages, passed on to Keycloak's login page

router = APIRouter()


class Me(BaseModel):
    """The signed-in user, for the UI."""

    username: str
    name: str
    sub: str = ""        # the Keycloak id: what owns documents and conversations, and whom a shared one names
    admin: bool = False  # may open the administration page (realm role ``suveryn-admin``)
    office_wide: bool = False  # the appliance's default access for cases (SUVERYN_CASES_DEFAULT_ACCESS=office)
    cases_keep: str = "manual"  # how long a closed case is kept before deletion (SUVERYN_CASES_KEEP)
    avatar: str | None = None   # the ETag of the user's picture, None without one (initials are shown)


def _auth(request: Request) -> Authenticator:
    return request.app.state.auth


def _cookie(request: Request, response: Response, name: str, value: str, max_age: int | None) -> None:
    response.set_cookie(name, value, max_age=max_age, path="/", httponly=True, samesite="lax",
                        secure=_auth(request).settings.secure_cookies)


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request, return_to: str = "/", lang: str | None = None):
    """Start signing in: redirect to the Keycloak login page, in the UI's language (``lang``: en, nl or fr)."""
    try:
        url, login_cookie = await _auth(request).start_login(return_to)
    except AuthUnavailable as e:
        raise HTTPException(503, f"Sign-in is not available: {e}.") from e
    if lang in UI_LANGUAGES:
        url += f"&ui_locales={lang}"  # OIDC: Keycloak shows its login page in this language
    response = RedirectResponse(url, status_code=303)
    _cookie(request, response, LOGIN_COOKIE, login_cookie, LOGIN_TTL_S)
    return response


@router.get("/auth/callback", include_in_schema=False)
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    """Keycloak sends the browser back here with a code; exchange it and start a session."""
    if error or not code or not state:
        raise HTTPException(400, "Sign-in was cancelled or failed. Close this page and sign in again.")
    try:
        session, return_to = await _auth(request).finish_login(code, state, request.cookies.get(LOGIN_COOKIE))
    except AuthError as e:
        raise HTTPException(400, f"Sign-in failed: {e}.") from e
    except AuthUnavailable as e:
        raise HTTPException(503, f"Sign-in is not available: {e}.") from e
    response = RedirectResponse(return_to, status_code=303)
    response.delete_cookie(LOGIN_COOKIE, path="/")
    _cookie(request, response, _auth(request).settings.session_cookie, session.id, None)  # a browser-session cookie
    return response


@router.get("/auth/me", response_model=Me, responses={401: {"description": "Not signed in"}})
async def me(request: Request):
    """The signed-in user (username and display name), or 401."""
    authenticator, cases = _auth(request), case_settings(request)
    if not authenticator.enabled:
        return Me(username="dev", name="Development (sign-in off)", sub=LOCAL_OWNER, admin=True, office_wide=cases.office_wide,
                  cases_keep=cases.keep, avatar=await _avatar_etag(request, LOCAL_OWNER))
    try:
        user = await authenticator.session_user(request.cookies.get(authenticator.settings.session_cookie))
    except AuthUnavailable as e:
        raise HTTPException(503, f"Sign-in is not available: {e}.") from e
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return Me(username=user.username, name=user.name, sub=user.sub, admin=ADMIN_ROLE in user.roles, office_wide=cases.office_wide,
              cases_keep=cases.keep, avatar=await _avatar_etag(request, user.sub))


async def _avatar_etag(request: Request, sub: str) -> str | None:
    """The ETag of the user's picture, if the avatar store is there (never an error: initials otherwise)."""
    from fastapi.concurrency import run_in_threadpool

    db = request.app.state.avatars
    store = db.get() if db.configured else None
    return await run_in_threadpool(store.etag, sub) if store is not None else None


@router.post("/auth/logout")
async def logout(request: Request):
    """End the session; ``logout_url`` ends the Keycloak session too (the UI navigates there)."""
    authenticator = _auth(request)
    origin = request.headers.get("origin")
    if authenticator.enabled and origin is not None and origin != authenticator.settings.public_origin:
        raise HTTPException(403, "Request from another site refused.")
    url = await authenticator.logout(request.cookies.get(authenticator.settings.session_cookie))
    response = JSONResponse({"logout_url": url})
    response.delete_cookie(authenticator.settings.session_cookie, path="/")
    return response
