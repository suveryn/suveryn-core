"""The users area against the gateway's description (suveryn-tracker#241): the accounts, the office's people and
pictures. The chat UI's code for it is generated from the description, so each answer its operations give, the
refusals too, is checked against it and kept for the chat UI's tests. What the operations do is tested in
``test_users.py`` and ``test_avatars.py``."""

import httpx
from described import Checked
from fastapi.testclient import TestClient
from suveryn_api_gateway.accounts import Accounts, AccountsSettings
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.directory import DirectoryUnavailable, Person
from suveryn_harness import LlamaServerClient, LLMSettings
from test_auth import SETTINGS, FakeKeycloak
from test_documents import llm_transport
from test_users import ALICE, BOB, CAROL, ISSUER, FakeAdminApi, FakeCases, FakeDocuments, FakeHistory, as_user

WHEN, SUB, PASSWORD = "2026-11-22T09:00:00Z", "00000000-0000-4000-8000-000000000001", "abcd-efgh-jkmn-pqrs"


class Pictures:
    """A stand-in for the pictures' store: one picture per person, by an ETag."""

    def __init__(self):
        self.kept = {BOB: (b"RIFF....WEBP", "bobs")}

    def get(self, sub):
        return self.kept.get(sub)

    def set(self, sub, upload):
        self.kept[sub] = (upload, "new1")
        return "new1"

    def remove(self, sub):
        return self.kept.pop(sub, None) is not None

    def etags(self, subs):
        return {s: self.kept[s][1] for s in subs if s in self.kept}

    def purge(self):
        return 0


class People:
    """A stand-in for the office's directory."""

    def __init__(self, api):
        self.api, self.configured, self.away = api, True, False

    async def holds_admin(self, sub):
        return sub in self.api.admins

    async def admins(self):
        return set(self.api.admins)

    async def search(self, query="", limit=20):
        if self.away:
            raise DirectoryUnavailable("unreachable")
        return [Person(sub=BOB, username="bob@office.test", name="Bob Peeters"), Person(sub=CAROL, username="carol@office.test", name="Carol Claes")]

    async def get(self, sub):
        return None

    async def aclose(self):
        pass


def test_every_answer_of_users_is_what_the_description_says():
    kc, api, cases, pictures = FakeKeycloak(), FakeAdminApi(), FakeCases(), Pictures()
    api.person(ALICE, "Alice Admin", "alice@office.test", admin=True)
    api.person(BOB, "Bob Peeters", "bob@office.test")
    api.person(CAROL, "Carol Claes", "carol@office.test")
    api.events = [{"type": "LOGIN", "userId": BOB, "time": 1_793_000_000_000}]
    people = People(api)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    accounts = Accounts(AccountsSettings(issuer=ISSUER), transport=httpx.MockTransport(api.handler))
    app = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([])), documents=FakeDocuments(), auth=auth,
                     accounts=accounts, cases=cases, conversations=FakeHistory(), avatars=pictures, directory=people)
    admin_only = [("GET", "/v1/admin/users", None, {}), ("POST", "/v1/admin/users", None, {"json": {"name": "J", "email": "j@office.test"}}),
                  ("GET", "/v1/admin/users/events", None, {}), ("DELETE", "/v1/admin/users/{sub}", f"/v1/admin/users/{CAROL}", {}),
                  ("PUT", "/v1/admin/users/{sub}/admin", f"/v1/admin/users/{CAROL}/admin", {"json": {"admin": True}}),
                  ("GET", "/v1/admin/users/{sub}/deletion", f"/v1/admin/users/{CAROL}/deletion", {}),
                  ("PUT", "/v1/admin/users/{sub}/enabled", f"/v1/admin/users/{CAROL}/enabled", {"json": {"enabled": False}}),
                  ("POST", "/v1/admin/users/{sub}/password", f"/v1/admin/users/{CAROL}/password", {}),
                  ("POST", "/v1/admin/users/{sub}/sign-out", f"/v1/admin/users/{CAROL}/sign-out", {}),
                  ("POST", "/v1/admin/users/{sub}/two-step", f"/v1/admin/users/{CAROL}/two-step", {})]
    anyone = [("GET", "/v1/users", None, {}), ("GET", "/v1/users/departed", None, {}), ("DELETE", "/v1/me/avatar", None, {}),
              ("PUT", "/v1/me/avatar", None, {"content": b"an image"}), ("GET", "/v1/users/{sub}/avatar", f"/v1/users/{BOB}/avatar", {})]

    def account(body):  # an account made in this run: its id
        body["sub"] = SUB if body["username"] == "jonas.c@office.test" else body["sub"]

    def temporary(body):  # and its temporary password
        account(body["user"])
        body["password"] = PASSWORD

    with TestClient(app) as c:
        check, user, admin = Checked(c, "users"), as_user(kc, BOB), as_user(kc, ALICE, admin=True)
        for method, path, at, sent in admin_only + anyone:
            assert check(method, path, 401, at, **sent).json()["code"] == "auth.signed_out"
        for method, path, at, sent in admin_only:
            keep = "not_an_administrator" if path == "/v1/admin/users" and method == "GET" else None
            assert check(method, path, 403, at, keep, headers=user, **sent).json()["code"] == "request.forbidden"

        # the accounts
        listed = check("GET", "/v1/admin/users", 200, keep="accounts", headers=admin).json()
        assert [u["name"] for u in listed["users"]] == ["Alice Admin", "Bob Peeters", "Carol Claes"] and listed["users"][1]["last_sign_in"]
        new = {"name": "Jonas  Claes", "email": "Jonas.C@office.test", "admin": False}
        added = check("POST", "/v1/admin/users", 201, keep="added", tidy=temporary, json=new, headers=admin).json()
        jonas = added["user"]["sub"]
        assert check("POST", "/v1/admin/users", 409, keep="email_exists", json=new, headers=admin).json()["code"] == "account.email_exists"
        assert "errors" in check("POST", "/v1/admin/users", 422, json={"name": "", "email": "nobody"}, headers=admin).json()
        of = lambda path: (f"/v1/admin/users/{{sub}}{path}", 200, f"/v1/admin/users/{jonas}{path}")  # noqa: E731
        assert check("PUT", *of("/admin"), "made_administrator", tidy=account, json={"admin": True}, headers=admin).json()["admin"] is True
        check("PUT", *of("/admin"), json={"admin": False}, headers=admin)
        assert check("PUT", "/v1/admin/users/{sub}/admin", 409, f"/v1/admin/users/{ALICE}/admin", "last_administrator", json={"admin": False},
                     headers=admin).json()["code"] == "account.last_administrator"
        assert check("PUT", "/v1/admin/users/{sub}/admin", 404, "/v1/admin/users/no-such-account/admin", "no_such_account", json={"admin": True},
                     headers=admin).json()["code"] == "request.not_found"
        assert "errors" in check("PUT", "/v1/admin/users/{sub}/admin", 422, f"/v1/admin/users/{jonas}/admin", json={}, headers=admin).json()
        check("POST", *of("/password"), "password_reset", tidy=temporary, headers=admin)
        check("POST", "/v1/admin/users/{sub}/password", 404, "/v1/admin/users/no-such-account/password", headers=admin)
        check("POST", "/v1/admin/users/{sub}/two-step", 204, f"/v1/admin/users/{jonas}/two-step", "done", headers=admin)
        check("POST", "/v1/admin/users/{sub}/two-step", 404, "/v1/admin/users/no-such-account/two-step", headers=admin)
        check("POST", "/v1/admin/users/{sub}/sign-out", 204, f"/v1/admin/users/{jonas}/sign-out", headers=admin)
        check("POST", "/v1/admin/users/{sub}/sign-out", 404, "/v1/admin/users/no-such-account/sign-out", headers=admin)
        assert check("PUT", "/v1/admin/users/{sub}/enabled", 409, f"/v1/admin/users/{ALICE}/enabled", "own_account", json={"enabled": False},
                     headers=admin).json()["code"] == "account.own_account"
        check("PUT", "/v1/admin/users/{sub}/enabled", 404, "/v1/admin/users/no-such-account/enabled", json={"enabled": False}, headers=admin)
        assert "errors" in check("PUT", "/v1/admin/users/{sub}/enabled", 422, f"/v1/admin/users/{jonas}/enabled", json={}, headers=admin).json()
        assert check("GET", "/v1/admin/users/{sub}/deletion", 409, f"/v1/admin/users/{jonas}/deletion", "not_switched_off",
                     headers=admin).json()["code"] == "account.not_switched_off"
        assert check("DELETE", "/v1/admin/users/{sub}", 409, f"/v1/admin/users/{jonas}", headers=admin).json()["code"] == "account.not_switched_off"
        assert check("PUT", *of("/enabled"), "switched_off", tidy=account, json={"enabled": False}, headers=admin).json()["enabled"] is False
        assert check("GET", *of("/deletion"), "deletion", headers=admin).json().keys() == {"documents", "conversations", "shared_conversations"}
        check("GET", "/v1/admin/users/{sub}/deletion", 404, "/v1/admin/users/no-such-account/deletion", headers=admin)

        def moments(events):  # when: the moment this test ran
            for e in events:
                e["at"], e["user"] = WHEN, SUB if e["name"] == "Jonas Claes" else e["user"]
        events = check("GET", "/v1/admin/users/events", 200, "/v1/admin/users/events?limit=5", "events", tidy=moments, headers=admin).json()
        assert {e["kind"] for e in events} <= {"added", "made_admin", "admin_removed", "password_reset", "two_step_reset", "signed_out_everywhere",
                                               "switched_off", "signed_in"} and len(events) == 5
        assert "errors" in check("GET", "/v1/admin/users/events", 422, "/v1/admin/users/events?limit=many", headers=admin).json()
        check("DELETE", "/v1/admin/users/{sub}", 204, f"/v1/admin/users/{jonas}", headers=admin)
        check("DELETE", "/v1/admin/users/{sub}", 404, "/v1/admin/users/no-such-account", headers=admin)

        # the office's people
        found = check("GET", "/v1/users", 200, "/v1/users?q=e", "people", headers=user).json()
        assert [(p["name"], p["avatar"]) for p in found] == [("Bob Peeters", "bobs"), ("Carol Claes", None)]
        people.away = True
        assert check("GET", "/v1/users", 503, keep="directory_away", headers=user).json()["code"] == "auth.unavailable"
        def gone(names):  # the account made and deleted in this run: its id
            names[SUB] = names.pop(jonas)
        assert check("GET", "/v1/users/departed", 200, keep="departed", tidy=gone, headers=user).json() == {jonas: "Jonas Claes"}

        # pictures
        picture = check("GET", "/v1/users/{sub}/avatar", 200, f"/v1/users/{BOB}/avatar", headers=user)
        assert picture.headers["etag"] == '"bobs"' and picture.content == b"RIFF....WEBP"
        check("GET", "/v1/users/{sub}/avatar", 304, f"/v1/users/{BOB}/avatar", headers={**user, "If-None-Match": '"bobs"'})
        assert check("GET", "/v1/users/{sub}/avatar", 404, f"/v1/users/{CAROL}/avatar", "no_picture", headers=user).json()["code"] == "request.not_found"
        octets = {"Content-Type": "application/octet-stream"}
        assert check("PUT", "/v1/me/avatar", 200, keep="picture_set", content=b"an image", headers={**user, **octets}).json() == {"avatar": "new1"}
        assert check("PUT", "/v1/me/avatar", 415, keep="no_picture_sent", content=b"", headers={**user, **octets}).json()["code"] == "request.unsupported"
        assert check("PUT", "/v1/me/avatar", 413, keep="picture_too_large", content=b"x" * (2 * 1024 * 1024 + 1),
                     headers={**user, **octets}).json()["code"] == "user.picture_too_large"
        check("DELETE", "/v1/me/avatar", 204, headers=user)
        check.kept.check()
        # not seen here, each for a reason: what nobody planned for (500); sign-in, the directory or a store down
        # (503: test_users.py, test_auth.py); the 422 FastAPI gives an operation whose only input is an id in the
        # address, or a search word, any text; sign-in turned off for another machine, for what anyone signed in
        # may do (403); and an account gone from the sign-in service while the accounts are listed (404)
        anyones = {(method, path) for method, path, _, _ in anyone}
        listing = {("GET", "/v1/admin/users"), ("POST", "/v1/admin/users"), ("GET", "/v1/admin/users/events")}
        for method, path, status in check.not_seen():
            assert (status in (500, 503) or (status == 422 and (method, path) not in {("POST", "/v1/admin/users"), ("PUT", "/v1/admin/users/{sub}/admin"),
                                                                                    ("PUT", "/v1/admin/users/{sub}/enabled"), ("GET", "/v1/admin/users/events")})
                    or (status == 403 and (method, path) in anyones) or (status == 404 and (method, path) in listing)), (method, path, status)
        assert {s for _, _, s in check.seen} == {200, 201, 204, 304, 401, 403, 404, 409, 413, 415, 422, 503}
