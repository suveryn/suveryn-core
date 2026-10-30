"""Cases (suveryn-tracker#10, stages 1 and 2): the authorisation rules, the case endpoints, that
documents, chat and conversations stay inside the case or the personal space they are in, then
members and roles, handover, the office's directory and the access log.
Against a fake Keycloak, a fake document service and in-memory stores; the real store's tests
are at the end (PostgreSQL, ``SUVERYN_TEST_DATABASE_URL``)."""

import base64
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import _delete_case_everywhere, create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.cases import (
    AdminCase,
    shielded,
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
from suveryn_harness import LlamaServerClient, LLMSettings
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
    ("manager", {"read", "contribute", "manage", "close", "read_log"}),
])
def test_a_members_role_gives_the_rights_of_the_table(role, allowed):
    who = Principal(BOB)
    actions = {"read", "contribute", "manage", "close", "reopen", "list", "handover", "read_log", "set_keep"}
    assert {a for a in actions if may(who, case(), role, a, office_wide=False)} == allowed


def test_an_administrator_sees_a_case_exists_and_nothing_inside_it():
    admin = Principal(ADMIN, admin=True)
    assert all(may(admin, case(), None, a, office_wide=False) for a in ("list", "handover", "read_log"))
    assert not any(may(admin, case(), None, a, office_wide=False) for a in ("read", "contribute", "manage", "set_keep"))
    assert may(admin, case(state="closed"), None, "set_keep", office_wide=False)  # the keep period, once closed
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
    assert may(Principal(ALICE), closed, "manager", "set_keep", office_wide=False)  # extend, keep: the manager's too
    assert may(Principal(ADMIN, admin=True), closed, None, "set_keep", office_wide=False)
    assert not may(Principal(BOB), closed, "contributor", "reopen", office_wide=False)
    assert not may(Principal(ALICE), case(), "manager", "reopen", office_wide=False)  # an open case isn't reopened
    assert not may(Principal(ALICE), case(), "manager", "set_keep", office_wide=False)  # nor kept: it's open
    assert not may(Principal(ALICE), closed, "manager", "close", office_wide=False)  # nor closed twice


def test_the_default_access_fails_closed(monkeypatch):
    monkeypatch.delenv("SUVERYN_CASES_DEFAULT_ACCESS", raising=False)
    assert CaseSettings.from_env().default_access == "members"
    monkeypatch.setenv("SUVERYN_CASES_DEFAULT_ACCESS", "office")
    assert CaseSettings.from_env().office_wide
    monkeypatch.setenv("SUVERYN_CASES_DEFAULT_ACCESS", "everyone")
    with pytest.raises(ValueError):
        CaseSettings.from_env()
    # the keep period: nothing is chosen for the office (decision 11), so closed cases are kept until deleted by hand
    monkeypatch.setenv("SUVERYN_CASES_DEFAULT_ACCESS", "members")
    assert CaseSettings.from_env().keep == "manual" and CaseSettings.from_env().keep_period is None
    monkeypatch.setenv("SUVERYN_CASES_KEEP", "5y")
    assert CaseSettings.from_env().keep_period == timedelta(days=5 * 366)
    monkeypatch.setenv("SUVERYN_CASES_KEEP", "forever")
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

    async def admins(self):
        return {ADMIN}  # the avatar's badge (routes/common.py with_faces)

    async def aclose(self):
        pass


class FakeCases:
    """In-memory stand-in for ``CaseStore``: cases, members (user -> Member) and the access log."""

    def __init__(self):
        self.cases: dict[uuid.UUID, Case] = {}
        self.rows: dict[uuid.UUID, dict[str, Member]] = {}
        self.log_lines: list[tuple[uuid.UUID, str, str, dict]] = []
        self.pins: set[tuple[uuid.UUID, str]] = set()
        self.settings_rows = {}
        self.purged = 0  # how often the sweep purged old access-log lines

    def purge_events(self):
        self.purged += 1
        return 0

    def set_pinned(self, case_id, user, pinned):
        (self.pins.add if pinned else self.pins.discard)((case_id, user))

    def create(self, body: CaseIn, user: str, username: str = "", name: str = "") -> Case:
        if any(c.reference.lower() == body.reference.lower() for c in self.cases.values()):
            raise DuplicateReference(body.reference)
        now = datetime.now(UTC)
        fields = body.model_dump()
        if fields["confidential"]:
            fields["access"] = "restricted"
        c = Case(id=str(uuid.uuid4()), **fields, state="open", opened_at=now, closed_at=None, keep_until=None,
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
        return c.model_copy(update={"my_role": self.role_of(case_id, user), "pinned": (case_id, user) in self.pins}) if c else None

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

    def members_of(self, case_ids):
        return {cid: self.members(cid) for cid in case_ids if cid in self.rows}

    def last_activity(self, case_ids):
        out = {}
        for cid, user, _, _ in self.log_lines:
            if cid in case_ids:
                out[cid] = (datetime.now(UTC), user)
        return out

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
                out.append(shielded(c.model_copy(update={"my_role": role, "pinned": (cid, user) in self.pins})))
        return sorted(out, key=lambda c: (c.state != "open", -c.updated_at.timestamp()))

    def list_all(self, viewer):
        out = []
        for cid, c in self.cases.items():
            m = self.rows[cid].get(c.manager)
            out.append(AdminCase(**shielded(c, self.role_of(cid, viewer)).model_dump(), manager_username=m.username if m else "",
                                 manager_name=m.name if m else "", members=len(self.rows[cid])))
        return sorted(out, key=lambda c: (c.state != "open", -c.updated_at.timestamp()))

    settings_meta = None

    def overrides(self):
        return dict(self.settings_rows)

    def overrides_meta(self):
        return self.settings_meta

    def access_counts(self):
        out = {"default": 0, "restricted": 0}
        for c in self.cases.values():
            if not c.confidential:
                out[c.access] += 1
        return out

    def set_overrides(self, changes, by, *, keep_existing=False, open_all=False, by_user=""):
        for cid, c in list(self.cases.items()):
            if c.confidential:
                continue
            if keep_existing and c.access == "default":
                self.cases[cid] = c.model_copy(update={"access": "restricted"})
            if open_all and c.access == "restricted":
                self.cases[cid] = c.model_copy(update={"access": "default"})
                self.log(cid, by_user, "access_changed", {"access": "default"})
        self.settings_rows.update(changes)
        self.settings_meta = (datetime.now(UTC), by)
        return dict(self.settings_rows)

    def update(self, case_id, body: CaseUpdate):
        from suveryn_api_gateway.cases import StrictlyConfidential

        c = self.cases.get(case_id)
        if c is None:
            return None
        fields = body.model_dump(exclude_none=True)
        if fields.get("confidential"):
            fields["access"] = "restricted"
        elif fields.get("access") == "default" and fields.get("confidential") is not False and c.confidential:
            raise StrictlyConfidential("members only")
        self.cases[case_id] = c = c.model_copy(update={**fields, "updated_at": datetime.now(UTC)})
        return c

    def confidential_ids(self, case_ids):
        return {str(i) for i in case_ids if (c := self.cases.get(i)) and c.confidential}

    def touch(self, case_id):
        self.cases[case_id] = self.cases[case_id].model_copy(update={"updated_at": datetime.now(UTC)})

    def delete(self, case_id):
        return self.cases.pop(case_id, None) is not None

    def close_case(self, case_id, period=None):
        c = self.cases.get(case_id)
        if c is None or c.state != "open":
            return None
        now = datetime.now(UTC)
        self.cases[case_id] = c = c.model_copy(update={"state": "closed", "closed_at": now, "keep": False,
                                                       "keep_until": now + period if period else None, "updated_at": now})
        return c

    def reopen_case(self, case_id):
        c = self.cases.get(case_id)
        if c is None or c.state != "closed":
            return None
        self.cases[case_id] = c = c.model_copy(update={"state": "open", "closed_at": None, "keep_until": None, "keep": False})
        return c

    def set_keep(self, case_id, keep, extend, period):
        c = self.cases.get(case_id)
        if c is None or c.state != "closed":
            return None
        now = datetime.now(UTC)
        kept, until = c.keep, c.keep_until
        if keep is not None:
            kept = keep
            if not keep:
                until = now + period if period else None
        if extend and period:
            until = max(until or now, now) + period
        self.cases[case_id] = c = c.model_copy(update={"keep": kept, "keep_until": until})
        return c

    def due_for_deletion(self):
        now = datetime.now(UTC)
        return [uuid.UUID(c.id) for c in self.cases.values() if c.state == "closed" and not c.keep and c.keep_until and c.keep_until <= now]


@pytest.fixture
def office():
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
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
    # the sidebar's "Documents": everything Alice may see, each with where it is (chat-ui.md)
    everything = {d["id"]: d["case_id"] for d in c.get("/v1/documents/all", headers=alice).json()["documents"]}
    assert everything == {DOC: None, in_case: cid}
    assert c.get("/v1/documents/all", headers=as_user(kc, BOB)).json()["documents"] == []  # not Bob's case
    # deleting takes the scope too: the personal document isn't in the case
    assert c.delete(f"/v1/documents/{DOC}?case={cid}", headers=alice).status_code == 404
    assert c.delete(f"/v1/documents/{in_case}?case={cid}", headers=alice).status_code == 204
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 204


def test_suveryns_own_output_coming_back_is_no_source_until_a_contributor_says_so(office):
    """docs/design/chat-ui.md §6: an upload with the export mark is stored, never blocked, and not
    used as a source until someone who may upload there chooses to; the case's log says so."""
    c, kc, _, _, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    back = str(uuid.uuid4())
    docs.docs[back] = (Scope.case(uuid.UUID(cid)), "uploaded")
    docs.noticed[back] = {"ref": "A-3f9c2e1b", "kind": "answer", "line": "Made by sūveryn · sūveryn-ref A-3f9c2e1b"}
    listed = {d["id"]: d for d in c.get(f"/v1/documents?case={cid}", headers=alice).json()["documents"]}
    assert listed[back]["source"] is False and listed[back]["provenance"]["noticed"]["ref"] == "A-3f9c2e1b"
    ask = {"messages": [{"role": "user", "content": "What is the price?"}], "document_ids": [back], "case_id": cid}
    assert c.post("/v1/chat", json=ask, headers=alice).status_code == 404  # not a source yet
    assert c.post(f"/v1/documents/{back}/source?case={cid}", headers=bob).status_code == 403  # a reader can't decide
    assert c.post(f"/v1/documents/{DOC}/source", headers=alice).status_code == 404  # nothing was noticed
    r = c.post(f"/v1/documents/{back}/source?case={cid}", headers=alice)
    assert r.status_code == 200 and r.json() == {"id": back, "source": True}
    assert docs.confirmed[back] == "notaris.test"
    events = c.get(f"/v1/cases/{cid}/events", headers=alice).json()
    assert events[0]["action"] == "source_confirmed" and events[0]["detail"]["ref"] == "A-3f9c2e1b"
    assert c.get(f"/v1/documents?case={cid}", headers=alice).json()["documents"][0]["source"] is True


def test_the_uploader_may_delete_their_own_noticed_upload_while_nobody_has_confirmed_it(office):
    """Deleting from the card is the uploader's right even as a contributor (deleting is otherwise the
    manager's); once confirmed, or someone else's, it is the manager's right again."""
    c, kc, _, _, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    mark = {"ref": "A-3f9c2e1b", "kind": "answer", "line": "sūveryn-ref A-3f9c2e1b"}
    def upload_by(user):
        did = str(uuid.uuid4())
        docs.docs[did], docs.noticed[did], docs.uploaders[did] = (Scope.case(uuid.UUID(cid)), "uploaded"), mark, user
        return did
    bobs, alices, plain = upload_by(BOB), upload_by(ALICE), str(uuid.uuid4())
    docs.docs[plain], docs.uploaders[plain] = (Scope.case(uuid.UUID(cid)), "uploaded"), BOB
    assert c.delete(f"/v1/documents/{alices}?case={cid}", headers=bob).status_code == 403  # not his upload
    assert c.delete(f"/v1/documents/{plain}?case={cid}", headers=bob).status_code == 403   # nothing noticed: the manager's
    c.post(f"/v1/documents/{bobs}/source?case={cid}", headers=bob)
    assert c.delete(f"/v1/documents/{bobs}?case={cid}", headers=bob).status_code == 403    # confirmed: the manager's
    again = upload_by(BOB)
    assert c.delete(f"/v1/documents/{again}?case={cid}", headers=bob).status_code == 204


def saved(question="What is the price?", message="m-1", **over):
    """An answer as the chat saves it to a case (docs/design/chat-ui.md §5)."""
    return {"filename": "What is the price.docx", "text": f"{question}\n\nThe price is EUR 300,000.",
            "content": {"question": question, "answer": "The price is EUR 300,000 [1].", "answeredOn": "2026-10-19T10:00:00Z",
                        "citations": [{"text": "The price is EUR 300,000.", "source": {"document_id": DOC, "page": 2}}],
                        "filenames": {DOC: "deed.pdf"}, "turnId": message},
            "conversation_id": str(uuid.uuid4()), "message_id": message, **over}


def test_a_contributor_saves_an_answer_to_the_case_once_and_may_undo_it(office):
    """Saving an answer is a contributor's right; it becomes a document with origin answer, never a source,
    logged; saving the same answer again gives the same document; the one who saved it may delete it
    (*Undo*), another contributor may not."""
    c, kc, _, _, docs = office
    alice, bob, carla = as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    assert c.post(f"/v1/cases/{cid}/documents", json=saved(), headers=carla).status_code == 403  # a reader
    r = c.post(f"/v1/cases/{cid}/documents", json=saved(), headers=bob)
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["filename"] == "What is the price.docx"
    did = r.json()["id"]
    again = c.post(f"/v1/cases/{cid}/documents", json=saved(), headers=bob)
    assert again.status_code == 200 and again.json() == {"id": did, "filename": "What is the price.docx", "created": False}
    listed = {d["id"]: d for d in c.get(f"/v1/documents?case={cid}", headers=carla).json()["documents"]}
    assert listed[did]["origin"] == "answer" and listed[did]["source"] is False and listed[did]["uploaded_by"] == BOB
    assert "content" not in listed[did]  # not in the lists; read one at a time
    assert docs.provenances[did]["message"] == "m-1"
    got = c.get(f"/v1/documents/{did}/content?case={cid}", headers=carla)  # a reader may download it
    assert got.status_code == 200 and got.json()["content"]["answer"] == "The price is EUR 300,000 [1]."
    assert c.get(f"/v1/documents/{did}/content", headers=carla).status_code == 404  # not in her personal space
    assert c.get(f"/v1/documents/{DOC}/content", headers=alice).status_code == 404  # an upload: nothing to rebuild
    ask = {"messages": [{"role": "user", "content": "What is the price?"}], "document_ids": [did], "case_id": cid}
    assert c.post("/v1/chat", json=ask, headers=bob).status_code == 404  # never a source (cases.md decision 7)
    assert c.get(f"/v1/cases/{cid}/events", headers=alice).json()[0]["action"] == "answer_saved"
    other = c.post(f"/v1/cases/{cid}/documents", json=saved(message="m-2"), headers=alice).json()["id"]
    assert c.delete(f"/v1/documents/{other}?case={cid}", headers=bob).status_code == 403  # Alice's
    assert c.delete(f"/v1/documents/{did}?case={cid}", headers=bob).status_code == 204    # his own: Undo


@pytest.mark.parametrize("change, status", [
    ({"filename": "../../etc/passwd.docx"}, 422), ({"filename": "answer.pdf"}, 422), ({"text": ""}, 422),
    ({"conversation_id": "x"}, 422), ({"content": {"answer": "no question"}}, 422),
])
def test_a_saved_answer_is_checked(office, change, status):
    c, kc, _, _, _ = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    assert c.post(f"/v1/cases/{cid}/documents", json=saved(**change), headers=alice).status_code == status


def test_a_closed_case_takes_no_saved_answer(office):
    c, kc, cases, _, _ = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    cases.close_case(uuid.UUID(cid))
    r = c.post(f"/v1/cases/{cid}/documents", json=saved(), headers=alice)
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    assert c.post(f"/v1/cases/{uuid.uuid4()}/documents", json=saved(), headers=alice).status_code == 404


def test_a_reader_pins_a_case_in_their_own_sidebar(office):
    """docs/design/chat-ui.md: per user, anyone who may read the case, not logged."""
    c, kc, cases, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    r = c.put(f"/v1/cases/{cid}/pin", json={"pinned": True}, headers=bob)
    assert r.status_code == 200 and r.json()["pinned"] is True
    assert [x["pinned"] for x in c.get("/v1/cases", headers=bob).json()] == [True]
    assert [x["pinned"] for x in c.get("/v1/cases", headers=alice).json()] == [False]  # someone else's pin
    assert c.put(f"/v1/cases/{cid}/pin", json={"pinned": False}, headers=bob).json()["pinned"] is False
    assert c.put(f"/v1/cases/{cid}/pin", json={"pinned": True}, headers=as_user(kc, CARLA)).status_code == 404  # not hers to see
    assert "pinned" not in [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]


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


def test_the_cases_overview_has_members_and_the_last_activity(office):
    """docs/design/chat-ui.md §4: open and closed cases, each with its members (the manager first) and who did
    something last; an administrator who isn't a member sees only that the case exists."""
    c, kc, cases, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    closed = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=alice).json()["id"]
    cases.close_case(uuid.UUID(closed))
    c.get(f"/v1/cases/{cid}", headers=bob)  # Bob opens it: the last activity
    rows = {x["id"]: x for x in c.get("/v1/cases/overview", headers=alice).json()}
    assert set(rows) == {cid, closed}  # closed ones too
    assert [(m["user"], m["role"]) for m in rows[cid]["members"]] == [(ALICE, "manager"), (BOB, "contributor")]
    assert rows[cid]["last_activity_by"] == "Bob Janssens" and rows[cid]["last_activity_at"]
    assert rows[closed]["state"] == "closed"
    admin = {x["id"]: x for x in c.get("/v1/cases/overview", headers=admin_headers(kc)).json()}
    assert admin[cid]["my_role"] is None and admin[cid]["members"] == [] and admin[cid]["last_activity_by"] == ""


def test_a_colleagues_shared_conversation_is_in_everyones_list_with_their_name(office):
    """§4: the Conversations overview lists the ones colleagues shared with a case the caller may read, with
    the colleague's name and the number of messages; unshared, it is theirs alone again."""
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    conv = str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    c.put(f"/v1/conversations/{conv}", json={"title": "Bob's", "turns": turns, "case_id": cid}, headers=bob)
    assert conv not in [x["id"] for x in c.get("/v1/conversations?all=true", headers=alice).json()]
    c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob)
    listed = {x["id"]: x for x in c.get("/v1/conversations?all=true", headers=alice).json()}
    assert listed[conv]["owner_name"] == "Bob Janssens" and listed[conv]["messages"] == 2 and listed[conv]["shared"]
    own = {x["id"]: x for x in c.get("/v1/conversations?all=true", headers=bob).json()}
    assert own[conv]["owner_name"] == ""  # his own: no name needed


def test_a_renamed_conversation_keeps_its_title_over_later_saves(office):
    """§4: the owner's title stays; saving the conversation again doesn't rename it after its first question."""
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    conv = str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    c.put(f"/v1/conversations/{conv}", json={"title": "Question", "turns": turns}, headers=alice)
    r = c.patch(f"/v1/conversations/{conv}", json={"title": "Sale, the price"}, headers=alice)
    assert r.status_code == 200 and r.json()["title"] == "Sale, the price"
    c.put(f"/v1/conversations/{conv}", json={"title": "Question", "turns": turns * 2}, headers=alice)
    assert c.get(f"/v1/conversations/{conv}", headers=alice).json()["title"] == "Sale, the price"
    assert c.patch(f"/v1/conversations/{conv}", json={"title": "Bob's"}, headers=bob).status_code == 404
    assert c.patch(f"/v1/conversations/{conv}", json={"title": " "}, headers=alice).status_code == 422


def test_a_personal_conversation_is_pinned_and_one_in_a_case_follows_its_case(office):
    """§3: a personal conversation can be pinned by its owner; one in a case can't (pin the case instead)."""
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    personal, in_case = str(uuid.uuid4()), str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    c.put(f"/v1/conversations/{personal}", json={"title": "Own", "turns": turns}, headers=alice)
    c.put(f"/v1/conversations/{in_case}", json={"title": "Case", "turns": turns, "case_id": cid}, headers=alice)
    r = c.put(f"/v1/conversations/{personal}/pin", json={"pinned": True}, headers=alice)
    assert r.status_code == 200 and r.json()["pinned"]
    assert c.get("/v1/conversations", headers=alice).json()[0]["pinned"]
    assert c.put(f"/v1/conversations/{in_case}/pin", json={"pinned": True}, headers=alice).status_code == 409
    assert c.put(f"/v1/conversations/{personal}/pin", json={"pinned": True}, headers=bob).status_code == 404
    assert not c.put(f"/v1/conversations/{personal}/pin", json={"pinned": False}, headers=alice).json()["pinned"]


def test_a_personal_conversation_moves_into_a_case_the_owner_contributes_to(office):
    """§4: moved, it isn't shared, loses its pin, follows the case and is in the case's access log; a reader,
    a closed case and a conversation already in a case are refused."""
    c, kc, cases, _, _ = office
    alice, bob, carla = as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    conv, carlas = str(uuid.uuid4()), str(uuid.uuid4())
    c.put(f"/v1/conversations/{conv}", json={"title": "Bob's", "turns": turns}, headers=bob)
    c.put(f"/v1/conversations/{conv}/pin", json={"pinned": True}, headers=bob)
    r = c.post(f"/v1/conversations/{conv}/move", json={"case_id": cid}, headers=bob)
    assert r.status_code == 200
    moved = r.json()
    assert moved["case_id"] == cid and not moved["shared"] and not moved["pinned"]
    assert c.get("/v1/conversations", headers=bob).json() == []  # no longer in his own space
    assert [x["id"] for x in c.get(f"/v1/conversations?case={cid}", headers=bob).json()] == [conv]
    assert c.get(f"/v1/conversations/{conv}", headers=bob).json()["turns"] == turns  # its questions came along
    events = c.get(f"/v1/cases/{cid}/events", headers=alice).json()
    assert (events[0]["user"], events[0]["action"], events[0]["detail"]) == (BOB, "conversation_moved_in", {"conversation": conv})
    assert c.post(f"/v1/conversations/{conv}/move", json={"case_id": cid}, headers=bob).status_code == 409
    # a reader can't move one in
    c.put(f"/v1/conversations/{carlas}", json={"title": "Carla's", "turns": turns}, headers=carla)
    assert c.post(f"/v1/conversations/{carlas}/move", json={"case_id": cid}, headers=carla).status_code == 403
    # nor anyone into a closed case, or into a case they can't see, or someone else's conversation
    other = str(uuid.uuid4())
    c.put(f"/v1/conversations/{other}", json={"title": "Alice's", "turns": turns}, headers=alice)
    assert c.post(f"/v1/conversations/{other}/move", json={"case_id": cid}, headers=bob).status_code == 404
    assert c.post(f"/v1/conversations/{other}/move", json={"case_id": str(uuid.uuid4())}, headers=alice).status_code == 404
    cases.close_case(uuid.UUID(cid))
    assert c.post(f"/v1/conversations/{other}/move", json={"case_id": cid}, headers=alice).status_code == 403
    assert c.get("/v1/conversations", headers=alice).json()[0]["case_id"] is None


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


def test_a_case_isnt_deleted_while_a_store_it_is_in_cant_be_reached(office):
    """Audit of 21 October 2026, finding 3: before, the case went and its conversations stayed."""
    from suveryn_api_gateway.routes.common import Database

    c, kc, cases, history, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    c.put(f"/v1/conversations/{uuid.uuid4()}", json={"title": "Case", "turns": turns, "case_id": cid}, headers=alice)

    def unreachable():
        raise OSError("no database")

    c.app.state.history = Database("conversations", connect=unreachable)
    assert c.delete(f"/v1/cases/{cid}", headers=alice).status_code == 503
    assert in_case in docs.docs and uuid.UUID(cid) in cases.cases  # nothing deleted
    c.app.state.history = Database("conversations", store=history)
    assert c.delete(f"/v1/cases/{cid}", headers=alice).status_code == 204
    assert in_case not in docs.docs and not any(r["case_id"] for r in history.rows.values())


def test_the_sweep_purges_old_access_log_lines_without_anyone_opening_the_log(office):
    """Audit of 21 October 2026, finding 4: the 180 days held only when someone opened an access log."""
    import time

    _, _, cases, _, _ = office
    for _ in range(50):  # the sweep's first round runs when the app starts
        if cases.purged:
            break
        time.sleep(0.05)
    assert cases.purged >= 1


def test_a_closed_case_refuses_uploads_and_questions(office):
    c, kc, cases, _, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    cases.close_case(uuid.UUID(cid))
    assert c.get(f"/v1/documents?case={cid}", headers=alice).status_code == 200  # reading stays
    assert c.get("/v1/cases", headers=alice).json() == [] and len(c.get("/v1/cases?closed=true", headers=alice).json()) == 1
    r = c.post(f"/v1/documents?case={cid}", files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}, headers=alice)
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    assert c.delete(f"/v1/documents/{in_case}?case={cid}", headers=alice).status_code == 403
    assert c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=alice).status_code == 403


# ------------------------------------------------------------------ stage 3: closing and the keep period
def test_the_manager_closes_a_case_and_it_is_kept_for_the_offices_period(office):
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    assert c.post(f"/v1/cases/{cid}/close", headers=bob).status_code == 403  # a contributor can't
    r = c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert r.status_code == 200 and r.json()["state"] == "closed" and r.json()["my_role"] == "manager"
    until = datetime.fromisoformat(r.json()["keep_until"])
    assert timedelta(days=182) < until - datetime.now(UTC) < timedelta(days=184)  # 6 months, the office's period
    assert c.post(f"/v1/cases/{cid}/close", headers=alice).status_code == 403  # closed: read-only, also for closing
    # read-only for everyone: no uploads, questions or changes; reading and the list (behind the filter) stay
    pdf = {"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=alice).status_code == 403
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 403
    assert c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=alice).status_code == 403
    assert c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice).status_code == 403
    assert c.get(f"/v1/documents?case={cid}", headers=bob).status_code == 200
    assert c.get("/v1/cases", headers=alice).json() == []
    assert [x["state"] for x in c.get("/v1/cases?closed=true", headers=alice).json()] == ["closed"]
    # the manager reopens it: open again, nothing planned
    assert c.post(f"/v1/cases/{cid}/reopen", headers=bob).status_code == 403
    r = c.post(f"/v1/cases/{cid}/reopen", headers=alice)
    assert r.status_code == 200 and r.json()["state"] == "open" and r.json()["keep_until"] is None
    assert c.post(f"/v1/cases/{cid}/reopen", headers=alice).status_code == 403  # not closed: reopen isn't a right
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 202
    events = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert events[:3] == ["uploaded", "reopened", "closed"]


def test_a_closed_case_due_for_deletion_can_be_extended_kept_or_reopened(office):
    c, kc, cases, _, _ = office
    alice, bob, admin = as_user(kc, ALICE), as_user(kc, BOB), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert c.post(f"/v1/cases/{cid}/keep", json={"keep": True}, headers=bob).status_code == 404  # not visible to Bob
    # a case whose deletion is three weeks away
    cases.cases[uuid.UUID(cid)] = cases.cases[uuid.UUID(cid)].model_copy(update={"keep_until": datetime.now(UTC) + timedelta(days=21)})
    # extend: one period later; keep: never deleted; keep false: one period from now
    r = c.post(f"/v1/cases/{cid}/keep", json={"extend": True}, headers=alice)
    until = datetime.fromisoformat(r.json()["keep_until"])
    assert timedelta(days=203) < until - datetime.now(UTC) < timedelta(days=205)
    r = c.post(f"/v1/cases/{cid}/keep", json={"keep": True}, headers=admin)
    assert r.status_code == 200 and r.json()["keep"] is True
    r = c.post(f"/v1/cases/{cid}/keep", json={"keep": False}, headers=alice)
    assert r.json()["keep"] is False and timedelta(days=182) < datetime.fromisoformat(r.json()["keep_until"]) - datetime.now(UTC)
    assert c.post(f"/v1/cases/{cid}/keep", json={}, headers=alice).status_code == 422
    c.post(f"/v1/cases/{cid}/reopen", headers=alice)
    assert c.post(f"/v1/cases/{cid}/keep", json={"keep": True}, headers=alice).status_code == 403  # open: close it first


def test_the_sweep_deletes_a_case_whose_period_has_passed_with_everything_in_it(office):
    c, kc, cases, history, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    turns = [{"role": "user", "text": "Vraag"}, {"role": "assistant", "text": "Antwoord"}]
    c.put(f"/v1/conversations/{uuid.uuid4()}", json={"title": "Dossier", "turns": turns, "case_id": cid}, headers=alice)
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    kept = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=alice).json()["id"]
    c.post(f"/v1/cases/{kept}/close", headers=alice)
    c.post(f"/v1/cases/{kept}/keep", json={"keep": True}, headers=alice)
    for x in (cid, kept):  # both past their period
        cases.cases[uuid.UUID(x)] = cases.cases[uuid.UUID(x)].model_copy(update={"keep_until": datetime.now(UTC) - timedelta(days=1)})
    assert cases.due_for_deletion() == [uuid.UUID(cid)]  # the kept one isn't
    import asyncio
    assert asyncio.run(_delete_case_everywhere(c.app, uuid.UUID(cid)))
    assert c.get(f"/v1/cases/{cid}", headers=alice).status_code == 404
    assert in_case not in docs.docs and DOC in docs.docs
    assert not any(r["case_id"] == uuid.UUID(cid) for r in history.rows.values())
    assert c.get(f"/v1/cases/{kept}", headers=alice).status_code == 200
    assert not asyncio.run(_delete_case_everywhere(c.app, uuid.uuid4()))


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
        "added_at": c.get(f"/v1/cases/{cid}/members", headers=alice).json()[0]["added_at"], "admin": False, "avatar": None}
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
    # pins (docs/design/chat-ui.md): per user, in the list and the single case
    assert not s.list(alice, office_wide=False)[0].pinned
    s.set_pinned(uuid.UUID(c.id), alice, True)
    assert s.list(alice, office_wide=False)[0].pinned and s.get(uuid.UUID(c.id), alice).pinned
    assert not s.list(bob, office_wide=True)[0].pinned  # someone else's pin
    s.set_pinned(uuid.UUID(c.id), alice, False)
    assert not s.get(uuid.UUID(c.id), alice).pinned
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


def test_store_keeps_the_strictly_confidential_label(store):
    """§11 against PostgreSQL: the label restricts the access, the access can't be opened while it is on."""
    from suveryn_api_gateway.cases import StrictlyConfidential

    s, alice, bob = store, f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"
    c = s.create(CaseIn(**NEW), alice)
    cid = uuid.UUID(c.id)
    assert c.confidential is False and s.confidential_ids([cid]) == set()
    on = s.update(cid, CaseUpdate(confidential=True))
    assert on.confidential and on.access == "restricted" and s.get(cid, alice).confidential
    assert s.confidential_ids([cid, uuid.uuid4()]) == {c.id} and s.confidential_ids([]) == set()
    assert [x.id for x in s.list(bob, office_wide=True) if x.id == c.id] == []  # members only
    with pytest.raises(StrictlyConfidential):
        s.update(cid, CaseUpdate(access="default"))
    off = s.update(cid, CaseUpdate(confidential=False, access="default"))
    assert not off.confidential and off.access == "default"


def test_two_managers_at_once_cant_open_a_case_that_became_strictly_confidential(store):
    """External review, pass 6: the access was checked with a read before the UPDATE, so a label set in
    between was missed. Now the UPDATE itself refuses: it waits for the other change, then sees the label."""
    import threading

    import psycopg
    from suveryn_api_gateway.cases import StrictlyConfidential

    s, alice = store, f"alice-{uuid.uuid4()}"
    cid = uuid.UUID(s.create(CaseIn(**NEW), alice).id)
    other = psycopg.connect(URL)  # the other manager's request, with its own connection
    other.execute("UPDATE cases SET confidential = true, access = 'restricted' WHERE id = %s", (cid,))  # not committed yet
    outcome = {}

    def opening():
        try:
            outcome["case"] = s.update(cid, CaseUpdate(access="default"))
        except StrictlyConfidential as e:
            outcome["refused"] = e

    t = threading.Thread(target=opening)
    t.start()
    t.join(0.5)
    assert t.is_alive()  # waiting for the other change to the row
    other.commit()
    t.join(5)
    other.close()
    assert "refused" in outcome
    after = s.get(cid, alice)
    assert after.confidential and after.access == "restricted"
    assert s.update(uuid.uuid4(), CaseUpdate(access="default")) is None  # an unknown case is still None


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
    # the overviews read several cases at once
    other = uuid.UUID(s.create(CaseIn(**{**NEW, "reference": f"R-{uuid.uuid4().hex[:6]}"}), bob, "bob", "Bob Janssens").id)
    members = s.members_of([cid, other])
    assert [m.user for m in members[cid]] == [carla, alice] and [m.user for m in members[other]] == [bob]
    last = s.last_activity([cid, other])
    assert last[cid][1] == carla and last[other][1] == bob
    s.delete(other)
    assert events[0].detail == {"documents": ["x"]}
    s._execute("UPDATE case_events SET at = now() - interval '181 days' WHERE case_id = %s AND action = 'created'", (cid,))
    assert [e.action for e in s.events(cid)] == ["asked", "opened"]  # purged after 180 days
    assert s.delete(cid) and s.events(cid) == []  # the log goes with the case


def test_store_closes_keeps_extends_reopens_and_finds_what_is_due(store):
    s = store
    alice, bob = f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"
    c = s.create(CaseIn(**NEW), alice)
    cid = uuid.UUID(c.id)
    half_year = timedelta(days=183)
    assert s.set_keep(cid, True, False, half_year) is None  # not closed yet
    assert s.reopen_case(cid) is None
    closed = s.close_case(cid, half_year)
    assert closed.state == "closed" and closed.closed_at and not closed.keep
    # In UTC: two aware times in the same zone subtract by the wall clock, an hour off across a clock change
    assert half_year - timedelta(minutes=1) < closed.keep_until.astimezone(UTC) - closed.closed_at.astimezone(UTC) <= half_year
    assert s.close_case(cid, half_year) is None  # already closed
    assert s.due_for_deletion() == []  # not for months
    s._execute("UPDATE cases SET keep_until = now() + interval '10 days' WHERE id = %s", (cid,))
    assert s.due_for_deletion() == []  # coming, not due yet
    extended = s.set_keep(cid, None, True, half_year)  # one more period from the planned date
    assert timedelta(days=192) < extended.keep_until - datetime.now(UTC) <= timedelta(days=193)
    kept = s.set_keep(cid, True, False, half_year)
    assert kept.keep and kept.keep_until == extended.keep_until  # the date stays, it just isn't acted on
    s._execute("UPDATE cases SET keep_until = now() - interval '1 day' WHERE id = %s", (cid,))
    assert s.due_for_deletion() == []  # kept: never swept
    released = s.set_keep(cid, False, False, half_year)  # one period from now again
    assert not released.keep and released.keep_until > datetime.now(UTC) + timedelta(days=182)
    s._execute("UPDATE cases SET keep_until = now() - interval '1 day' WHERE id = %s", (cid,))
    assert s.due_for_deletion() == [cid]  # overdue
    manual = s.close_case(uuid.UUID(s.create(CaseIn(**{**NEW, "reference": "2026/0418"}), bob).id), None)
    assert manual.keep_until is None and s.due_for_deletion() == [cid]  # no period: deleted by hand only
    reopened = s.reopen_case(cid)
    assert reopened.state == "open" and reopened.closed_at is None and reopened.keep_until is None
    assert s.due_for_deletion() == []


def test_store_writes_of_several_statements_are_all_or_nothing(store, monkeypatch):
    """Review finding: a case without its manager (decision 6) must be impossible, even if the
    connection goes halfway through creating it."""
    s = store
    alice = f"alice-{uuid.uuid4()}"
    monkeypatch.setattr(s, "log", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the log failed")))
    with pytest.raises(RuntimeError):
        s.create(CaseIn(**NEW), alice)
    assert s._execute("SELECT count(*) FROM cases WHERE reference = %s", (NEW["reference"],)).fetchone()[0] == 0
    assert s._execute('SELECT count(*) FROM case_members WHERE "user" = %s', (alice,)).fetchone()[0] == 0
    monkeypatch.undo()
    c = s.create(CaseIn(**NEW), alice)  # the connection is usable again after the rollback
    assert s.role_of(uuid.UUID(c.id), alice) == "manager"


# ------------------------------------------------------------------ stage 4: shared conversations, the administrator's pages
def test_a_conversation_shared_with_the_case_is_read_only_for_the_other_members(office):
    c, kc, _, history, _ = office
    alice, bob, carla, admin = as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    conv = str(uuid.uuid4())
    body = {"title": "Wat is de koopprijs?", "case_id": cid,
            "turns": [{"role": "user", "text": "Wat is de koopprijs?"}, {"role": "assistant", "text": "€ 345.000 [1]"}]}
    assert c.put(f"/v1/conversations/{conv}", json=body, headers=alice).status_code == 204
    # private until shared: bob (a reader of the case) sees nothing, neither in the list nor by id
    assert c.get(f"/v1/conversations?case={cid}", headers=bob).json() == []
    assert c.get(f"/v1/conversations/{conv}", headers=bob).status_code == 404
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob).status_code == 404  # not his
    r = c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=alice)
    assert r.status_code == 200 and r.json()["shared"] and r.json()["owner"] == ALICE
    listed = c.get(f"/v1/conversations?case={cid}", headers=bob).json()
    assert [(x["id"], x["owner"], x["shared"]) for x in listed] == [(conv, ALICE, True)]
    assert c.get(f"/v1/conversations/{conv}", headers=bob).json()["turns"][1]["text"] == "€ 345.000 [1]"
    # read-only for bob: he can't save over it, share or unshare it, or delete it
    assert c.put(f"/v1/conversations/{conv}", json={**body, "title": "mine now"}, headers=bob).status_code == 404
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": False}, headers=bob).status_code == 404
    assert c.delete(f"/v1/conversations/{conv}", headers=bob).status_code == 404
    assert c.get(f"/v1/conversations/{conv}", headers=alice).json()["title"] == "Wat is de koopprijs?"
    # not for someone outside the case, nor for an administrator who isn't a member
    assert c.get(f"/v1/conversations/{conv}", headers=carla).status_code == 404
    assert c.get(f"/v1/conversations/{conv}", headers=admin).status_code == 404
    # unshared: gone from bob's list again; the log noted both
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": False}, headers=alice).json()["shared"] is False
    assert c.get(f"/v1/conversations?case={cid}", headers=bob).json() == []
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert actions[:2] == ["conversation_unshared", "conversation_shared"]
    # the sidebar's list: Alice's own, across her case and her personal space; Bob's shared one isn't hers
    mine = str(uuid.uuid4())
    c.put(f"/v1/conversations/{mine}", json={"title": "Persoonlijk", "turns": body["turns"]}, headers=alice)
    assert {x["id"] for x in c.get("/v1/conversations?all=true", headers=alice).json()} == {conv, mine}
    assert c.get("/v1/conversations?all=true", headers=bob).json() == []
    # a personal conversation can't be shared; nor can one in a closed case
    personal = str(uuid.uuid4())
    c.put(f"/v1/conversations/{personal}", json={**body, "case_id": None}, headers=alice)
    assert c.post(f"/v1/conversations/{personal}/share", json={"shared": True}, headers=alice).status_code == 404
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=alice).status_code == 403
    assert c.get(f"/v1/conversations/{conv}", headers=alice).status_code == 200  # reading stays


def test_deleting_a_cases_document_cleans_every_members_conversations(office):
    c, kc, _, history, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    doc = str(uuid.uuid4())
    docs.docs[doc] = (Scope.case(uuid.UUID(cid)), "uploaded")
    turns = [{"role": "user", "text": "?"}, {"role": "assistant", "text": "x [1]",
             "citations": [{"n": 1, "text": "De koopprijs bedraagt € 345.000.", "source": {"document_id": doc, "page": 3}}]}]
    bobs = str(uuid.uuid4())
    c.put(f"/v1/conversations/{bobs}", json={"title": "Bob's", "case_id": cid, "turns": turns}, headers=bob)
    # the manager is asked which conversations cite it: bob's too, since it is the case's document
    assert [x["owner"] for x in c.get(f"/v1/documents/{doc}/conversations?case={cid}", headers=alice).json()] == [BOB]
    assert c.get(f"/v1/documents/{doc}/conversations?case={cid}", headers=bob).status_code == 403  # a contributor can't delete
    assert c.delete(f"/v1/documents/{doc}?case={cid}", headers=alice).status_code == 204
    cleaned = c.get(f"/v1/conversations/{bobs}", headers=bob).json()["turns"][1]["citations"][0]
    assert cleaned["text"] == "" and cleaned["removed"] is True


def test_an_administrator_lists_every_case_and_changes_the_offices_settings(office):
    c, kc, cases, history, _ = office
    alice, bob, admin = as_user(kc, ALICE), as_user(kc, BOB), admin_headers(kc)
    assert c.get("/v1/admin/cases", headers=alice).status_code == 403
    assert c.get("/v1/admin/cases/settings", headers=alice).status_code == 403
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    other = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=bob).json()["id"]
    c.post(f"/v1/cases/{other}/close", headers=bob)
    listed = c.get("/v1/admin/cases", headers=admin).json()
    assert [(x["id"], x["state"], x["manager"], x["members"]) for x in listed] == [
        (cid, "open", ALICE, 2), (other, "closed", BOB, 1)]
    assert all(x["manager_name"] and x["manager_username"] for x in listed)  # the name as when the case was opened
    assert all("subject" not in x or x["subject"] == NEW["subject"] for x in listed)  # the case's label, nothing inside it
    # the settings: as provisioned (members, 6m) until changed here, then effective at once
    before = c.get("/v1/admin/cases/settings", headers=admin).json()
    assert before == {"default_access": "members", "keep": "6m", "conversations_keep": "manual", "two_step": False,
                      "updated_at": None, "updated_by": ""}
    assert c.put("/v1/admin/cases/settings", json={}, headers=admin).status_code == 422
    r = c.put("/v1/admin/cases/settings", json={"default_access": "office", "keep": "manual", "apply_to": "all"}, headers=admin)
    assert r.status_code == 200 and r.json()["default_access"] == "office" and r.json()["keep"] == "manual"
    # the conversations period (the data lifecycle, suveryn-tracker#31) reaches the conversation store at once
    r = c.put("/v1/admin/cases/settings", json={"conversations_keep": "1y"}, headers=admin)
    assert r.status_code == 200 and r.json()["conversations_keep"] == "1y" and r.json()["keep"] == "manual"
    assert history.keep == "1y" and history.purged[-1] == "1y"  # told and purged when saved (VM check of 28 October)
    assert c.get("/v1/conversations", headers=alice).status_code == 200
    assert r.json()["updated_by"] and r.json()["updated_at"]  # the administrator's name (round 4, finding 4), and when
    assert c.get(f"/v1/cases/{cid}", headers=as_user(kc, CARLA)).json()["my_role"] == "reader"  # office-wide now
    closed = c.post(f"/v1/cases/{cid}/close", headers=alice).json()
    assert closed["keep_until"] is None  # the new period applies to cases closed from now on
    assert c.put("/v1/admin/cases/settings", json={"keep": "2y"}, headers=admin).status_code == 422


def test_opening_the_office_applies_to_new_cases_or_by_choice_to_all_but_never_strictly_confidential_ones(office):
    """Administration › Settings (docs/design/admin.md, artboard 35): who sees a case, for new cases or all of them."""
    c, kc, cases, history, _ = office
    alice, carla, admin = as_user(kc, ALICE), as_user(kc, CARLA), admin_headers(kc)
    first = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    secret = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=alice).json()["id"]
    c.patch(f"/v1/cases/{secret}", json={"confidential": True}, headers=alice)
    preview = lambda q: c.get("/v1/admin/cases/settings/preview", params=q, headers=admin).json()  # noqa: E731
    assert c.get("/v1/admin/cases/settings/preview", headers=alice).status_code == 403
    assert preview({"default_access": "office", "apply_to": "new"})["cases_opened"] == 0
    assert preview({"default_access": "office", "apply_to": "all"})["cases_opened"] == 1  # the strictly confidential one never
    # new cases only: the existing one stays with its members, restricted, and its manager can open it
    c.put("/v1/admin/cases/settings", json={"default_access": "office"}, headers=admin)
    assert c.get(f"/v1/cases/{first}", headers=carla).status_code in (403, 404)
    assert cases.cases[uuid.UUID(first)].access == "restricted"
    later = c.post("/v1/cases", json={**NEW, "reference": "2026/0419"}, headers=alice).json()["id"]
    assert c.get(f"/v1/cases/{later}", headers=carla).json()["my_role"] == "reader"
    # back to members only: every case that follows the default, counted first
    assert preview({"default_access": "members"})["cases_closed"] == 1
    c.put("/v1/admin/cases/settings", json={"default_access": "members"}, headers=admin)
    assert c.get(f"/v1/cases/{later}", headers=carla).status_code in (403, 404)
    # all cases: the restricted one opens too, with a line in its access log; the strictly confidential one stays
    c.put("/v1/admin/cases/settings", json={"default_access": "office", "apply_to": "all"}, headers=admin)
    assert c.get(f"/v1/cases/{first}", headers=carla).json()["my_role"] == "reader"
    assert c.get(f"/v1/cases/{secret}", headers=carla).status_code in (403, 404)
    assert "access_changed" in [e["action"] for e in c.get(f"/v1/cases/{first}/events", headers=alice).json()]


def test_a_shorter_keep_period_for_conversations_is_counted_before_it_is_saved(office):
    c, kc, _, history, _ = office
    admin = admin_headers(kc)
    old, now = datetime.now(UTC) - timedelta(days=400), datetime.now(UTC)
    for at in (old, old, now):
        history.rows[uuid.uuid4()] = {"updated_at": at}
    preview = lambda keep: c.get("/v1/admin/cases/settings/preview", params={"conversations_keep": keep}, headers=admin).json()  # noqa: E731
    assert preview("1y")["conversations_deleted"] == 2 and preview("5y")["conversations_deleted"] == 0
    assert preview("manual")["conversations_deleted"] == 0
    c.put("/v1/admin/cases/settings", json={"conversations_keep": "1y"}, headers=admin)
    assert history.purged[-1] == "1y"  # deleted when saved, not at the next sweep (VM check of 28 October, finding 4)
    assert preview("5y")["conversations_deleted"] == 0  # longer: nothing goes


def test_store_opens_or_keeps_the_existing_cases_with_the_setting_never_strictly_confidential_ones(store):
    s, alice = store, f"alice-{uuid.uuid4()}"
    first = s.create(CaseIn(**NEW), alice)
    secret = s.create(CaseIn(**{**NEW, "reference": "2026/0418"}), alice)
    s.update(uuid.UUID(secret.id), CaseUpdate(confidential=True))
    before = s.access_counts()
    s.set_overrides({"default_access": "office"}, "admin", keep_existing=True)
    assert s.get(uuid.UUID(first.id), alice).access == "restricted" and s.access_counts()["default"] == 0
    s.set_overrides({"default_access": "office"}, "admin", open_all=True, by_user="admin-sub")
    assert s.get(uuid.UUID(first.id), alice).access == "default"
    assert s.get(uuid.UUID(secret.id), alice).access == "restricted"  # their members decide
    assert s.access_counts()["default"] == before["default"] + before["restricted"]
    assert [(e.action, e.user) for e in s.events(uuid.UUID(first.id))][0] == ("access_changed", "admin-sub")
    s.set_overrides({"default_access": "members"}, "admin")


def test_store_lists_every_case_for_the_administrator_and_keeps_the_offices_settings(store):
    s = store
    alice, bob = f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"
    c = s.create(CaseIn(**NEW), alice, "alice", "Alice Peeters")
    s.set_member(uuid.UUID(c.id), bob, "reader", alice, "bob", "Bob Janssens")
    other = s.create(CaseIn(**{**NEW, "reference": "2026/0418"}), bob, "bob", "Bob Janssens")
    s.close_case(uuid.UUID(other.id), None)
    mine = [x for x in s.list_all("admin-sub") if x.id in (c.id, other.id)]
    assert [(x.id, x.state, x.manager_name, x.manager_username, x.members) for x in mine] == [
        (c.id, "open", "Alice Peeters", "alice", 2), (other.id, "closed", "Bob Janssens", "bob", 1)]
    # the settings: nothing chosen until an administrator does; then kept, and merged over the environment's
    s._execute("DELETE FROM case_settings")
    s._overrides = None
    assert s.overrides() == {} and s.overrides_meta() is None
    assert s.set_overrides({"keep": "1y"}, "admin") == {"keep": "1y"}
    assert s.set_overrides({"default_access": "office"}, "admin") == {"keep": "1y", "default_access": "office"}
    assert s.overrides_meta()[1] == "admin"
    with pytest.raises(ValueError):
        s.set_overrides({"colour": "teal"}, "admin")
    merged = CaseSettings(database_url=URL, default_access="members", keep="6m").with_overrides(s.overrides())
    assert merged.office_wide and merged.keep == "1y"
    assert CaseSettings(keep="6m").with_overrides({"keep": "2y", "default_access": "everyone"}).keep == "6m"  # bad rows are ignored
    assert CaseSettings().with_overrides({"conversations_keep": "5y"}).conversations_keep == "5y"
    assert CaseSettings().with_overrides({"conversations_keep": "2y"}).conversations_keep == "manual"
    fresh = CaseStore(CaseSettings(database_url=URL))  # another store reads what was chosen
    try:
        assert fresh.overrides() == {"keep": "1y", "default_access": "office"}
    finally:
        fresh.close()
        s._execute("DELETE FROM case_settings")


def test_a_strictly_confidential_case_is_for_its_members_with_no_sharing_and_shielded_titles(office):
    """docs/design/chat-ui.md §11: the manager turns the label on; access becomes members only and
    can't be opened, shared conversations are unshared (their owners keep them), sharing is refused,
    the lists that span cases show no title, and the access log says so."""
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    conv = str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    c.put(f"/v1/conversations/{conv}", json={"title": "Bob's question", "turns": turns, "case_id": cid}, headers=bob)
    c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob)

    assert c.patch(f"/v1/cases/{cid}", json={"confidential": True}, headers=bob).status_code == 403  # the manager only
    c.put(f"/v1/cases/{cid}/pin", json={"pinned": True}, headers=alice)
    r = c.patch(f"/v1/cases/{cid}", json={"confidential": True}, headers=alice)
    assert r.status_code == 200 and r.json()["confidential"] is True and r.json()["access"] == "restricted"
    assert r.json()["pinned"] is True  # the answer keeps the caller's pin: the sidebar doesn't drop the case
    assert c.patch(f"/v1/cases/{cid}", json={"access": "default"}, headers=alice).status_code == 409
    # unshared, still Bob's; and he can't share it again
    assert c.get(f"/v1/conversations?case={cid}", headers=alice).json() == []
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob).status_code == 409
    # the lists that span cases: no title; the case's own list keeps it
    [listed] = [x for x in c.get("/v1/conversations?all=true", headers=bob).json() if x["id"] == conv]
    assert listed["title"] is None and listed["shielded"] is True and listed["case_id"] == cid
    assert c.get(f"/v1/conversations?case={cid}", headers=bob).json()[0]["title"] == "Bob's question"
    events = c.get(f"/v1/cases/{cid}/events", headers=alice).json()
    on = next(e for e in events if e["action"] == "confidential_on")
    assert on["detail"] == {"unshared": 1}
    assert any(e["action"] == "access_changed" and e["detail"] == {"access": "restricted"} for e in events)
    # off again: titles return, sharing works, the access stays as it was until changed
    r = c.patch(f"/v1/cases/{cid}", json={"confidential": False}, headers=alice)
    assert r.json()["confidential"] is False and r.json()["access"] == "restricted"
    assert c.get(f"/v1/cases/{cid}/events", headers=alice).json()[0]["action"] == "confidential_off"
    [listed] = [x for x in c.get("/v1/conversations?all=true", headers=bob).json() if x["id"] == conv]
    assert listed["title"] == "Bob's question" and listed["shielded"] is False
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob).status_code == 200
    # turning it off and opening the access in one change is allowed
    c.patch(f"/v1/cases/{cid}", json={"confidential": True}, headers=alice)
    assert c.patch(f"/v1/cases/{cid}", json={"confidential": False, "access": "default"}, headers=alice).json()["access"] == "default"


def test_a_case_can_be_strictly_confidential_from_the_start(office):
    """VM check of 28 October, finding 14: POST /v1/cases ignored "confidential"."""
    c, kc, _, _, _ = office
    r = c.post("/v1/cases", json={**NEW, "confidential": True}, headers=as_user(kc, ALICE))
    assert r.status_code == 201 and r.json()["confidential"] is True and r.json()["access"] == "restricted"


def test_store_keeps_a_deleted_accounts_name_with_what_it_did(store):
    """Administration › Users, deleting an account (Filip, 29 October): out of its cases, its name kept."""
    s, alice, bob = store, f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"
    c = s.create(CaseIn(**NEW), alice, "alice", "Alice")
    cid = uuid.UUID(c.id)
    s.set_member(cid, bob, "contributor", alice, "bob", "Bob Peeters")
    s.log(cid, bob, "uploaded", {})
    s.set_pinned(cid, bob, True)
    assert s.depart(bob, "bob", "Bob Peeters", alice) == 1
    assert s.role_of(cid, bob) is None
    assert s._execute('SELECT 1 FROM case_pins WHERE case_id = %s AND "user" = %s', (cid, bob)).fetchone() is None
    assert s.departed_names([bob]) == {bob: "Bob Peeters"} and bob in s.departed_names()
    names = {(e.user, e.action): e.name for e in s.events(cid)}
    assert names[(bob, "uploaded")] == "Bob Peeters" and names[(alice, "member_removed")] == "Alice"
    s._execute("DELETE FROM departed_accounts WHERE sub = %s", (bob,))


def test_the_sign_in_check_needs_keycloaks_database(monkeypatch):
    """Round 2: Keycloak serves its discovery document while its database is down, and then every
    sign-in fails. Directory.working asks for the number of accounts with the service account's
    token, which needs the database; /health and Status say sign-in is unavailable meanwhile, and
    ready again once it is back. A read, so Keycloak logs no event for it."""
    import asyncio

    import suveryn_api_gateway.directory as directory_module
    from suveryn_api_gateway.directory import Directory, DirectorySettings, DirectoryUnavailable
    from suveryn_api_gateway.routes.common import signin_status

    db = {"up": True}
    asked = []

    def keycloak(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if not db["up"]:
            return httpx.Response(500, text="Internal Server Error")  # what Keycloak 26.8 answered
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "svc-token", "expires_in": 300})
        if request.url.path == "/admin/realms/suveryn/users/count":
            assert request.url.params["enabled"] == "true"
            return httpx.Response(200, json=3)
        return httpx.Response(404)

    clock = [100.0]
    monkeypatch.setattr(directory_module.time, "monotonic", lambda: clock[0])
    d = Directory(DirectorySettings(issuer="http://keycloak.test/realms/suveryn", client_secret="d1r"),
                  transport=httpx.MockTransport(keycloak))

    class Auth:
        async def status(self):
            return "ready", None  # the discovery document answers, as it did

    class State:
        auth, directory = Auth(), d

    async def run():
        assert await signin_status(State()) == ("ready", None)
        db["up"] = False
        assert await signin_status(State()) == ("ready", None)  # within the TTL: the last answer stands
        clock[0] += directory_module.WORKING_TTL_S
        state, why = await signin_status(State())
        assert state == "unavailable" and "500" in why
        with pytest.raises(DirectoryUnavailable):
            await d.working()
        db["up"] = True
        clock[0] += directory_module.WORKING_TTL_S
        assert await signin_status(State()) == ("ready", None)
        assert asked.count("/realms/suveryn/protocol/openid-connect/token") == 1  # the token kept, not a sign-in a minute
        await d.aclose()

    asyncio.run(run())


def test_an_administrator_outside_a_strictly_confidential_case_sees_its_number_only(office):
    """Filip, 29 October (external review, pass 7, item 9): an administrator who isn't a member sees that a
    strictly confidential case exists, by its reference, with its manager, to hand it over or close it; never
    its name or subject. Every other case, and for its members, as before."""
    c, kc, cases, _, _ = office
    alice, admin = as_user(kc, ALICE), admin_headers(kc)
    secret = c.post("/v1/cases", json={**NEW, "confidential": True}, headers=alice).json()["id"]
    plain = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=alice).json()["id"]
    assert c.get("/v1/cases", headers=alice).json()[0]["name"] == "Verkoop Kerkstraat 12"  # the member: all of it

    def by_id(rows):
        return {r["id"]: r for r in rows}

    for rows in (c.get("/v1/cases", headers=admin).json(), c.get("/v1/cases/overview", headers=admin).json(),
                 c.get("/v1/admin/cases", headers=admin).json()):
        seen = by_id(rows)
        assert seen[secret]["reference"] == "2026/0417" and seen[secret]["name"] == "" and seen[secret]["subject"] == {}
        assert seen[plain]["name"] == "Verkoop Kerkstraat 12"  # not strictly confidential: as before
    assert by_id(c.get("/v1/admin/cases", headers=admin).json())[secret]["manager_name"]  # who manages it, to hand over
    # handed over by the administrator, the answer still holds no name
    handed = c.post(f"/v1/cases/{secret}/handover", json={"user": BOB}, headers=admin).json()
    assert handed["reference"] == "2026/0417" and handed["name"] == "" and handed["subject"] == {}


def test_store_shows_a_strictly_confidential_case_by_its_number_outside_it(store):
    """The real store's lists: an administrator outside a strictly confidential case gets its reference,
    no name and no subject (list, list_all); its member gets all of it."""
    s = store
    alice, admin = f"alice-{uuid.uuid4()}", f"admin-{uuid.uuid4()}"
    c = s.create(CaseIn(**{**NEW, "reference": f"S-{uuid.uuid4().hex[:8]}", "confidential": True}), alice, "alice", "Alice")
    outside = next(x for x in s.list(admin, office_wide=False, admin=True) if x.id == c.id)
    assert (outside.name, outside.subject, outside.my_role) == ("", {}, None) and outside.reference == c.reference
    assert next(x for x in s.list_all(admin) if x.id == c.id).name == ""
    assert next(x for x in s.list_all(alice) if x.id == c.id).name == NEW["name"]
    assert next(x for x in s.list(alice, office_wide=False) if x.id == c.id).subject == NEW["subject"]


def test_a_due_case_left_while_documents_start_is_deleted_minutes_later_not_an_hour(monkeypatch):
    """VM regression of 29 October, finding 4: at start the sweep ran while documents were still starting, the
    due case was left, and the sweep slept an hour. A due case left for a store not reachable yet is looked at
    again within SWEEP_RETRY_S."""
    import time

    import suveryn_api_gateway.app as app_module

    monkeypatch.setattr(app_module, "SWEEP_RETRY_S", 0.05)
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(state="starting", owner=ALICE)
    store_case = cases.create(CaseIn(**NEW), ALICE, "alice", "Alice")
    cid = uuid.UUID(store_case.id)
    cases.cases[cid] = cases.cases[cid].model_copy(update={"state": "closed", "keep_until": datetime.now(UTC) - timedelta(days=1)})
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app):
        time.sleep(0.2)
        assert cid in cases.cases  # documents still starting: left
        docs.state = "ready"
        for _ in range(100):
            if cid not in cases.cases:
                break
            time.sleep(0.05)
        assert cid not in cases.cases  # deleted at the retry, not an hour later


def test_an_administrators_action_in_a_case_they_arent_in_carries_their_name(office):
    """VM regression of 29 October, finding 9: Alice's handover from Administration showed in the access log
    with no name (she isn't a member); the name comes from the directory."""
    c, kc, cases, _, _ = office
    alice, admin = as_user(kc, ALICE), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    assert c.post(f"/v1/cases/{cid}/handover", json={"user": BOB}, headers=admin).status_code == 200
    events = c.get(f"/v1/cases/{cid}/events", headers=admin).json()
    handed = next(e for e in events if e["action"] == "handed_over")
    assert handed["user"] == ADMIN and handed["name"] == "The Administrator"


def test_administration_refuses_someone_else_before_reading_the_body(office):
    """VM regression of 29 October, finding 11: a non-administrator with a malformed body got 422 from 7
    administration endpoints (the body was checked first); it is 403 everywhere now."""
    c, kc, _, _, _ = office
    bob = as_user(kc, BOB)
    for method, path in (("PUT", "/v1/admin/cases/settings"), ("POST", "/v1/admin/users"), ("PUT", "/v1/admin/playbooks"),
                         ("POST", "/v1/admin/backups/requests"), ("PUT", "/v1/admin/usage/rates")):
        r = c.request(method, path, content=b"{not json", headers={**bob, "Content-Type": "application/json"})
        assert r.status_code == 403, (method, path, r.status_code)
