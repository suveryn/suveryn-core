"""Sign-in with the local Keycloak (OpenID Connect), and the session that gates the API.

Pattern: backend-for-frontend. The gateway is a *confidential* OIDC client of the local Keycloak and
runs the authorization-code flow with PKCE (S256) itself. Tokens stay in the gateway's memory; the
browser only gets an opaque session cookie (HttpOnly, SameSite=Lax, ``Secure`` and ``__Host-``
prefixed when the public URL is https). No token is ever readable by JavaScript in the UI.

Flow:
1. ``GET /auth/login``: a random ``state``, ``nonce`` and PKCE verifier are kept server-side for ten
   minutes; ``state`` is also set in a short-lived cookie, so the callback is bound to the browser
   that started it (prevents login CSRF). The browser is redirected to Keycloak's login page.
2. ``GET /auth/callback``: checks ``state`` against that cookie, exchanges the code (with the PKCE
   verifier and the client secret) at Keycloak's token endpoint, and validates the ID token.
3. A session is created and its id set as the session cookie. Every API request (``/v1/...``)
   needs a valid session, or a bearer access token for non-browser clients.
4. Shortly before the access token expires, the gateway refreshes it with the refresh token. If
   Keycloak refuses (user disabled, session ended or logged out by an admin), the session is
   dropped and the next request gets 401. So revocation takes effect within one access-token
   lifetime (5 minutes in the dev realm).
5. ``POST /auth/logout``: drops the session and returns Keycloak's end-session URL, which ends the
   Keycloak session too.

Token validation (``OIDCProvider.verify``): signature against Keycloak's published keys (JWKS),
only the algorithms in ``AuthSettings.algorithms`` (RS256; never ``none`` or HMAC), issuer, expiry,
audience (ID token) or authorised party (access token), and the nonce of an ID token.

Identity providers: by design only Keycloak's own users (local accounts, optionally federated
from LDAP/Active Directory, optionally with TOTP) can sign in. Social or online identity providers
are not supported at any tier; see ``keycloak/README.md``.

Review notes:
- Sessions and pending logins live in this process's memory: a gateway restart signs everyone out
  (Keycloak's own session usually lets them straight back in). Multi-process deployments need a
  shared session store.
- Tokens contain the user's name and username, not document data. Nothing here logs tokens,
  codes or cookies.
"""

import asyncio
import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass, field, replace
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from jwt import PyJWK

LOGIN_TTL_S = 600         # a login must be completed within ten minutes
REFRESH_MARGIN_S = 30     # refresh the access token this long before it expires
CLOCK_LEEWAY_S = 30       # tolerated clock difference between gateway and Keycloak
JWKS_MIN_REFRESH_S = 60   # re-read Keycloak's keys at most once a minute (on an unknown key id)
MAX_PENDING_LOGINS = 1000
MAX_SESSIONS = 10_000
LOGIN_COOKIE = "suveryn_login"


class AuthError(Exception):
    """Sign-in failed or a token is invalid. The message is safe to show (no token content)."""


class AuthUnavailable(Exception):
    """Keycloak can't be reached or isn't configured."""


@dataclass(frozen=True)
class AuthSettings:
    """Sign-in settings, from ``SUVERYN_*`` environment variables (see the package README)."""

    issuer: str = ""          # e.g. http://localhost:8180/realms/suveryn
    client_id: str = "suveryn-chat"
    client_secret: str = ""
    public_url: str = ""      # the URL people open the chat UI at, e.g. https://suveryn.office.local
    disabled: bool = False    # SUVERYN_AUTH=off: development only, loopback only (enforced in main.py)
    algorithms: tuple[str, ...] = ("RS256",)

    @classmethod
    def from_env(cls) -> "AuthSettings":
        return cls(
            issuer=os.environ.get("SUVERYN_OIDC_ISSUER", "").rstrip("/"),
            client_id=os.environ.get("SUVERYN_OIDC_CLIENT_ID", cls.client_id),
            client_secret=os.environ.get("SUVERYN_OIDC_CLIENT_SECRET", ""),
            public_url=os.environ.get("SUVERYN_PUBLIC_URL", "").rstrip("/"),
            disabled=os.environ.get("SUVERYN_AUTH", "").lower() == "off",
        )

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.client_id and self.client_secret and self.public_url)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    @property
    def public_origin(self) -> str:
        u = urlsplit(self.public_url)
        return f"{u.scheme}://{u.netloc}"

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def session_cookie(self) -> str:
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure, host-only and Path=/.
        return "__Host-suveryn_session" if self.secure_cookies else "suveryn_session"


@dataclass(frozen=True)
class User:
    """Who is signed in. ``sub`` is Keycloak's stable user id."""

    sub: str
    username: str
    name: str
    roles: tuple[str, ...] = ()


@dataclass
class Session:
    """A signed-in browser. Tokens never leave the gateway."""

    id: str
    user: User
    id_token: str
    access_token: str
    access_expires: float
    refresh_token: str | None
    refresh_expires: float | None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class PendingLogin:
    verifier: str
    nonce: str
    return_to: str
    created: float = field(default_factory=time.time)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """A PKCE code verifier and its S256 challenge (RFC 7636)."""
    verifier = _b64url(secrets.token_bytes(32))
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def safe_return_path(path: str | None) -> str:
    """Only a path on this site ("/..."), never another host ("//evil", "https://...", "/\\evil")."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


class OIDCProvider:
    """Talks to Keycloak: discovery, keys, code exchange, refresh, token validation."""

    def __init__(self, settings: AuthSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport)
        self._meta: dict | None = None
        self._keys: dict[str, PyJWK] = {}
        self._keys_read = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def metadata(self) -> dict:
        """Keycloak's OpenID configuration (read once; retried on the next call if it failed)."""
        if self._meta is None:
            url = f"{self.settings.issuer}/.well-known/openid-configuration"
            try:
                r = await self._http.get(url)
                r.raise_for_status()
                meta = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise AuthUnavailable(f"sign-in service unreachable: {type(e).__name__}") from e
            if meta.get("issuer") != self.settings.issuer:
                raise AuthUnavailable("the sign-in service reports a different issuer than configured")
            self._meta = meta
        return self._meta

    async def _key(self, kid: str | None) -> PyJWK:
        async with self._lock:
            if kid not in self._keys and time.time() - self._keys_read > JWKS_MIN_REFRESH_S:
                meta = await self.metadata()
                try:
                    r = await self._http.get(meta["jwks_uri"])
                    r.raise_for_status()
                    keys = r.json()["keys"]
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    raise AuthUnavailable(f"sign-in keys unreachable: {type(e).__name__}") from e
                self._keys = {}
                for k in keys:
                    if k.get("use", "sig") == "sig" and k.get("alg", "RS256") in self.settings.algorithms:
                        try:
                            self._keys[k.get("kid")] = PyJWK(k)
                        except jwt.PyJWKError:
                            continue  # a key type we don't use
                self._keys_read = time.time()
            if kid not in self._keys:
                raise AuthError("token signed with an unknown key")
            return self._keys[kid]

    async def verify(self, token: str, *, kind: str, nonce: str | None = None) -> dict:
        """Validate an ``"id"`` or ``"access"`` token and return its claims. Raises ``AuthError``."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise AuthError("malformed token") from e
        if header.get("alg") not in self.settings.algorithms:
            raise AuthError("token algorithm not allowed")
        key = await self._key(header.get("kid"))
        options = {"require": ["exp", "iat", "iss", "sub"], "verify_aud": kind == "id"}
        try:
            claims = jwt.decode(token, key=key, algorithms=list(self.settings.algorithms), issuer=self.settings.issuer,
                                audience=self.settings.client_id if kind == "id" else None,
                                options=options, leeway=CLOCK_LEEWAY_S)
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid token: {type(e).__name__}") from e
        if kind == "id" and claims.get("nonce") != nonce:
            raise AuthError("invalid token: nonce mismatch")
        if kind == "access":
            aud = claims.get("aud")
            auds = aud if isinstance(aud, list) else [aud] if aud else []
            if claims.get("azp") != self.settings.client_id and self.settings.client_id not in auds:
                raise AuthError("invalid token: issued for another client")
            if claims.get("typ", "Bearer") != "Bearer":
                raise AuthError("invalid token: not an access token")
        return claims

    async def authorize_url(self, state: str, nonce: str, challenge: str) -> str:
        meta = await self.metadata()
        query = urlencode({"response_type": "code", "client_id": self.settings.client_id,
                           "redirect_uri": self.settings.redirect_uri, "scope": "openid profile",
                           "state": state, "nonce": nonce, "code_challenge": challenge,
                           "code_challenge_method": "S256"})
        return f"{meta['authorization_endpoint']}?{query}"

    async def _token_request(self, data: dict) -> dict:
        meta = await self.metadata()
        try:
            r = await self._http.post(meta["token_endpoint"], data=data,
                                      auth=(self.settings.client_id, self.settings.client_secret))
        except httpx.HTTPError as e:
            raise AuthUnavailable(f"sign-in service unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            raise AuthError(f"the sign-in service refused the request (HTTP {r.status_code})")
        try:
            return r.json()
        except ValueError as e:
            raise AuthError("the sign-in service sent an unexpected answer") from e

    async def exchange_code(self, code: str, verifier: str) -> dict:
        return await self._token_request({"grant_type": "authorization_code", "code": code,
                                          "redirect_uri": self.settings.redirect_uri, "code_verifier": verifier})

    async def refresh(self, refresh_token: str) -> dict:
        return await self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def end_session_url(self, id_token: str | None) -> str | None:
        meta = await self.metadata()
        endpoint = meta.get("end_session_endpoint")
        if not endpoint:
            return None
        params = {"client_id": self.settings.client_id, "post_logout_redirect_uri": f"{self.settings.public_url}/"}
        if id_token:
            params["id_token_hint"] = id_token
        return f"{endpoint}?{urlencode(params)}"


def user_from_claims(claims: dict, roles_from: dict | None = None) -> User:
    """The signed-in user, from ID or access token claims (Keycloak's standard claim names).

    Realm roles are read from ``roles_from`` when given: Keycloak puts ``realm_access`` in the
    access token only, not in the ID token.
    """
    roles = tuple(sorted(((roles_from or claims).get("realm_access") or {}).get("roles") or []))
    username = claims.get("preferred_username") or claims["sub"]
    return User(sub=claims["sub"], username=username, name=claims.get("name") or username, roles=roles)


class Authenticator:
    """Sessions and sign-in for the gateway. ``disabled()`` gives a no-op one for development and tests."""

    def __init__(self, settings: AuthSettings, provider: OIDCProvider | None = None):
        self.settings = settings
        self.provider = provider or (OIDCProvider(settings) if settings.configured else None)
        self._sessions: dict[str, Session] = {}
        self._pending: dict[str, PendingLogin] = {}

    @classmethod
    def disabled(cls) -> "Authenticator":
        return cls(AuthSettings(disabled=True))

    @property
    def enabled(self) -> bool:
        return not self.settings.disabled

    async def status(self) -> tuple[str, str | None]:
        """("ready" | "unavailable" | "not_configured" | "disabled", detail) for /health."""
        if not self.enabled:
            return "disabled", "sign-in is turned off (SUVERYN_AUTH=off, development only)"
        if self.provider is None:
            return "not_configured", "set SUVERYN_OIDC_ISSUER, SUVERYN_OIDC_CLIENT_SECRET and SUVERYN_PUBLIC_URL"
        try:
            await self.provider.metadata()
        except AuthUnavailable as e:
            return "unavailable", str(e)
        return "ready", None

    def _require_provider(self) -> OIDCProvider:
        if self.provider is None:
            raise AuthUnavailable("sign-in is not configured on this server")
        return self.provider

    # ------------------------------------------------------------------ login flow
    async def start_login(self, return_to: str | None) -> tuple[str, str]:
        """(Keycloak URL to redirect to, state to set in the login cookie)."""
        provider = self._require_provider()
        now = time.time()
        for s in [s for s, p in self._pending.items() if now - p.created > LOGIN_TTL_S]:
            del self._pending[s]
        if len(self._pending) >= MAX_PENDING_LOGINS:
            raise AuthUnavailable("too many sign-ins in progress; try again in a few minutes")
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        self._pending[state] = PendingLogin(verifier, nonce, safe_return_path(return_to))
        return await provider.authorize_url(state, nonce, challenge), state

    async def finish_login(self, code: str, state: str, cookie_state: str | None) -> tuple[Session, str]:
        """Complete a login: (new session, path to return to). Raises ``AuthError``."""
        provider = self._require_provider()
        pending = self._pending.pop(state, None)
        if pending is None or time.time() - pending.created > LOGIN_TTL_S:
            raise AuthError("this sign-in has expired or was already used; please sign in again")
        if not cookie_state or not secrets.compare_digest(cookie_state, state):
            raise AuthError("this sign-in was started in another browser; please sign in again")
        tokens = await provider.exchange_code(code, pending.verifier)
        claims = await provider.verify(tokens.get("id_token", ""), kind="id", nonce=pending.nonce)
        access = await provider.verify(tokens.get("access_token", ""), kind="access")
        session = self._new_session(user_from_claims(claims, roles_from=access), tokens)
        return session, pending.return_to

    def _new_session(self, user: User, tokens: dict) -> Session:
        now = time.time()
        if len(self._sessions) >= MAX_SESSIONS:
            self._prune()
        session = Session(id=secrets.token_urlsafe(32), user=user, id_token=tokens.get("id_token", ""),
                          access_token=tokens["access_token"], access_expires=now + int(tokens.get("expires_in", 60)),
                          refresh_token=tokens.get("refresh_token"),
                          refresh_expires=now + int(tokens["refresh_expires_in"]) if tokens.get("refresh_expires_in") else None)
        self._sessions[session.id] = session
        return session

    def _prune(self) -> None:
        now = time.time()
        for sid in [sid for sid, s in self._sessions.items()
                    if (s.refresh_expires or s.access_expires) < now]:
            del self._sessions[sid]

    # ------------------------------------------------------------------ requests
    async def session_user(self, session_id: str | None) -> User | None:
        """The user of a valid session, refreshing its tokens when needed; None if signed out."""
        session = self._sessions.get(session_id or "")
        if session is None:
            return None
        if time.time() < session.access_expires - REFRESH_MARGIN_S:
            return session.user
        async with session.lock:
            if time.time() < session.access_expires - REFRESH_MARGIN_S:
                return session.user  # refreshed by a concurrent request
            if not session.refresh_token or (session.refresh_expires and time.time() > session.refresh_expires):
                self.drop(session.id)
                return None
            try:
                tokens = await self._require_provider().refresh(session.refresh_token)
                claims = await self._require_provider().verify(tokens.get("access_token", ""), kind="access")
            except AuthError:
                self.drop(session.id)  # Keycloak ended the session, disabled the user, ...
                return None
            if claims["sub"] != session.user.sub:
                self.drop(session.id)
                return None
            now = time.time()
            session.access_token = tokens["access_token"]
            session.access_expires = now + int(tokens.get("expires_in", 60))
            session.refresh_token = tokens.get("refresh_token", session.refresh_token)
            if tokens.get("refresh_expires_in"):
                session.refresh_expires = now + int(tokens["refresh_expires_in"])
            session.id_token = tokens.get("id_token", session.id_token)
            # Roles can change in Keycloak (an administrator granted or revoked): take them from each new token.
            session.user = replace(session.user, roles=user_from_claims(claims).roles)
            return session.user

    async def bearer_user(self, token: str) -> User:
        """The user of a bearer access token (non-browser clients). Raises ``AuthError``."""
        claims = await self._require_provider().verify(token, kind="access")
        return user_from_claims(claims)

    def drop(self, session_id: str | None) -> Session | None:
        return self._sessions.pop(session_id or "", None)

    async def logout(self, session_id: str | None) -> str | None:
        """End the session here; return Keycloak's end-session URL (ends the Keycloak session too)."""
        session = self.drop(session_id)
        if self.provider is None:
            return None
        try:
            return await self.provider.end_session_url(session.id_token if session else None)
        except AuthUnavailable:
            return None

    async def aclose(self) -> None:
        if self.provider is not None:
            await self.provider.aclose()
