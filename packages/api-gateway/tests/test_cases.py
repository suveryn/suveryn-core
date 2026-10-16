"""Cases (suveryn-tracker#10, stage 1): the authorisation rules, the case endpoints, and that
documents, chat and conversations stay inside the case or the personal space they are in.
Against a fake Keycloak, a fake document service and in-memory stores; the real store's tests
are at the end (PostgreSQL, ``SUVERYN_TEST_DATABASE_URL``)."""

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
    CaseIn,
    CaseSettings,
    CaseStore,
    CaseUpdate,
    DuplicateReference,
    Principal,
    may,
)
from suveryn_engine import LlamaServerClient, LLMSettings
from suveryn_rag.store import Scope
from test_auth import SETTINGS, FakeKeycloak
from test_conversations import FakeConversations, as_user
from test_documents import DOC, FakeDocuments, llm_transport

ALICE, BOB, ADMIN = "alice-sub", "bob-sub", "admin-sub"
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
    ("manager", {"read", "contribute", "manage"}),
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
class FakeCases:
    """In-memory stand-in for ``CaseStore`` (stage 1: the creator is the only member)."""

    def __init__(self):
        self.cases: dict[uuid.UUID, Case] = {}
        self.members: dict[uuid.UUID, dict[str, str]] = {}

    def create(self, body: CaseIn, user: str) -> Case:
        if any(c.reference.lower() == body.reference.lower() for c in self.cases.values()):
            raise DuplicateReference(body.reference)
        now = datetime.now(UTC)
        c = Case(id=str(uuid.uuid4()), **body.model_dump(), state="open", opened_at=now, closed_at=None, keep_until=None,
                 keep=False, manager=user, created_by=user, created_at=now, updated_at=now)
        self.cases[uuid.UUID(c.id)], self.members[uuid.UUID(c.id)] = c, {user: "manager"}
        return c.model_copy(update={"my_role": "manager"})

    def get(self, case_id, user):
        c = self.cases.get(case_id)
        return c.model_copy(update={"my_role": self.members[case_id].get(user)}) if c else None

    def list(self, user, *, office_wide, admin=False, closed=False):
        out = []
        for cid, c in self.cases.items():
            role = self.members[cid].get(user)
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
                     case_settings=CaseSettings(default_access="members"))
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
