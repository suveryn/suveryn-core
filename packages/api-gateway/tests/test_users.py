"""Administration › Users (docs/design/admin.md, artboards 32 and 34): the office's accounts through Keycloak's
admin API, with the rules the gateway holds: always one administrator, not your own account, cases first.

A fake of the few admin endpoints the gateway calls stands in for Keycloak, writing admin events as Keycloak
does; the same calls were made against Keycloak 26.8 with the development realm while building, as an
administrator (the composite role reaching the chat client's token, the temporary password with its required
actions, the sign-in events, the admin events naming the administrator).
"""

import json
import re
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
import jwt
from suveryn_api_gateway.accounts import Accounts, AccountsSettings, temporary_password
from suveryn_api_gateway.app import ADMIN_ROLE, create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_harness import LlamaServerClient, LLMSettings
from test_auth import PUBLIC, SETTINGS, FakeKeycloak, sign_in
from test_documents import llm_transport

ISSUER = "http://kc.test/realms/suveryn"
ADMIN = "http://kc.test/admin/realms/suveryn"


class FakeAdminApi:
    """Keycloak's admin endpoints as accounts.py calls them, on a few users kept in memory."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.admins: set[str] = set()
        self.passwords: dict[str, tuple[str, bool]] = {}
        self.credentials: dict[str, list[dict]] = {}
        self.logged_out: list[str] = []
        self.events: list[dict] = []
        self.admin_events: list[dict] = []  # newest first, as Keycloak answers
        self.callers: list[str] = []  # whose token each call carried

    def person(self, sub: str, name: str, email: str, admin: bool = False, enabled: bool = True) -> None:
        first, _, last = name.partition(" ")
        self.users[sub] = {"id": sub, "username": email, "email": email, "firstName": first, "lastName": last,
                           "enabled": enabled, "requiredActions": []}
        if admin:
            self.admins.add(sub)

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        caller = jwt.decode(token, options={"verify_signature": False})
        if ADMIN_ROLE not in caller.get("realm_access", {}).get("roles", []) or getattr(self, "no_composites", False):
            return httpx.Response(403, json={"error": "unknown_error"})  # the composite role isn't there
        self.callers.append(caller["sub"])
        path = request.url.path.removeprefix("/admin/realms/suveryn")
        body = json.loads(request.content) if request.content else None
        self._params = request.url.params
        response = self._answer(path, method, body)
        if method != "GET" and response.status_code < 300:
            self._admin_event(path, method, caller["sub"], response)
        return response

    def _admin_event(self, path: str, method: str, by: str, response: httpx.Response) -> None:
        if path == "/users":
            path = "/users/" + response.headers["location"].rsplit("/", 1)[1]
        kind = "REALM_ROLE_MAPPING" if path.endswith("/role-mappings/realm") else "USER"
        op = {"POST": "ACTION" if path.endswith("/logout") else "CREATE", "PUT": "UPDATE", "DELETE": "DELETE"}[method]
        if path.endswith("/reset-password"):
            op = "ACTION"
        if path.count("/") == 2 and method == "POST":
            op = "CREATE"
        self.admin_events.insert(0, {"time": int(time.time() * 1000), "operationType": op, "resourceType": kind,
                                     "resourcePath": path.lstrip("/"), "authDetails": {"userId": by, "ipAddress": "10.0.0.9"}})

    def _answer(self, path: str, method: str, body) -> httpx.Response:
        if path == "/users" and method == "GET":
            return httpx.Response(200, json=list(self.users.values()))
        if path == "/users" and method == "POST":
            if any(u["email"] == body["email"] for u in self.users.values()):
                return httpx.Response(409, json={"errorMessage": "User exists with same email"})
            sub = str(uuid.uuid4())
            self.users[sub] = {**body, "id": sub}
            return httpx.Response(201, headers={"location": f"{ADMIN}/users/{sub}"})
        if path == f"/roles/{ADMIN_ROLE}/users":
            return httpx.Response(200, json=[{"id": s} for s in self.admins])
        if path == f"/roles/{ADMIN_ROLE}":
            return httpx.Response(200, json={"id": "role-1", "name": ADMIN_ROLE})
        if path == "/events":  # newest first; by type, by user and at most max, as Keycloak answers
            types, user = self._params.get_list("type"), self._params.get("user")
            found = [e for e in self.events if (not types or e.get("type") in types) and (not user or e.get("userId") == user)]
            return httpx.Response(200, json=found[:int(self._params.get("max", "100"))])
        if path == "/admin-events":
            return httpx.Response(200, json=self.admin_events)
        m = re.fullmatch(r"/users/([\w-]+)(/.*)?", path)
        if not m or m.group(1) not in self.users:
            return httpx.Response(404)
        sub, rest = m.group(1), m.group(2) or ""
        user = self.users[sub]
        if rest == "" and method == "GET":
            return httpx.Response(200, json=user)
        if rest == "" and method == "PUT":
            user.update(body)
            return httpx.Response(204)
        if rest == "/reset-password":
            self.passwords[sub] = (body["value"], body["temporary"])
            if body["temporary"] and "UPDATE_PASSWORD" not in user["requiredActions"]:
                user["requiredActions"].append("UPDATE_PASSWORD")
            return httpx.Response(204)
        if rest == "/role-mappings/realm":
            (self.admins.add if method == "POST" else self.admins.discard)(sub)
            return httpx.Response(204)
        if rest == "/credentials":
            return httpx.Response(200, json=self.credentials.get(sub, []))
        if rest.startswith("/credentials/") and method == "DELETE":
            self.credentials[sub] = [c for c in self.credentials.get(sub, []) if c["id"] != rest.rsplit("/", 1)[1]]
            return httpx.Response(204)
        if rest == "" and method == "DELETE":
            del self.users[sub]
            self.admins.discard(sub)
            return httpx.Response(204)
        if rest == "/logout":
            self.logged_out.append(sub)
            return httpx.Response(204)
        return httpx.Response(405)


class FakeCases:
    """Only what Users asks the case store: how many cases an account manages."""

    def __init__(self):
        self.managed: dict[str, int] = {}

    def manages(self, user):
        return self.managed.get(user, 0)

    departed: dict

    def depart(self, sub, username, name, by):
        self.__dict__.setdefault("departed", {})[sub] = name
        return 0

    def departed_names(self, subs=None):
        return dict(self.__dict__.get("departed", {}))

    # what the gateway's hourly sweep asks
    def purge_events(self):
        return 0

    def due_for_deletion(self):
        return []

    def overrides(self):
        return {}


ALICE, BOB, CAROL = "user-a", "user-b", "user-c"


@pytest.fixture
def setup():
    kc, api, cases = FakeKeycloak(), FakeAdminApi(), FakeCases()
    api.person(ALICE, "Alice Admin", "alice@office.test", admin=True)
    api.person(BOB, "Bob Peeters", "bob@office.test")
    api.person(CAROL, "Carol Claes", "carol@office.test")
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    accounts = Accounts(AccountsSettings(issuer=ISSUER), transport=httpx.MockTransport(api.handler))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=auth, accounts=accounts, cases=cases)) as c:
        yield c, kc, api, cases


def as_user(kc: FakeKeycloak, sub: str, admin: bool = False) -> dict:
    claims = {"sub": sub, "preferred_username": sub, "name": "Alice Admin" if sub == ALICE else sub,
              "realm_access": {"roles": [ADMIN_ROLE] if admin else []}}
    return {"Authorization": f"Bearer {kc.tokens(over=claims)['access_token']}"}


def test_the_list_is_for_administrators_with_last_sign_in(setup):
    c, kc, api, _ = setup
    api.events = [{"type": "LOGIN", "userId": BOB, "time": 1_793_000_000_000}, {"type": "LOGIN", "userId": BOB, "time": 1_792_000_000_000}]
    assert c.get("/v1/admin/users", headers=as_user(kc, BOB)).status_code == 403
    users = c.get("/v1/admin/users", headers=as_user(kc, ALICE, admin=True)).json()["users"]
    assert [(u["name"], u["admin"], u["enabled"]) for u in users] == [
        ("Alice Admin", True, True), ("Bob Peeters", False, True), ("Carol Claes", False, True)]
    assert users[1]["last_sign_in"].startswith("2026-10-26T07:33:20") and users[0]["last_sign_in"] is None  # the newest LOGIN


def test_adding_someone_gives_a_temporary_password_once_and_keeps_it_nowhere(setup):
    c, kc, api, _ = setup
    admin = as_user(kc, ALICE, admin=True)
    r = c.post("/v1/admin/users", json={"name": "Jonas  Claes", "email": "Jonas.C@office.test", "admin": True}, headers=admin)
    assert r.status_code == 201
    body = r.json()
    sub = body["user"]["sub"]
    assert body["user"]["name"] == "Jonas Claes" and body["user"]["username"] == "jonas.c@office.test"
    assert api.passwords[sub] == (body["password"], True)  # temporary: chosen again at first sign-in
    assert set(api.users[sub]["requiredActions"]) == {"UPDATE_PASSWORD", "CONFIGURE_TOTP"}
    assert sub in api.admins
    assert "valid_until" not in body  # Keycloak is the password manager: no expiry kept beside it (Filip, 28 October)
    assert set(api.callers) == {ALICE}  # every call as the administrator, with her own token
    events = c.get("/v1/admin/users/events", headers=admin).json()
    assert [(e["kind"], e["name"], e["by"]) for e in events] == [  # the temporary password is part of adding
        ("made_admin", "Jonas Claes", "Alice Admin"), ("added", "Jonas Claes", "Alice Admin")]
    assert body["password"] not in json.dumps(events + api.admin_events)  # never written down
    # the same e-mail address again
    assert c.post("/v1/admin/users", json={"name": "J", "email": "jonas.c@office.test"}, headers=admin).status_code == 409


def test_there_is_always_one_administrator(setup):
    c, kc, api, _ = setup
    admin = as_user(kc, ALICE, admin=True)
    assert c.put(f"/v1/admin/users/{ALICE}/admin", json={"admin": False}, headers=admin).status_code == 409
    assert c.put(f"/v1/admin/users/{BOB}/admin", json={"admin": True}, headers=admin).json()["admin"] is True
    assert c.put(f"/v1/admin/users/{ALICE}/admin", json={"admin": False}, headers=admin).status_code == 200  # Bob is one now
    assert api.admins == {BOB}
    assert c.put(f"/v1/admin/users/{BOB}/enabled", json={"enabled": False}, headers=admin).status_code == 409  # the last one


def test_switching_off_not_your_own_and_only_with_cases_handed_over(setup):
    c, kc, api, cases = setup
    admin = as_user(kc, ALICE, admin=True)
    assert c.put(f"/v1/admin/users/{ALICE}/enabled", json={"enabled": False}, headers=admin).status_code == 409
    cases.managed[BOB] = 2
    r = c.put(f"/v1/admin/users/{BOB}/enabled", json={"enabled": False}, headers=admin)
    assert r.status_code == 409 and "2 cases" in r.json()["detail"]
    cases.managed[BOB] = 0
    assert c.put(f"/v1/admin/users/{BOB}/enabled", json={"enabled": False}, headers=admin).json()["enabled"] is False
    assert api.users[BOB]["enabled"] is False and BOB in api.logged_out  # off signs out everywhere too
    assert c.put(f"/v1/admin/users/{BOB}/enabled", json={"enabled": True}, headers=admin).json()["enabled"] is True
    kinds = [e["kind"] for e in c.get("/v1/admin/users/events", headers=admin).json()]
    assert kinds == ["changed", "changed"]  # no details in Keycloak's admin events: off and on read as changed


def test_password_two_step_and_sign_out(setup):
    c, kc, api, _ = setup
    admin = as_user(kc, ALICE, admin=True)
    r = c.post(f"/v1/admin/users/{CAROL}/password", headers=admin).json()
    assert api.passwords[CAROL] == (r["password"], True) and r["address"]
    api.credentials[CAROL] = [{"id": "c1", "type": "password"}, {"id": "c2", "type": "otp"}]
    assert c.post(f"/v1/admin/users/{CAROL}/two-step", headers=admin).status_code == 204
    assert [x["type"] for x in api.credentials[CAROL]] == ["password"] and "CONFIGURE_TOTP" in api.users[CAROL]["requiredActions"]
    assert c.post(f"/v1/admin/users/{CAROL}/sign-out", headers=admin).status_code == 204 and api.logged_out == [CAROL]
    assert c.post("/v1/admin/users/no-such-user/sign-out", headers=admin).status_code == 404
    kinds = [e["kind"] for e in c.get("/v1/admin/users/events", headers=admin).json()]
    assert sorted(kinds) == ["password_reset", "signed_out_everywhere", "two_step_reset"]  # the required action is part of it


def test_sign_ins_and_changes_never_name_what_was_typed(setup):
    c, kc, api, _ = setup
    admin = as_user(kc, ALICE, admin=True)
    c.post(f"/v1/admin/users/{BOB}/sign-out", headers=admin)
    api.events = [
        {"type": "LOGIN_ERROR", "userId": BOB, "error": "invalid_user_credentials", "time": 1_793_000_300_000},
        {"type": "LOGIN_ERROR", "error": "user_not_found", "details": {"username": "MyPassword!23"}, "time": 1_793_000_200_000},
        {"type": "LOGIN", "userId": CAROL, "time": 1_793_000_100_000}]
    events = c.get("/v1/admin/users/events", headers=admin).json()
    kinds = [(e["kind"], e["name"], e["reason"], e["by"]) for e in events]
    assert ("sign_in_failed", "Bob Peeters", "wrong_password", None) in kinds
    assert ("sign_in_failed", "", "other", None) in kinds  # an unknown name typed in: not shown
    assert ("signed_in", "Carol Claes", None, None) in kinds
    assert ("signed_out_everywhere", "Bob Peeters", None, "Alice Admin") in kinds
    assert "MyPassword" not in json.dumps(events)


def test_temporary_passwords_are_readable_and_long_enough():
    for _ in range(50):
        p = temporary_password()
        assert len(p) == 19 and re.fullmatch(r"[a-km-z2-9]{4}(-[a-km-z2-9]{4}){3}", p) and not set("lo01") & set(p)


def test_nobody_else_can_and_a_browser_session_calls_with_a_fresh_token(setup):
    c, kc, api, _ = setup
    assert c.post(f"/v1/admin/users/{BOB}/sign-out", headers=as_user(kc, BOB)).status_code == 403
    assert api.callers == []  # refused by the gateway before Keycloak is asked
    admin_claims = {"sub": ALICE, "name": "Alice Admin", "realm_access": {"roles": [ADMIN_ROLE]}}
    kc.refresh_over = admin_claims
    sign_in(c, kc, **admin_claims)
    calls = len(kc.token_calls)
    assert c.post(f"/v1/admin/users/{BOB}/sign-out", headers={"Origin": PUBLIC}).status_code == 204
    assert kc.token_calls[calls:] and kc.token_calls[-1]["grant_type"] == "refresh_token"  # the gateway kept no token
    assert api.callers[-1] == ALICE and api.logged_out == [BOB]
    kc.refresh_allowed = False  # the administrator's session ended in Keycloak
    assert c.post(f"/v1/admin/users/{BOB}/sign-out", headers={"Origin": PUBLIC}).status_code == 401


def test_signing_out_everywhere_or_switching_off_ends_this_gateways_sessions_at_once(setup):
    """VM check of 28 October, finding 2: Keycloak ended the account's sessions, but the gateway's own session kept
    working until its access token ran out (about 4½ minutes)."""
    c, kc, api, _ = setup
    admin = as_user(kc, ALICE, admin=True)
    for action in (lambda: c.post(f"/v1/admin/users/{CAROL}/sign-out", headers=admin),
                   lambda: c.put(f"/v1/admin/users/{CAROL}/enabled", json={"enabled": False}, headers=admin)):
        carol = TestClient(c.app)  # Carol's own browser
        kc.refresh_over = {"sub": CAROL, "name": "Carol Claes"}
        sign_in(carol, kc, sub=CAROL, name="Carol Claes")
        assert carol.get("/v1/admin/users").status_code == 403  # signed in, not an administrator
        assert action().status_code in (200, 204)
        assert carol.get("/v1/admin/users").status_code == 401  # at once, not when her token runs out
        c.put(f"/v1/admin/users/{CAROL}/enabled", json={"enabled": True}, headers=admin)


def test_a_role_without_its_composites_says_the_rights_were_refused(setup):
    """VM check of 28 October, finding 11: a realm imported before Users answered "not available"."""
    c, kc, api, _ = setup
    api.no_composites = True
    r = c.get("/v1/admin/users", headers=as_user(kc, ALICE, admin=True))
    assert r.status_code == 503 and r.json()["reason"] == "rights"


def test_an_account_is_deleted_only_once_it_is_off_and_its_name_stays(setup):
    """Filip, 29 October: an administrator can delete an account, as a second step after switching it off."""
    c, kc, api, cases = setup
    admin = as_user(kc, ALICE, admin=True)
    assert c.delete(f"/v1/admin/users/{BOB}", headers=as_user(kc, CAROL)).status_code == 403
    r = c.delete(f"/v1/admin/users/{BOB}", headers=admin)
    assert r.status_code == 409 and "off first" in r.json()["detail"]
    assert c.get(f"/v1/admin/users/{BOB}/deletion", headers=admin).status_code == 409
    assert c.delete(f"/v1/admin/users/{ALICE}", headers=admin).status_code == 409  # not your own
    c.put(f"/v1/admin/users/{BOB}/enabled", json={"enabled": False}, headers=admin)
    assert c.get(f"/v1/admin/users/{BOB}/deletion", headers=admin).json() == {
        "documents": 0, "conversations": 0, "shared_conversations": 0}  # no stores on this test gateway
    assert c.delete(f"/v1/admin/users/{BOB}", headers=admin).status_code == 204
    assert BOB not in api.users and cases.departed == {BOB: "Bob Peeters"}
    events = c.get("/v1/admin/users/events", headers=admin).json()
    assert ("deleted", "Bob Peeters", "Alice Admin") in [(e["kind"], e["name"], e["by"]) for e in events]
    assert c.delete(f"/v1/admin/users/{BOB}", headers=admin).status_code == 404  # gone



def test_last_sign_in_is_found_beyond_the_newest_two_thousand(setup):
    """External review, pass 7: the last sign-in came from the newest 2,000 sign-ins, so someone who signed in
    less often read "never". Each account not among them is asked for on its own; one older than the 180 days
    of sign-ins Keycloak keeps, with none found, reads "not in the last 180 days", not "never"."""
    c, kc, api, cases = setup
    now = int(time.time() * 1000)
    day = 24 * 3600 * 1000
    api.events = [{"type": "LOGIN", "userId": CAROL, "time": now - i * 1000} for i in range(2000)]
    api.events.append({"type": "LOGIN", "userId": BOB, "time": now - 30 * day})  # the 2,001st
    api.users[ALICE]["createdTimestamp"] = now - 400 * day  # older than the events kept, no sign-in among them
    api.person("user-d", "Dirk Daems", "dirk@office.test")
    api.users["user-d"]["createdTimestamp"] = now - 2 * day  # new: really never
    users = {u["sub"]: u for u in c.get("/v1/admin/users", headers=as_user(kc, ALICE, admin=True)).json()["users"]}
    assert users[BOB]["last_sign_in"] is not None and not users[BOB]["last_sign_in_unknown"]
    assert users[ALICE]["last_sign_in"] is None and users[ALICE]["last_sign_in_unknown"]
    assert users["user-d"]["last_sign_in"] is None and not users["user-d"]["last_sign_in_unknown"]


def test_two_administrators_removing_each_other_at_once_leave_one(setup, monkeypatch):
    """External review, pass 7: "always one administrator" was checked, then acted on; two administrators
    removing each other's rights in the same instant could both pass the check. The check and the change now
    happen one at a time. Keycloak answers slowly here, so the two requests overlap as they would."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    import suveryn_api_gateway.routes.users as users_routes

    c, kc, api, cases = setup
    api.person("user-d", "Dirk Daems", "dirk@office.test", admin=True)
    accounts = c.app.state.accounts

    async def slow(request):
        await asyncio.sleep(0.05)
        return api.handler(request)

    accounts._http = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    alice, dirk = as_user(kc, ALICE, admin=True), {**as_user(kc, "user-d", admin=True)}

    def both():
        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(c.put, "/v1/admin/users/user-d/admin", json={"admin": False}, headers=alice)
            d = pool.submit(c.put, f"/v1/admin/users/{ALICE}/admin", json={"admin": False}, headers=dirk)
            return sorted([a.result().status_code, d.result().status_code])

    # without the lock, the race is real: both pass the check and nobody is left
    real = users_routes._admin_changes
    monkeypatch.setattr(users_routes, "_admin_changes", lambda request: asyncio.Lock())
    assert both() == [200, 200] and not api.admins
    api.admins = {ALICE, "user-d"}
    monkeypatch.setattr(users_routes, "_admin_changes", real)
    assert both() == [200, 409] and len(api.admins) == 1


class FakeDocuments:
    state, error = "ready", None

    def __init__(self):
        self.personal = {BOB: ["d1", "d2"]}
        self.fail = False

    def documents(self, scope):
        return self.personal.get(scope.owner, []) if scope.case_id is None else []

    def delete_all(self, scope):
        if self.fail:
            raise RuntimeError("the database went away")
        return len(self.personal.pop(scope.owner, []))

    def __getattr__(self, name):  # what the gateway's sweep and startup ask, unused here
        return lambda *a, **k: 0


class FakeHistory:
    def __init__(self):
        self.own = {BOB: 4}
        self.shared = {BOB: 1}
        self.fail = False

    def personal(self, sub):
        return self.own.get(sub, 0)

    def shared_count(self, sub):
        return self.shared.get(sub, 0)

    def delete_personal(self, sub):
        if self.fail:
            raise RuntimeError("the database went away")
        return self.own.pop(sub, 0)

    def __getattr__(self, name):
        return lambda *a, **k: 0


class FakeAvatars:
    def __init__(self):
        self.pictures = {BOB}

    def remove(self, sub):
        self.pictures.discard(sub)
        return True

    def __getattr__(self, name):
        return lambda *a, **k: 0


@pytest.fixture
def stores():
    kc, api, cases = FakeKeycloak(), FakeAdminApi(), FakeCases()
    api.person(ALICE, "Alice Admin", "alice@office.test", admin=True)
    api.person(BOB, "Bob Peeters", "bob@office.test", enabled=False)
    docs, history, avatars = FakeDocuments(), FakeHistory(), FakeAvatars()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    accounts = Accounts(AccountsSettings(issuer=ISSUER), transport=httpx.MockTransport(api.handler))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    app = create_app(llm, documents=docs, auth=auth, accounts=accounts, cases=cases, conversations=history, avatars=avatars)
    with TestClient(app) as c:
        yield c, kc, api, cases, docs, history, avatars


def test_deleting_with_every_store_takes_what_the_confirmation_said(stores):
    """External audit, 29 October: the deletion with its stores, not only the route. The confirmation's counts
    are what goes; what stays with the cases stays; the account goes last."""
    c, kc, api, cases, docs, history, avatars = stores
    admin = as_user(kc, ALICE, admin=True)
    assert c.get(f"/v1/admin/users/{BOB}/deletion", headers=admin).json() == {
        "documents": 2, "conversations": 4, "shared_conversations": 1}
    assert c.delete(f"/v1/admin/users/{BOB}", headers=admin).status_code == 204
    assert BOB not in docs.personal and BOB not in history.own and BOB not in avatars.pictures
    assert history.shared == {BOB: 1}  # the shared conversation stays with its case
    assert cases.departed == {BOB: "Bob Peeters"} and BOB not in api.users


def test_a_store_down_before_anything_is_deleted_deletes_nothing(stores):
    c, kc, api, cases, docs, history, avatars = stores
    docs.state = "starting"
    r = c.delete(f"/v1/admin/users/{BOB}", headers=as_user(kc, ALICE, admin=True))
    assert r.status_code == 503
    assert docs.personal == {BOB: ["d1", "d2"]} and history.own == {BOB: 4} and avatars.pictures == {BOB} and BOB in api.users


@pytest.mark.parametrize("where", ["documents", "conversations", "keycloak"])
def test_a_deletion_stopped_partway_says_so_and_finishes_when_done_again(stores, where):
    """External audit, 29 October: a store or Keycloak failing after another step has deleted. The answer is
    its own sentence (reason "unfinished"), the account stays, switched off, and deleting again finishes it,
    with the case attribution kept once."""
    c, kc, api, cases, docs, history, avatars = stores
    admin = as_user(kc, ALICE, admin=True)
    if where == "documents":
        docs.fail = True
    elif where == "conversations":
        history.fail = True
    else:
        api.down_on_delete = True
        original = api._answer
        api._answer = lambda path, method, body: (httpx.Response(500) if method == "DELETE" and getattr(api, "down_on_delete", False)
                                                  else original(path, method, body))
    r = c.delete(f"/v1/admin/users/{BOB}", headers=admin)
    assert r.status_code == 503 and r.json()["reason"] == "unfinished"
    assert BOB in api.users and api.users[BOB]["enabled"] is False  # still there, still off
    docs.fail = history.fail = api.down_on_delete = False
    assert c.delete(f"/v1/admin/users/{BOB}", headers=admin).status_code == 204
    assert BOB not in api.users and BOB not in docs.personal and BOB not in history.own and BOB not in avatars.pictures
    assert cases.departed == {BOB: "Bob Peeters"}
