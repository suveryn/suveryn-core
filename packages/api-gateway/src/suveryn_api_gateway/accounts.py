"""The office's accounts, managed from Administration › Users (docs/design/admin.md, artboards 32 and 34).

Nobody needs Keycloak's own console: the gateway manages the accounts through Keycloak's admin REST API **as
the administrator who is signed in**, with their own access token, never from the browser. The realm role
``suveryn-admin`` is a composite of realm-management's ``manage-users``, ``view-users``, ``view-realm`` and
``view-events`` (``keycloak/suveryn-realm.json``), so an administrator's token carries what these calls need
and nobody else's does. No extra client and no secret: when no administrator is signed in, nothing here can
be done, and Keycloak's admin events name the administrator who made each change (Filip, 28 October).

The appliance sends no e-mail (no mail server, maybe air-gapped), so adding someone, or having their password
set again, gives a **temporary password** to pass on, shown once and kept nowhere. At its first use the
person chooses their own password and sets up two-step sign-in (Keycloak's required actions). Keycloak is the
password manager: the gateway keeps no dates, passwords or log beside it. One never used shows as "never
signed in" on the list, where the administrator can set it again or switch the account off.
"""

import asyncio
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel

log = logging.getLogger("suveryn.gateway")
ADMIN_ROLE = "suveryn-admin"
MAX_USERS = 1000
MAX_EVENTS = 200
EVENTS_KEPT_DAYS = 180  # the realm's eventsExpiration (development and production): older sign-ins are gone
PAIRED_S = 2  # what one change does in several calls, one right after the other, shows as one line
# A temporary password the policy accepts (15 characters or more) and a person can read out: four groups
# of letters and digits without look-alikes (no l, 1, o, 0).
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


class AccountsUnavailable(Exception):
    """Keycloak can't be reached, refuses the administrator's token, or the issuer isn't configured."""


class RightsRefused(AccountsUnavailable):
    """Keycloak refused the administrator's token for its admin API: the ``suveryn-admin`` role lacks its
    composites (a realm imported before them; the provisioning adds them again)."""


class AccountRefused(Exception):
    """Keycloak refused the change for a reason the administrator can act on (``code``)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AccountsSettings:
    issuer: str = ""

    @classmethod
    def from_env(cls) -> "AccountsSettings":
        return cls(issuer=os.environ.get("SUVERYN_OIDC_ISSUER", "").rstrip("/"))

    @property
    def configured(self) -> bool:
        return "/realms/" in self.issuer

    @property
    def admin_url(self) -> str:
        base, _, realm = self.issuer.rpartition("/realms/")
        return f"{base}/admin/realms/{realm}"


class Account(BaseModel):
    sub: str
    username: str
    name: str
    email: str = ""
    admin: bool = False
    enabled: bool = True
    last_sign_in: datetime | None = None
    # No sign-in found, but the account is older than the sign-in events Keycloak keeps: "not in the last
    # 180 days", not "never" (external review, pass 7).
    last_sign_in_unknown: bool = False


EventKind = Literal["signed_in", "sign_in_failed", "signed_out", "added", "made_admin", "admin_removed",
                    "password_reset", "two_step_reset", "signed_out_everywhere", "changed", "deleted"]


class AccountEvent(BaseModel):
    """One line of *Sign-ins and changes*: who, what, when, and by whom for a change. Never a password or text."""

    at: datetime
    kind: EventKind
    user: str | None = None  # the account's id, when known
    name: str  # the account's name; for a failed sign-in with an unknown name: ""
    by: str | None = None  # the administrator who made a change
    reason: Literal["wrong_password", "locked", "switched_off", "other"] | None = None  # a failed sign-in


def temporary_password() -> str:
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4))


def split_name(name: str) -> tuple[str, str]:
    first, _, last = " ".join(name.split()).partition(" ")
    return first, last


class Accounts:
    """Keycloak's accounts for this realm. Every call takes the signed-in administrator's access token."""

    def __init__(self, settings: AccountsSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=15.0, transport=transport)

    @property
    def configured(self) -> bool:
        return self.settings.configured

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, token: str, method: str, path: str, *, params: dict | None = None, json=None) -> httpx.Response:
        if not self.configured:
            raise AccountsUnavailable("account management isn't configured on this server")
        try:
            r = await self._http.request(method, self.settings.admin_url + path, params=params, json=json,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise AccountsUnavailable(f"the sign-in service can't be reached ({type(e).__name__})") from e
        if r.status_code == 404:
            raise AccountRefused("not_found")
        if r.status_code in (401, 403):
            raise RightsRefused(f"the sign-in service refused the administrator's rights (HTTP {r.status_code})")
        if r.status_code >= 400 and r.status_code != 409:
            raise AccountsUnavailable(f"the sign-in service refused {method} {path.split('/')[1]} (HTTP {r.status_code})")
        return r

    async def _admins(self, token: str) -> set[str]:
        return {u["id"] for u in (await self._call(token, "GET", f"/roles/{ADMIN_ROLE}/users",
                                                   params={"max": str(MAX_USERS), "briefRepresentation": "true"})).json()}

    # ------------------------------------------------------------------ reading
    async def everyone(self, token: str) -> list[Account]:
        """Every person's account (no service accounts), with administrator, on or off, and last sign-in."""
        users = (await self._call(token, "GET", "/users", params={"max": str(MAX_USERS), "briefRepresentation": "false"})).json()
        admins = await self._admins(token)
        people = [u for u in users if not u.get("serviceAccountClientId")]
        last: dict[str, datetime] = {}
        for e in (await self._call(token, "GET", "/events", params={"type": "LOGIN", "max": "2000"})).json():
            uid = e.get("userId")
            if uid and uid not in last:  # newest first
                last[uid] = _time(e)
        # The newest 2,000 sign-ins can miss someone who signed in less often (external review, pass 7): each
        # of them is asked for on their own, newest first, one event.
        missing = [u["id"] for u in people if u["id"] not in last]
        answers = await asyncio.gather(*(self._call(token, "GET", "/events", params={"type": "LOGIN", "user": uid, "max": "1"})
                                         for uid in missing))
        for uid, r in zip(missing, answers):
            if (found := r.json()):
                last[uid] = _time(found[0])
        kept_since = datetime.now(UTC) - timedelta(days=EVENTS_KEPT_DAYS)
        out = []
        for u in people:
            created = datetime.fromtimestamp(u["createdTimestamp"] / 1000, UTC) if u.get("createdTimestamp") else None
            out.append(_account(u, u["id"] in admins, last.get(u["id"]),
                                unknown=u["id"] not in last and (created is None or created < kept_since)))
        return sorted(out, key=lambda a: a.name.lower())

    async def get(self, token: str, sub: str) -> Account:
        _check_id(sub)
        u = (await self._call(token, "GET", f"/users/{sub}")).json()
        return _account(u, sub in await self._admins(token), None)

    async def events(self, token: str, known: dict[str, str], limit: int = MAX_EVENTS) -> list[AccountEvent]:
        """*Sign-ins and changes*, newest first: Keycloak's sign-in events and its admin events on accounts.

        A failed sign-in names the account only when it is one of ``known`` (id to name): what someone typed
        into the name field is never shown. A change names the administrator who made it. Admin events carry
        no details on the appliance (``adminEventsDetailsEnabled`` off), so an update that is not one of the
        actions here (switched off or on, say) reads as "changed"."""
        sign_ins = (await self._call(token, "GET", "/events",
                                     params={"type": ["LOGIN", "LOGIN_ERROR", "LOGOUT"], "max": str(limit)})).json()
        changes = (await self._call(token, "GET", "/admin-events", params={
            "resourceTypes": ["USER", "REALM_ROLE_MAPPING"], "max": str(limit)})).json()
        out = []
        for e in sign_ins:
            uid = e.get("userId")
            if e.get("type") == "LOGIN_ERROR":
                error = e.get("error", "")
                reason = ("wrong_password" if error == "invalid_user_credentials" else "locked" if error == "user_temporarily_disabled"
                          else "switched_off" if error == "user_disabled" else "other")
                out.append(AccountEvent(at=_time(e), kind="sign_in_failed", user=uid if uid in known else None,
                                        name=known.get(uid or "", ""), reason=reason))
            elif uid in known:
                out.append(AccountEvent(at=_time(e), kind="signed_in" if e.get("type") == "LOGIN" else "signed_out",
                                        user=uid, name=known[uid]))
        out += _changes(changes, known)
        return sorted(out, key=lambda e: e.at, reverse=True)[:limit]

    # ------------------------------------------------------------------ changing
    async def add(self, token: str, name: str, email: str, admin: bool) -> tuple[Account, str]:
        """A new account that signs in with its e-mail address, with a temporary password; at first sign-in the
        person chooses a password and sets up two-step sign-in."""
        first, last = split_name(name)
        r = await self._call(token, "POST", "/users", json={
            "username": email.lower(), "email": email.lower(), "firstName": first, "lastName": last, "enabled": True,
            "emailVerified": True, "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]})
        if r.status_code == 409:
            raise AccountRefused("exists")
        sub = r.headers.get("location", "").rstrip("/").rsplit("/", 1)[-1]
        password = await self.reset_password(token, sub)
        if admin:
            await self.set_admin(token, sub, True)
        return Account(sub=sub, username=email.lower(), name=" ".join(name.split()), email=email.lower(), admin=admin), password

    async def reset_password(self, token: str, sub: str) -> str:
        """A new temporary password: the current one stops working; the person chooses theirs at the next sign-in."""
        _check_id(sub)
        password = temporary_password()
        await self._call(token, "PUT", f"/users/{sub}/reset-password", json={"type": "password", "value": password, "temporary": True})
        return password

    async def set_admin(self, token: str, sub: str, on: bool) -> None:
        _check_id(sub)
        role = (await self._call(token, "GET", f"/roles/{ADMIN_ROLE}")).json()
        await self._call(token, "POST" if on else "DELETE", f"/users/{sub}/role-mappings/realm", json=[role])

    async def reset_two_step(self, token: str, sub: str) -> None:
        """Remove the authenticator app; the person sets it up again at the next sign-in."""
        _check_id(sub)
        for c in (await self._call(token, "GET", f"/users/{sub}/credentials")).json():
            if c.get("type") == "otp":
                await self._call(token, "DELETE", f"/users/{sub}/credentials/{c['id']}")
        u = (await self._call(token, "GET", f"/users/{sub}")).json()
        actions = u.get("requiredActions", [])
        if "CONFIGURE_TOTP" not in actions:
            await self._call(token, "PUT", f"/users/{sub}", json={"requiredActions": [*actions, "CONFIGURE_TOTP"]})

    async def sign_out(self, token: str, sub: str) -> None:
        _check_id(sub)
        await self._call(token, "POST", f"/users/{sub}/logout")

    async def delete(self, token: str, sub: str) -> None:
        """Delete the account in Keycloak (its credentials, sessions and role mappings with it)."""
        _check_id(sub)
        await self._call(token, "DELETE", f"/users/{sub}")

    async def set_enabled(self, token: str, sub: str, on: bool) -> None:
        _check_id(sub)
        await self._call(token, "PUT", f"/users/{sub}", json={"enabled": on})
        if not on:
            await self._call(token, "POST", f"/users/{sub}/logout")  # switched off signs out everywhere too


def _time(e: dict) -> datetime:
    return datetime.fromtimestamp(e["time"] / 1000, UTC)


def _change_kind(e: dict) -> tuple[str, str] | None:
    """(account id, kind) of one Keycloak admin event, or None for one that isn't about an account here."""
    parts = (e.get("resourcePath") or "").split("/")
    if len(parts) < 2 or parts[0] != "users":
        return None
    sub, rest, op = parts[1], parts[2:], e.get("operationType")
    if e.get("resourceType") == "REALM_ROLE_MAPPING" and rest == ["role-mappings", "realm"]:
        # the gateway maps no other realm role; Keycloak's default roles at creation make no admin event
        return (sub, "made_admin" if op == "CREATE" else "admin_removed") if op in ("CREATE", "DELETE") else None
    if rest == [] and op == "CREATE":
        return sub, "added"
    if rest == [] and op == "UPDATE":
        return sub, "changed"
    if rest == [] and op == "DELETE":
        return sub, "deleted"
    if rest == ["reset-password"]:
        return sub, "password_reset"
    if rest == ["logout"]:
        return sub, "signed_out_everywhere"
    if len(rest) == 2 and rest[0] == "credentials" and op == "DELETE":
        return sub, "two_step_reset"
    return None


def _changes(events: list[dict], known: dict[str, str]) -> list[AccountEvent]:
    """Keycloak's admin events (newest first) as lines, one per change: the temporary password that comes with
    a new account, the required action that comes with a two-step reset and the sign-out that comes with
    switching off are part of the same change."""
    lines = [(sub, kind, _time(e), e) for e in events if (k := _change_kind(e)) for sub, kind in [k]]

    def near(line, kind: str, among) -> bool:  # just after a line of this kind, on the same account
        return any(o is not line and o[0] == line[0] and o[1] == kind and 0 <= (line[2] - o[2]).total_seconds() <= PAIRED_S
                   for o in among)

    lines = [x for x in lines if not (x[1] == "password_reset" and near(x, "added", lines))
             and not (x[1] == "changed" and near(x, "two_step_reset", lines))]
    lines = [x for x in lines if not (x[1] == "signed_out_everywhere" and near(x, "changed", lines))]
    return [AccountEvent(at=at, kind=kind, user=sub, name=known.get(sub, ""),
                         by=known.get((e.get("authDetails") or {}).get("userId") or ""))
            for sub, kind, at, e in lines]


def _check_id(sub: str) -> None:
    if not sub or len(sub) > 64 or not all(c.isalnum() or c == "-" for c in sub):
        raise AccountRefused("not_found")


def _account(u: dict, admin: bool, last: datetime | None, unknown: bool = False) -> Account:
    username = u.get("username") or u["id"]
    name = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p) or username
    return Account(sub=u["id"], username=username, name=name, email=u.get("email") or "", admin=admin,
                   enabled=u.get("enabled", True), last_sign_in=last, last_sign_in_unknown=unknown)
