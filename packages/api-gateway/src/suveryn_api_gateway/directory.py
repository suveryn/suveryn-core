"""The office's people, from Keycloak (suveryn-tracker#10, stage 2): who can be added to a case.

A manager adding a colleague to a case picks them from the office's accounts, so a colleague
who has never opened sūveryn can be added too. The list comes from Keycloak's admin API, read
with a client of its own, ``suveryn-directory``: a confidential client with a service account
whose only right is ``view-users`` on this realm (the realm files: the gateway's development
realm, and suveryn-appliance's production realm). The chat client ``suveryn-chat`` keeps no
service account, as before.

What is read: user id (``sub``), username, display name, and whether the account is enabled;
nothing else, and nothing is written. Disabled accounts aren't offered. Results are cached for
``CACHE_S`` so a search as you type doesn't hit Keycloak on every keystroke.

Without the client's secret (``SUVERYN_DIRECTORY_CLIENT_SECRET``) the directory is unavailable
and the API answers 503; with sign-in off (development on one machine) it holds the local user.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

log = logging.getLogger("suveryn.gateway")
ADMIN_ROLE = "suveryn-admin"  # the realm role; routes/common.py names the same

CACHE_S = 30
MAX_RESULTS = 20


class DirectoryUnavailable(Exception):
    """Keycloak can't be reached, refuses the client, or the directory isn't configured."""


@dataclass(frozen=True)
class DirectorySettings:
    issuer: str = ""                          # the realm, as SUVERYN_OIDC_ISSUER
    client_id: str = "suveryn-directory"
    client_secret: str = ""

    @classmethod
    def from_env(cls) -> "DirectorySettings":
        return cls(issuer=os.environ.get("SUVERYN_OIDC_ISSUER", "").rstrip("/"),
                   client_id=os.environ.get("SUVERYN_DIRECTORY_CLIENT_ID", cls.client_id),
                   client_secret=os.environ.get("SUVERYN_DIRECTORY_CLIENT_SECRET", ""))

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.client_id and self.client_secret)

    @property
    def admin_url(self) -> str:
        """``.../realms/suveryn`` -> ``.../admin/realms/suveryn``."""
        base, _, realm = self.issuer.rpartition("/realms/")
        return f"{base}/admin/realms/{realm}"

    @property
    def token_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"


class Person(BaseModel):
    """One account, as the API lists it."""

    sub: str
    username: str
    name: str
    admin: bool = False  # holds the realm role suveryn-admin (the avatar's badge); filled in by ``admins()``
    avatar: str | None = None  # the ETag of their picture, None without one (routes/common.py ``with_faces``)


class Directory:
    """Keycloak's users for this realm, through the ``suveryn-directory`` service account."""

    def __init__(self, settings: DirectorySettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport)
        self._token: tuple[str, float] = ("", 0.0)
        self._cache: dict[str, tuple[float, list[Person]]] = {}
        self._admins: tuple[float, set[str]] | None = None
        self._admins_warned = False
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self.settings.configured

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _access_token(self) -> str:
        token, until = self._token
        if token and time.monotonic() < until:
            return token
        try:
            r = await self._http.post(self.settings.token_url, data={"grant_type": "client_credentials"},
                                      auth=(self.settings.client_id, self.settings.client_secret))
        except httpx.HTTPError as e:
            raise DirectoryUnavailable(f"the sign-in service can't be reached ({type(e).__name__})") from e
        if r.status_code != 200:
            raise DirectoryUnavailable(f"the sign-in service refused the directory client (HTTP {r.status_code})")
        body = r.json()
        self._token = (body["access_token"], time.monotonic() + max(30, int(body.get("expires_in", 60)) - 30))
        return self._token[0]

    async def search(self, query: str = "", limit: int = MAX_RESULTS) -> list[Person]:
        """Enabled accounts whose username, name or email contains ``query`` (Keycloak's own search)."""
        if not self.configured:
            raise DirectoryUnavailable("the directory isn't configured on this server")
        key = query.strip().lower()
        async with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_S:
                return hit[1][:limit]
            people = await self._fetch(key, limit)
            if len(self._cache) > 200:
                self._cache.clear()
            self._cache[key] = (time.monotonic(), people)
            return people

    async def get(self, sub: str) -> Person | None:
        """One enabled account by its id, or None."""
        if not self.configured:
            raise DirectoryUnavailable("the directory isn't configured on this server")
        if not sub or "/" in sub or len(sub) > 200:
            return None
        r = await self._admin_get(f"/users/{sub}")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise DirectoryUnavailable(f"the sign-in service refused the user lookup (HTTP {r.status_code})")
        return _person(r.json())

    async def admins(self) -> set[str]:
        """The ids of the accounts holding the realm role ``suveryn-admin``, for the badge on their
        avatar; cached ``CACHE_S``. Keycloak answers this through ``/roles/{role}/users``, which needs
        the ``view-realm`` right as well as ``view-users``; without it the answer is empty (logged
        once, never an error: a missing badge is cosmetic)."""
        if not self.configured:
            return set()
        async with self._lock:
            if self._admins is not None and time.monotonic() - self._admins[0] < CACHE_S:
                return self._admins[1]
            found: set[str] = set()
            try:
                r = await self._admin_get(f"/roles/{ADMIN_ROLE}/users", {"max": "200", "briefRepresentation": "true"})
                if r.status_code == 200:
                    found = {u["id"] for u in r.json() if u.get("id")}
                elif not self._admins_warned:
                    log.warning("the directory client can't list administrators (HTTP %d): no badge on their avatars", r.status_code)
                    self._admins_warned = True
            except (httpx.HTTPError, DirectoryUnavailable) as e:
                log.info("administrators not listed: %s", type(e).__name__)
            self._admins = (time.monotonic(), found)
            return found

    async def _admin_get(self, path: str, params: dict | None = None) -> httpx.Response:
        token = await self._access_token()
        try:
            r = await self._http.get(self.settings.admin_url + path, params=params,
                                     headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401:  # the token expired early: once more with a fresh one
                self._token = ("", 0.0)
                token = await self._access_token()
                r = await self._http.get(self.settings.admin_url + path, params=params,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise DirectoryUnavailable(f"the sign-in service can't be reached ({type(e).__name__})") from e
        return r

    async def _fetch(self, query: str, limit: int) -> list[Person]:
        params = {"max": str(limit), "briefRepresentation": "true", "enabled": "true"}
        if query:
            params["search"] = query
        r = await self._admin_get("/users", params)
        if r.status_code != 200:
            raise DirectoryUnavailable(f"the sign-in service refused the user list (HTTP {r.status_code})")
        people = [p for p in (_person(u) for u in r.json()) if p is not None]
        people.sort(key=lambda p: p.name.lower())
        return people


def _person(u: dict) -> Person | None:
    """Keycloak's user representation as a Person; None for a disabled account or a service account."""
    if u.get("enabled") is False or u.get("serviceAccountClientId"):
        return None
    username = u.get("username") or u["id"]
    name = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p) or username
    return Person(sub=u["id"], username=username, name=name)


class LocalDirectory:
    """With sign-in off: the one local user, so the screens work in development."""

    configured = True

    def __init__(self, sub: str, name: str = "Development (sign-in off)"):
        self._people = [Person(sub=sub, username="dev", name=name)]

    async def search(self, query: str = "", limit: int = MAX_RESULTS) -> list[Person]:
        q = query.strip().lower()
        return [p for p in self._people if not q or q in p.name.lower() or q in p.username.lower()][:limit]

    async def get(self, sub: str) -> Person | None:
        return next((p for p in self._people if p.sub == sub), None)

    async def admins(self) -> set[str]:
        return {p.sub for p in self._people}  # with sign-in off, the one local user administers

    async def aclose(self) -> None:
        pass
