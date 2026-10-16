"""Cases (suveryn-tracker#10, stages 1 and 2): the authorisation rules, the case endpoints, that
documents, chat and conversations stay inside the case or the personal space they are in, then
members and roles, handover, the office's directory and the access log.
Against a fake Keycloak, a fake document service and in-memory stores; the real store's tests
are at the end (PostgreSQL, ``SUVERYN_TEST_DATABASE_URL``)."""

import base64
import json
import os
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.cases import (
    Case,
    CaseEvent,
    CaseIn,
    CaseSettings,
    CaseStore,
    CaseUpdate,
    DuplicateReference,
    Member,
    Principal,
    may,
)
from suveryn_api_gateway.directory import Person
from suveryn_engine import LlamaServerClient, LLMSettings
from suveryn_rag.store import Scope
from test_auth import SETTINGS, FakeKeycloak
from test_conversations import FakeConversations, as_user
from test_documents import DOC, FakeDocuments, llm_transport

ALICE, BOB, CARLA, ADMIN = "alice-sub", "bob-sub", "carla-sub", "admin-sub"
PEOPLE = [Person(sub=ALICE, username="alice", name="Alice Peeters"), Person(sub=BOB, username="bob", name="Bob Janssens"),
          Person(sub=CARLA, username="carla", name="Carla Maes"), Person(sub=ADMIN, username="admin", name="The Administrator")]
NEW = {"reference": "2026/0417", "name": "Verkoop Kerkstraat 12", "type": "sale", "subject": {"property": "Kerkstraat 12, Gent"}}


# ------------------------------------------------------------------ the rules
def case(state="open", access="default", manager=ALICE) -> Case:
    now = datetime.now(UTC)
    return Case(id=str(uuid.uuid4()), reference="2026/0417", name="Verkoop", type="sale", subject={}, access=access,
                state=state, opened_at=now, closed_at=None, keep_until=None, keep=False, manager=manager,
                created_by=manager, created_at=now, updated_at=now)


@pytest.mark.parametrize("role, allowed", [
    (None, set()),
    ("reader", {"read"}),
    ("contributor", {"read", "contribute"}),
    ("manager", {"read", "contribute", "manage", "read_log"}),
])
def test_a_members_role_gives_the_rights_of_the_table(role, allowed):
    who = Principal(BOB)
    actions = {"read", "contribute", "manage", "reopen", "list", "handover", "read_log", "set_keep"}
    assert {a for a in actions if may(who, case(), role, a, office_wide=False)} == allowed


def test_an_administrator_sees_a_case_exists_and_nothing_inside_it():
    admin = Principal(ADMIN, admin=True)
    assert all(may(admin, case(), None, a, office_wide=False) for a in ("list", "handover", "read_log", "set_keep"))
    assert not any(may(admin, case(), None, a, office_wide=False) for a in ("read", "contribute", "manage"))
    assert may(admin, case(), "reader", "read", office_wide=False)  # unless a member
    assert not may(Principal(ALICE), case(), "manager", "handover", office_wide=False)  # and a manager isn't an admin
    assert may(Principal(ALICE), case(state="closed"), "manager", "read_log", office_wide=False)  # the log stays readable
    assert not may(Principal(BOB), case(), "contributor", "read_log", office_wide=False)


def test_office_wide_makes_everyone_a_reader_of_an_unrestricted_case_only():
    bob = Principal(BOB)
    assert may(bob, case(), None, "read", office_wide=True)
    assert not may(bob, case(), None, "contribute", office_wide=True)
    assert not may(bob, case(access="restricted"), None, "read", office_wide=True)
    assert may(bob, case(access="restricted"), "contributor", "contribute", office_wide=True)  # membership adds rights


def test_a_closed_case_is_read_only_and_its_manager_may_reopen_it():
    closed = case(state="closed")
    assert may(Principal(BOB), closed, "contributor", "read", office_wide=False)
    assert not may(Principal(BOB), closed, "contributor", "contribute", office_wide=False)
    assert not may(Principal(ALICE), closed, "manager", "manage", office_wide=False)
    assert may(Principal(ALICE), closed, "manager", "reopen", office_wide=False)
    assert not may(Principal(BOB), closed, "contributor", "reopen", office_wide=False)
    assert not may(Principal(ALICE), case(), "manager", "reopen", office_wide=False)  # an open case isn't reopened


def test_the_default_access_fails_closed(monkeypatch):
    monkeypatch.delenv("SUVERYN_CASES_DEFAULT_ACCESS", raising=False)
    assert CaseSettings.from_env().default_access == "members"
    monkeypatch.setenv("SUVERYN_CASES_DEFAULT_ACCESS", "office")
    assert CaseSettings.from_env().office_wide
    monkeypatch.setenv("SUVERYN_CASES_DEFAULT_ACCESS", "everyone")
    with pytest.raises(ValueError):
        CaseSettings.from_env()


def test_a_reference_name_or_type_is_not_blank():
    for bad in ({"reference": " "}, {"name": ""}, {"type": " "}, {"reference": "x" * 101}):
        with pytest.raises(ValueError):
            CaseIn(**{**NEW, **bad})


# ------------------------------------------------------------------ the endpoints
class FakeDirectory:
    """The office's accounts, as ``directory.Directory`` answers."""

    configured = True

    def __init__(self, people=PEOPLE):
        self.people = list(people)

    async def search(self, query="", limit=20):
        q = query.lower()
        return sorted([p for p in self.people if q in p.name.lower() or q in p.username.lower()], key=lambda p: p.name)[:limit]

    async def get(self, sub):
        return next((p for p in self.people if p.sub == sub), None)

    async def aclose(self):
        pass


class FakeCases:
    """In-memory stand-in for ``CaseStore``: cases, members (user -> Member) and the access log."""

    def __init__(self):
        self.cases: dict[uuid.UUID, Case] = {}
        self.rows: dict[uuid.UUID, dict[str, Member]] = {}
        self.log_lines: list[tuple[uuid.UUID, str, str, dict]] = []

    def create(self, body: CaseIn, user: str, username: str = "", name: str = "") -> Case:
        if any(c.reference.lower() == body.reference.lower() for c in self.cases.values()):
            raise DuplicateReference(body.reference)
        now = datetime.now(UTC)
        c = Case(id=str(uuid.uuid4()), **body.model_dump(), state="open", opened_at=now, closed_at=None, keep_until=None,
                 keep=False, manager=user, created_by=user, created_at=now, updated_at=now)
        cid = uuid.UUID(c.id)
        self.cases[cid] = c
        self.rows[cid] = {user: Member(user=user, username=username, name=name, role="manager", added_by=user, added_at=now)}
        self.log(cid, user, "created", {})
        return c.model_copy(update={"my_role": "manager"})

    def role_of(self, case_id, user):
        m = self.rows.get(case_id, {}).get(user)
        return m.role if m else None

    def get(self, case_id, user):
        c = self.cases.get(case_id)
        return c.model_copy(update={"my_role": self.role_of(case_id, user)}) if c else None

    def members(self, case_id):
        return sorted(self.rows[case_id].values(), key=lambda m: (m.role != "manager", m.name.lower()))

    def set_member(self, case_id, user, role, by, username="", name=""):
        if role == "manager":
            raise ValueError("use set_manager")
        old = self.rows[case_id].get(user)
        if old and old.role == "manager":
            raise ValueError("the manager's role is changed by handing the case over")
        m = Member(user=user, username=username or (old.username if old else ""), name=name or (old.name if old else ""),
                   role=role, added_by=old.added_by if old else by, added_at=old.added_at if old else datetime.now(UTC))
        self.rows[case_id][user] = m
        return m

    def remove_member(self, case_id, user):
        m = self.rows[case_id].get(user)
        if m is None or m.role == "manager":
            return False
        del self.rows[case_id][user]
        return True

    def set_manager(self, case_id, user, by, username="", name=""):
        c = self.cases.get(case_id)
        if c is None:
            return None
        if c.manager != user:
            self.rows[case_id][c.manager] = self.rows[case_id][c.manager].model_copy(update={"role": "contributor"})
            old = self.rows[case_id].get(user)
            self.rows[case_id][user] = Member(user=user, username=username or (old.username if old else ""),
                                                 name=name or (old.name if old else ""), role="manager", added_by=by,
                                                 added_at=old.added_at if old else datetime.now(UTC))
        self.cases[case_id] = c = c.model_copy(update={"manager": user, "updated_at": datetime.now(UTC)})
        return c.model_copy(update={"my_role": self.role_of(case_id, by)})

    def log(self, case_id, user, action, detail=None):
        self.log_lines.append((case_id, user, action, detail or {}))

    def events(self, case_id, limit=1000):
        lines = [l for l in self.log_lines if l[0] == case_id][-limit:][::-1]
        return [CaseEvent(id=i, user=u, at=datetime.now(UTC), action=a, detail=d) for i, (_, u, a, d) in enumerate(lines)]

    def list(self, user, *, office_wide, admin=False, closed=False):
        out = []
        for cid, c in self.cases.items():
            role = self.role_of(cid, user)
            if role is None and office_wide and c.access == "default":
                role = "reader"
            if (role or admin) and (closed or c.state == "open"):
                out.append(c.model_copy(update={"my_role": role}))
        return sorted(out, key=lambda c: (c.state != "open", -c.updated_at.timestamp()))

    def update(self, case_id, body: CaseUpdate):
        c = self.cases.get(case_id)
        if c is None:
            return None
        self.cases[case_id] = c = c.model_copy(update={**body.model_dump(exclude_none=True), "updated_at": datetime.now(UTC)})
        return c

    def touch(self, case_id):
        self.cases[case_id] = self.cases[case_id].model_copy(update={"updated_at": datetime.now(UTC)})

    def delete(self, case_id):
        return self.cases.pop(case_id, None) is not None

    def close(self, case_id):  # a stand-in for stage 3, to test the read-only rule end to end
        self.cases[case_id] = self.cases[case_id].model_copy(update={"state": "closed", "closed_at": datetime.now(UTC)})


@pytest.fixture
def office():
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases,
                     case_settings=CaseSettings(default_access="members"), directory=FakeDirectory())
    with TestClient(app) as c:
        yield c, kc, cases, history, docs


def admin_headers(kc: FakeKeycloak) -> dict:
    token = kc.tokens(over={"sub": ADMIN, "realm_access": {"roles": ["suveryn-admin"]}})["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_list_and_open_a_case(office):
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    r = c.post("/v1/cases", json=NEW, headers=alice)
    assert r.status_code == 201
    made = r.json()
    assert made["reference"] == "2026/0417" and made["manager"] == ALICE and made["my_role"] == "manager"
    assert made["state"] == "open" and made["access"] == "default"
    assert [x["id"] for x in c.get("/v1/cases", headers=alice).json()] == [made["id"]]
    assert c.get(f"/v1/cases/{made['id']}", headers=alice).json()["subject"] == {"property": "Kerkstraat 12, Gent"}
    # members only: Bob doesn't see it, and it is "unknown" to him, not "forbidden"
    assert c.get("/v1/cases", headers=bob).json() == []
    assert c.get(f"/v1/cases/{made['id']}", headers=bob).status_code == 404
    assert c.get(f"/v1/cases/{uuid.uuid4()}", headers=alice).status_code == 404
    assert c.get("/v1/cases/not-an-id", headers=alice).status_code == 422
    # the office's file numbers are unique: the same reference again is refused, whoever asks
    assert c.post("/v1/cases", json={**NEW, "reference": "2026/0417"}, headers=bob).status_code == 409


def test_only_the_manager_changes_or_deletes_a_case(office):
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    r = c.patch(f"/v1/cases/{cid}", json={"name": "Verkoop Kerkstraat 12 (deel 2)", "access": "restricted"}, headers=alice)
    assert r.status_code == 200 and r.json()["access"] == "restricted" and r.json()["reference"] == "2026/0417"
    assert c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=bob).status_code == 404
    assert c.delete(f"/v1/cases/{cid}", headers=bob).status_code == 404
    assert c.delete(f"/v1/cases/{cid}", headers=alice).status_code == 204
    assert c.get(f"/v1/cases/{cid}", headers=alice).status_code == 404


def test_an_administrator_sees_the_case_exists_but_not_what_is_in_it(office):
    c, kc, _, _, _ = office
    alice, admin = as_user(kc, ALICE), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    listed = c.get("/v1/cases", headers=admin).json()
    assert [x["id"] for x in listed] == [cid] and listed[0]["my_role"] is None and listed[0]["manager"] == ALICE
    assert c.get(f"/v1/cases/{cid}", headers=admin).status_code == 403
    assert c.get(f"/v1/documents?case={cid}", headers=admin).status_code == 403
    assert c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=admin).status_code == 403


def test_documents_in_a_case_are_separate_from_the_personal_space(office):
    c, kc, _, _, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    assert [d["id"] for d in c.get("/v1/documents", headers=alice).json()["documents"]] == [DOC]
    listed = c.get(f"/v1/documents?case={cid}", headers=alice).json()["documents"]
    assert [d["id"] for d in listed] == [in_case] and listed[0]["origin"] == "uploaded"
    assert c.get(f"/v1/documents?case={uuid.uuid4()}", headers=alice).status_code == 404
    # deleting takes the scope too: the personal document isn't in the case
    assert c.delete(f"/v1/documents/{DOC}?case={cid}", headers=alice).status_code == 404
    assert c.delete(f"/v1/documents/{in_case}?case={cid}", headers=alice).status_code == 204
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 204


def test_an_upload_goes_into_the_case_and_its_job_is_listed_there(office):
    c, kc, _, _, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    pdf = {"file": ("akte.pdf", b"%PDF-1.7 x", "application/pdf")}
    r = c.post(f"/v1/documents?case={cid}", files=pdf, headers=alice)
    assert r.status_code == 202 and docs.uploads == [("akte.pdf", ALICE, uuid.UUID(cid))]
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 404  # not Bob's case
    assert [j["id"] for j in c.get(f"/v1/documents?case={cid}", headers=alice).json()["jobs"]] == [r.json()["id"]]
    assert c.get("/v1/documents", headers=alice).json()["jobs"] == []
    assert c.get(f"/v1/documents/jobs/{r.json()['id']}", headers=bob).status_code == 404


def test_ask_about_this_case_only_reads_the_cases_uploaded_documents(office):
    c, kc, _, _, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case, generated = str(uuid.uuid4()), str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    docs.docs[generated] = (Scope.case(uuid.UUID(cid)), "generated")
    ask = {"messages": [{"role": "user", "content": "Wat is de koopprijs?"}], "document_ids": [in_case], "case_id": cid}
    assert c.post("/v1/chat", json=ask, headers=alice).status_code == 200
    assert docs.seen["case_id"] == uuid.UUID(cid) and docs.seen["owner"] is None
    # a personal document can't be asked about in the case, nor a case document outside it
    assert c.post("/v1/chat", json={**ask, "document_ids": [DOC]}, headers=alice).status_code == 404
    assert c.post("/v1/chat", json={**ask, "case_id": None}, headers=alice).status_code == 404
    # sūveryn's own output is never a source (decision 7)
    assert c.post("/v1/chat", json={**ask, "document_ids": [in_case, generated]}, headers=alice).status_code == 404
    # and Bob can't ask in Alice's case at all
    assert c.post("/v1/chat", json=ask, headers=bob).status_code == 404
    assert c.post("/v1/chat", json={**ask, "case_id": "nope"}, headers=alice).status_code == 422


def test_conversations_are_listed_with_their_case(office):
    c, kc, _, _, _ = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    personal, in_case = str(uuid.uuid4()), str(uuid.uuid4())
    turns = [{"role": "user", "text": "Vraag"}, {"role": "assistant", "text": "Antwoord"}]
    assert c.put(f"/v1/conversations/{personal}", json={"title": "Los", "turns": turns}, headers=alice).status_code == 204
    assert c.put(f"/v1/conversations/{in_case}", json={"title": "Dossier", "turns": turns, "case_id": cid},
                 headers=alice).status_code == 204
    assert [x["id"] for x in c.get("/v1/conversations", headers=alice).json()] == [personal]
    listed = c.get(f"/v1/conversations?case={cid}", headers=alice).json()
    assert [x["id"] for x in listed] == [in_case] and listed[0]["case_id"] == cid
    assert c.get(f"/v1/conversations/{in_case}", headers=alice).json()["case_id"] == cid
    # a conversation can't be saved into a case the caller may not see
    assert c.put(f"/v1/conversations/{uuid.uuid4()}", json={"title": "x", "turns": turns, "case_id": str(uuid.uuid4())},
                 headers=alice).status_code == 404
    # a later save doesn't move it
    c.put(f"/v1/conversations/{in_case}", json={"title": "Dossier 2", "turns": turns}, headers=alice)
    assert [x["id"] for x in c.get(f"/v1/conversations?case={cid}", headers=alice).json()] == [in_case]


def test_deleting_a_case_deletes_its_documents_and_conversations(office):
    c, kc, _, history, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    turns = [{"role": "user", "text": "Vraag"}, {"role": "assistant", "text": "Antwoord"}]
    c.put(f"/v1/conversations/{uuid.uuid4()}", json={"title": "Dossier", "turns": turns, "case_id": cid}, headers=alice)
    c.put(f"/v1/conversations/{uuid.uuid4()}", json={"title": "Los", "turns": turns}, headers=alice)
    assert c.delete(f"/v1/cases/{cid}", headers=alice).status_code == 204
    assert set(docs.docs) == {DOC}  # the personal document stays
    assert [x["title"] for x in c.get("/v1/conversations", headers=alice).json()] == ["Los"]
    assert not any(r["case_id"] for r in history.rows.values())


def test_a_closed_case_refuses_uploads_and_questions(office):
    c, kc, cases, _, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    cases.close(uuid.UUID(cid))
    assert c.get(f"/v1/documents?case={cid}", headers=alice).status_code == 200  # reading stays
    assert c.get("/v1/cases", headers=alice).json() == [] and len(c.get("/v1/cases?closed=true", headers=alice).json()) == 1
    r = c.post(f"/v1/documents?case={cid}", files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}, headers=alice)
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    assert c.delete(f"/v1/documents/{in_case}?case={cid}", headers=alice).status_code == 403
    assert c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=alice).status_code == 403


def test_office_wide_appliance_lets_colleagues_read_but_not_contribute():
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, cases=cases,
                     case_settings=CaseSettings(default_access="office"))
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    with TestClient(app) as c:
        cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        listed = c.get("/v1/cases", headers=bob).json()
        assert [x["id"] for x in listed] == [cid] and listed[0]["my_role"] == "reader"
        assert c.get(f"/v1/documents?case={cid}", headers=bob).status_code == 200
        r = c.post(f"/v1/documents?case={cid}", files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}, headers=bob)
        assert r.status_code == 403
        c.patch(f"/v1/cases/{cid}", json={"access": "restricted"}, headers=alice)  # the manager restricts it
        assert c.get("/v1/cases", headers=bob).json() == []
        assert c.get(f"/v1/documents?case={cid}", headers=bob).status_code == 404


# ------------------------------------------------------------------ stage 2: members, roles, the log
def test_the_manager_adds_colleagues_from_the_directory_with_a_role(office):
    c, kc, cases, _, docs = office
    alice, bob, carla = as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    # the directory: the office's accounts, searched by name or username
    assert [p["username"] for p in c.get("/v1/users?q=ja", headers=alice).json()] == ["bob"]
    assert c.get(f"/v1/cases/{cid}/members", headers=alice).json()[0] == {
        "user": ALICE, "username": "notaris.test", "name": "Test Notaris", "role": "manager", "added_by": ALICE,
        "added_at": c.get(f"/v1/cases/{cid}/members", headers=alice).json()[0]["added_at"]}
    assert c.get(f"/v1/cases/{cid}/members", headers=bob).status_code == 404  # not yet a member: unknown case
    r = c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    assert r.status_code == 200 and r.json()["name"] == "Bob Janssens" and r.json()["role"] == "reader"
    assert c.put(f"/v1/cases/{cid}/members/nobody-sub", json={"role": "reader"}, headers=alice).status_code == 404
    assert c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "manager"}, headers=alice).status_code == 422
    # Bob reads, doesn't contribute; a role change makes him a contributor
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    assert c.get(f"/v1/cases/{cid}", headers=bob).json()["my_role"] == "reader"
    assert c.get(f"/v1/documents?case={cid}", headers=bob).status_code == 200
    pdf = {"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 403
    ask = {"messages": [{"role": "user", "content": "Vraag?"}], "document_ids": [in_case], "case_id": cid}
    assert c.post("/v1/chat", json=ask, headers=bob).status_code == 403
    assert c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice).json()["role"] == "contributor"
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 202
    assert c.post("/v1/chat", json=ask, headers=bob).status_code == 200
    # a contributor can't change members, and a reader can't see the log
    assert c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=bob).status_code == 403
    assert c.get(f"/v1/cases/{cid}/events", headers=bob).status_code == 403
    # members see the list; removal; the manager can't be removed
    assert [m["user"] for m in c.get(f"/v1/cases/{cid}/members", headers=bob).json()] == [ALICE, BOB]
    assert c.delete(f"/v1/cases/{cid}/members/{ALICE}", headers=alice).status_code == 422
    assert c.delete(f"/v1/cases/{cid}/members/{BOB}", headers=alice).status_code == 204
    assert c.delete(f"/v1/cases/{cid}/members/{BOB}", headers=alice).status_code == 404
    assert c.get(f"/v1/cases/{cid}", headers=bob).status_code == 404
    assert c.get("/v1/cases", headers=carla).json() == []


def test_handover_by_the_manager_or_an_administrator_keeps_one_manager(office):
    c, kc, cases, _, _ = office
    alice, bob, admin = as_user(kc, ALICE), as_user(kc, BOB), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    assert c.post(f"/v1/cases/{cid}/handover", json={"user": BOB}, headers=bob).status_code == 404  # not even visible
    r = c.post(f"/v1/cases/{cid}/handover", json={"user": BOB}, headers=alice)
    assert r.status_code == 200 and r.json()["manager"] == BOB and r.json()["my_role"] == "contributor"
    roles = {m["user"]: m["role"] for m in c.get(f"/v1/cases/{cid}/members", headers=alice).json()}
    assert roles == {BOB: "manager", ALICE: "contributor"}
    assert c.post(f"/v1/cases/{cid}/handover", json={"user": ALICE}, headers=alice).status_code == 403  # no longer manages
    # an administrator hands it over without being a member (decision 6), to someone in the directory
    assert c.post(f"/v1/cases/{cid}/handover", json={"user": "nobody-sub"}, headers=admin).status_code == 404
    r = c.post(f"/v1/cases/{cid}/handover", json={"user": CARLA}, headers=admin)
    assert r.status_code == 200 and r.json()["manager"] == CARLA and r.json()["my_role"] is None
    roles = {m["user"]: m["role"] for m in c.get(f"/v1/cases/{cid}/members", headers=alice).json()}
    assert roles == {CARLA: "manager", BOB: "contributor", ALICE: "contributor"}
    assert c.get(f"/v1/cases/{cid}/events", headers=admin).status_code == 200  # the administrator reads the log


def test_the_access_log_says_who_did_what(office):
    c, kc, cases, _, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.get(f"/v1/cases/{cid}", headers=bob)
    c.get(f"/v1/documents?case={cid}", headers=bob)
    r = c.post(f"/v1/documents?case={cid}", files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}, headers=bob)
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    c.post("/v1/chat", json={"messages": [{"role": "user", "content": "Wat is de koopprijs?"}], "document_ids": [in_case],
                             "case_id": cid}, headers=bob)
    c.patch(f"/v1/cases/{cid}", json={"access": "restricted", "name": "Verkoop Kerkstraat 12 (deel 2)"}, headers=alice)
    c.delete(f"/v1/documents/{in_case}?case={cid}", headers=alice)
    c.delete(f"/v1/cases/{cid}/members/{BOB}", headers=alice)
    events = c.get(f"/v1/cases/{cid}/events", headers=alice).json()
    assert [(e["user"], e["action"]) for e in events] == [
        (ALICE, "member_removed"), (ALICE, "document_deleted"), (ALICE, "changed"), (ALICE, "access_changed"),
        (BOB, "asked"), (BOB, "uploaded"), (BOB, "opened"), (ALICE, "member_added"), (ALICE, "created")]
    assert events[4]["detail"] == {"documents": [in_case]} and events[5]["detail"] == {"job": r.json()["id"]}
    assert not any(e["action"] == "documents" for e in events)  # listing is not reading: not logged
    assert events[3]["detail"] == {"access": "restricted"} and events[2]["detail"] == {"fields": ["name"]}
    assert all("Wat is" not in json.dumps(e) and "Kerkstraat" not in json.dumps(e) for e in events)  # never text


def test_the_directory_reads_keycloak_with_its_own_client():
    """``directory.Directory`` against a mock Keycloak: a client-credentials token for suveryn-directory,
    then the admin API's user list and lookup; disabled accounts and service accounts left out."""
    import asyncio

    from suveryn_api_gateway.directory import (
        Directory,
        DirectorySettings,
        DirectoryUnavailable,
    )

    calls = []

    def keycloak(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/protocol/openid-connect/token"):
            if request.headers.get("authorization") != "Basic " + base64.b64encode(b"suveryn-directory:d1r").decode():
                return httpx.Response(401, json={"error": "unauthorized_client"})
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "svc-token", "expires_in": 300})
        if request.headers.get("authorization") != "Bearer svc-token":
            return httpx.Response(401)
        if request.url.path == "/admin/realms/suveryn/users":
            assert request.url.params["enabled"] == "true" and request.url.params["briefRepresentation"] == "true"
            q = request.url.params.get("search", "")
            users = [{"id": BOB, "username": "bob", "firstName": "Bob", "lastName": "Janssens", "enabled": True},
                     {"id": ALICE, "username": "alice", "firstName": "Alice", "lastName": "Peeters", "enabled": True},
                     {"id": "svc", "username": "service-account-suveryn-directory", "enabled": True,
                      "serviceAccountClientId": "suveryn-directory"},
                     {"id": "old", "username": "old", "enabled": False}]
            return httpx.Response(200, json=[u for u in users if q in u["username"]])
        if request.url.path == f"/admin/realms/suveryn/users/{BOB}":
            return httpx.Response(200, json={"id": BOB, "username": "bob", "firstName": "Bob", "lastName": "Janssens", "enabled": True})
        if request.url.path.startswith("/admin/realms/suveryn/users/"):
            return httpx.Response(404, json={"error": "User not found"})
        return httpx.Response(404)

    settings = DirectorySettings(issuer="http://keycloak.test/realms/suveryn", client_secret="d1r")
    assert settings.admin_url == "http://keycloak.test/admin/realms/suveryn"
    d = Directory(settings, transport=httpx.MockTransport(keycloak))

    async def run():
        people = await d.search("")
        assert [(p.username, p.name) for p in people] == [("alice", "Alice Peeters"), ("bob", "Bob Janssens")]
        assert [p.username for p in await d.search("bo")] == ["bob"]
        assert await d.search("") == people and len([c for c in calls if c[1].endswith("/token")]) == 1  # cached; one token
        assert (await d.get(BOB)).name == "Bob Janssens" and await d.get("nobody") is None
        assert await d.get("../realms") is None  # never a path of its own
        with pytest.raises(DirectoryUnavailable):
            await Directory(DirectorySettings(issuer=settings.issuer, client_secret="wrong"),
                            transport=httpx.MockTransport(keycloak)).search("")
        with pytest.raises(DirectoryUnavailable):
            await Directory(DirectorySettings(), transport=httpx.MockTransport(keycloak)).search("")
        await d.aclose()

    asyncio.run(run())


def test_with_sign_in_off_the_directory_holds_the_local_user():
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled(), cases=FakeCases())) as c:
        assert [p["sub"] for p in c.get("/v1/users").json()] == ["local-dev"]
        assert c.get("/health").json()["directory"]["status"] == "ready"
        cid = c.post("/v1/cases", json=NEW).json()["id"]
        assert c.get(f"/v1/cases/{cid}/members").json()[0]["username"] == "dev"


def test_without_a_database_cases_are_unavailable():
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled())) as c:
        assert c.get("/v1/cases").status_code == 503
        assert c.post("/v1/cases", json=NEW).status_code == 503
        assert c.get("/health").json()["cases"]["status"] == "unavailable"
        assert c.get("/v1/documents?case=" + str(uuid.uuid4())).status_code == 503


# ------------------------------------------------------------------ the store
URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")


@pytest.fixture
def store():
    if not URL:
        pytest.skip("SUVERYN_TEST_DATABASE_URL not set")
    s = CaseStore(CaseSettings(database_url=URL))
    clean = lambda: s._execute("DELETE FROM cases WHERE reference IN (%s, %s)", (NEW["reference"], "2026/0418"))
    clean()
    yield s
    clean()
    s.close()


def test_store_creates_lists_updates_and_deletes(store):
    s = store
    alice, bob = f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"
    c = s.create(CaseIn(**NEW), alice)
    assert c.my_role == "manager" and c.manager == alice and c.state == "open" and c.subject == NEW["subject"]
    assert s.role_of(uuid.UUID(c.id), alice) == "manager" and s.role_of(uuid.UUID(c.id), bob) is None
    assert s.get(uuid.UUID(c.id), bob).my_role is None and s.get(uuid.uuid4(), alice) is None
    assert [x.id for x in s.list(alice, office_wide=False)] == [c.id]
    assert s.list(bob, office_wide=False) == []
    assert [x.my_role for x in s.list(bob, office_wide=True) if x.id == c.id] == ["reader"]
    assert [x.my_role for x in s.list(bob, office_wide=False, admin=True) if x.id == c.id] == [None]
    changed = s.update(uuid.UUID(c.id), CaseUpdate(access="restricted", subject={"property": "elsewhere"}))
    assert changed.access == "restricted" and changed.subject == {"property": "elsewhere"} and changed.updated_at > c.updated_at
    assert [x.id for x in s.list(bob, office_wide=True) if x.id == c.id] == []
    assert s.update(uuid.uuid4(), CaseUpdate(name="x")) is None
    assert s.manages(alice) == 1
    with pytest.raises(DuplicateReference):
        s.create(CaseIn(**{**NEW, "reference": NEW["reference"].upper()}), bob)
    other = s.create(CaseIn(**{**NEW, "reference": "2026/0418"}), bob)
    with pytest.raises(DuplicateReference):
        s.update(uuid.UUID(other.id), CaseUpdate(reference=NEW["reference"]))
    assert s.delete(uuid.UUID(c.id)) and not s.delete(uuid.UUID(c.id))
    assert s.role_of(uuid.UUID(c.id), alice) is None  # the membership went with it


def test_store_members_handover_and_the_log(store):
    s = store
    alice, bob, carla = f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}", f"carla-{uuid.uuid4()}"
    c = s.create(CaseIn(**NEW), alice, "alice", "Alice Peeters")
    cid = uuid.UUID(c.id)
    assert [(m.user, m.role, m.name) for m in s.members(cid)] == [(alice, "manager", "Alice Peeters")]
    m = s.set_member(cid, bob, "reader", alice, "bob", "Bob Janssens")
    assert m.role == "reader" and m.added_by == alice
    assert s.set_member(cid, bob, "contributor", alice).name == "Bob Janssens"  # the name is kept when not given
    with pytest.raises(ValueError):
        s.set_member(cid, alice, "reader", alice)  # the manager's role: only by handing over
    with pytest.raises(ValueError):
        s.set_member(cid, carla, "manager", alice)
    assert [(m.user, m.role) for m in s.members(cid)] == [(alice, "manager"), (bob, "contributor")]
    assert not s.remove_member(cid, alice) and s.remove_member(cid, bob) and not s.remove_member(cid, bob)
    # handover: exactly one manager, the previous one stays as a contributor; to a non-member too
    handed = s.set_manager(cid, carla, alice, "carla", "Carla Maes")
    assert handed.manager == carla and handed.my_role == "contributor"
    assert [(m.user, m.role) for m in s.members(cid)] == [(carla, "manager"), (alice, "contributor")]
    assert s.set_manager(cid, carla, carla).manager == carla  # to oneself: nothing changes
    assert s.set_manager(uuid.uuid4(), carla, alice) is None
    # the log, newest first
    s.log(cid, alice, "opened")
    s.log(cid, carla, "asked", {"documents": ["x"]})
    events = s.events(cid)
    assert [(e.user, e.action) for e in events] == [(carla, "asked"), (alice, "opened"), (alice, "created")]
    assert events[0].detail == {"documents": ["x"]}
    s._execute("UPDATE case_events SET at = now() - interval '181 days' WHERE case_id = %s AND action = 'created'", (cid,))
    assert [e.action for e in s.events(cid)] == ["asked", "opened"]  # purged after 180 days
    assert s.delete(cid) and s.events(cid) == []  # the log goes with the case
