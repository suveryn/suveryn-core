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
from suveryn_rag.store import Original, Scope
from conftest import FakeConversations, kept
from conftest import ask as asked
from test_auth import SETTINGS, FakeKeycloak
from test_conversations import as_user
from test_documents import DOC, FakeDocuments, llm_transport

ALICE, BOB, CARLA, ADMIN = "alice-sub", "bob-sub", "carla-sub", "admin-sub"
PEOPLE = [Person(sub=ALICE, username="alice", name="Alice Peeters"), Person(sub=BOB, username="bob", name="Bob Janssens"),
          Person(sub=CARLA, username="carla", name="Carla Maes"), Person(sub=ADMIN, username="admin", name="The Administrator")]
NEW = {"reference": "2026/0417", "name": "Verkoop Kerkstraat 12", "type": "sale"}


# ------------------------------------------------------------------ the rules
def case(state="open", access="default", manager=ALICE) -> Case:
    now = datetime.now(UTC)
    return Case(id=str(uuid.uuid4()), reference="2026/0417", name="Verkoop", type="sale", access=access,
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
    assert "subject" not in c.get(f"/v1/cases/{made['id']}", headers=alice).json()
    # members only: Bob doesn't see it, and it is "unknown" to him, not "forbidden"
    assert c.get("/v1/cases", headers=bob).json() == []
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{made['id']}", headers=bob)) == (404, "case.not_found")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{uuid.uuid4()}", headers=alice)) == (404, "case.not_found")
    assert c.get("/v1/cases/not-an-id", headers=alice).status_code == 422
    # the office's file numbers are unique: the same reference again is refused, whoever asks
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post("/v1/cases", json={**NEW, "reference": "2026/0417"}, headers=bob)) == (409, "case.reference_exists")


def test_the_case_types_offered_come_from_core_and_the_installed_packs(office):
    """suveryn-tracker#229: the server knows which case types exist (core's reference content's, then the installed
    packs': here the test pack's), each with its words; signed in only."""
    c, kc, _, _, _ = office
    types = c.get("/v1/case-types", headers=as_user(kc, BOB)).json()
    assert [(t["id"], t["pack"]) for t in types][:2] == [("sale", "pack/be-notary"), ("company-formation", "pack/be-test")]
    assert types[0]["text"] == {"en": "Sale", "nl": "Verkoop", "fr": "Vente"}
    assert "estate" in [t["id"] for t in types]  # a type without a playbook is offered too
    assert c.get("/v1/case-types").status_code == 401


def test_a_case_type_the_appliance_doesnt_offer_is_refused_and_a_stored_one_is_kept(office):
    """suveryn-tracker#229: a new case or a change of type takes an offered type only; a case whose stored type is no
    longer offered (its pack is gone) keeps it, and its other fields still change."""
    c, kc, cases, _, _ = office
    alice = as_user(kc, ALICE)
    code = lambda r: (r.status_code, r.json().get("code"))  # noqa: E731
    assert code(c.post("/v1/cases", json={**NEW, "type": "gift"}, headers=alice)) == (422, "case.type_unsupported")
    made = c.post("/v1/cases", json={**NEW, "type": "estate"}, headers=alice).json()
    assert made["type"] == "estate"
    assert code(c.patch(f"/v1/cases/{made['id']}", json={"type": "marriage-contract"}, headers=alice)) == (422, "case.type_unsupported")
    assert c.patch(f"/v1/cases/{made['id']}", json={"type": "sale"}, headers=alice).json()["type"] == "sale"
    cid = uuid.UUID(made["id"])
    cases.cases[cid] = cases.cases[cid].model_copy(update={"type": "gift"})  # stored when a pack declared it
    r = c.patch(f"/v1/cases/{made['id']}", json={"name": "Schenking (deel 2)", "type": "gift"}, headers=alice)
    assert r.status_code == 200 and (r.json()["type"], r.json()["name"]) == ("gift", "Schenking (deel 2)")


def test_only_the_manager_changes_or_deletes_a_case(office):
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    r = c.patch(f"/v1/cases/{cid}", json={"name": "Verkoop Kerkstraat 12 (deel 2)", "access": "restricted"}, headers=alice)
    assert r.status_code == 200 and r.json()["access"] == "restricted" and r.json()["reference"] == "2026/0417"
    assert (lambda r: (r.status_code, r.json()["code"]))(c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=bob)) == (404, "case.not_found")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/cases/{cid}", headers=bob)) == (404, "case.not_found")
    assert c.delete(f"/v1/cases/{cid}", headers=alice).status_code == 204
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{cid}", headers=alice)) == (404, "case.not_found")


def test_an_administrator_sees_the_case_exists_but_not_what_is_in_it(office):
    c, kc, _, _, _ = office
    alice, admin = as_user(kc, ALICE), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    listed = c.get("/v1/cases", headers=admin).json()
    assert [x["id"] for x in listed] == [cid] and listed[0]["my_role"] is None and listed[0]["manager"] == ALICE
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{cid}", headers=admin)) == (403, "case.not_allowed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/documents?case={cid}", headers=admin)) == (403, "case.not_allowed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=admin)) == (403, "case.not_allowed")


def test_documents_in_a_case_are_separate_from_the_personal_space(office):
    c, kc, _, _, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    assert [d["id"] for d in c.get("/v1/documents", headers=alice).json()["documents"]] == [DOC]
    listed = c.get(f"/v1/documents?case={cid}", headers=alice).json()["documents"]
    assert [d["id"] for d in listed] == [in_case] and listed[0]["origin"] == "uploaded"
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/documents?case={uuid.uuid4()}", headers=alice)) == (404, "case.not_found")
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
    assert asked(c, ask, alice).status_code == 404  # not a source yet
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/documents/{back}/source?case={cid}", headers=bob)) == (403, "case.not_allowed")  # a reader can't decide
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
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/documents/{alices}?case={cid}", headers=bob)) == (403, "case.not_allowed")  # not his upload
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/documents/{plain}?case={cid}", headers=bob)) == (403, "case.not_allowed")   # nothing noticed: the manager's
    c.post(f"/v1/documents/{bobs}/source?case={cid}", headers=bob)
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/documents/{bobs}?case={cid}", headers=bob)) == (403, "case.not_allowed")    # confirmed: the manager's
    again = upload_by(BOB)
    assert c.delete(f"/v1/documents/{again}?case={cid}", headers=bob).status_code == 204


ANSWERED = [{"role": "user", "text": "What is the price?", "document_ids": [DOC], "about": [], "attached": [], "model": None,
             "thinking": False},
            {"role": "assistant", "text": "The price is EUR 300,000 [1].",
             "citations": [{"text": "The price is EUR 300,000.", "source": {"document_id": DOC, "page": 2, "location": None}}]}]


def answered_in(history, cid: str, owner: str) -> str:
    """A question asked in the case and its answer, as the server keeps them (suveryn-tracker#251): the conversation's id;
    the answer is turn 2."""
    conv = str(uuid.uuid4())
    assert kept(history, conv, owner, ANSWERED, case_id=cid)
    return conv


def test_a_contributor_saves_an_answer_to_the_case_once_and_may_undo_it(office):
    """Saving an answer is a contributor's right; it becomes a document with origin answer, never a source,
    logged; saving the same answer again gives the same document; the one who saved it may delete it
    (*Undo*), another contributor may not."""
    c, kc, _, history, docs = office
    alice, bob, carla = as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    carlas = answered_in(history, cid, CARLA)  # asked before she became a reader
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{carlas}/turns/2/document", headers=carla)) == (403, "case.not_allowed")
    bobs = answered_in(history, cid, BOB)
    r = c.post(f"/v1/conversations/{bobs}/turns/2/document", headers=bob)
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["filename"].endswith(".docx")
    did = r.json()["id"]
    again = c.post(f"/v1/conversations/{bobs}/turns/2/document", headers=bob)
    assert again.status_code == 200 and again.json() == {"id": did, "filename": r.json()["filename"], "created": False}
    listed = {d["id"]: d for d in c.get(f"/v1/documents?case={cid}", headers=carla).json()["documents"]}
    assert listed[did]["origin"] == "answer" and listed[did]["source"] is False and listed[did]["uploaded_by"] == BOB
    assert "content" not in listed[did]  # not in the lists; read one at a time
    assert docs.provenances[did]["message"] == f"{bobs}/2"
    got = c.get(f"/v1/documents/{did}/content?case={cid}", headers=carla)  # a reader may download it
    assert got.status_code == 200 and got.json()["content"]["answer"] == "The price is EUR 300,000 [1]."
    assert c.get(f"/v1/documents/{did}/content", headers=carla).status_code == 404  # not in her personal space
    assert c.get(f"/v1/documents/{DOC}/content", headers=alice).status_code == 404  # an upload: nothing to rebuild
    ask = {"messages": [{"role": "user", "content": "What is the price?"}], "document_ids": [did], "case_id": cid}
    assert asked(c, ask, bob).status_code == 404  # never a source (cases.md decision 7)
    assert c.get(f"/v1/cases/{cid}/events", headers=alice).json()[0]["action"] == "answer_saved"
    # the file a document was read from (board G11): a reader opens it, noted in the case's access log
    docs.originals = {did: ("Compromis.pdf", Original("application/pdf", b"%PDF-1.7 test"))}
    r = c.get(f"/v1/documents/{did}/original?case={cid}", headers=carla)
    assert r.status_code == 200 and r.content == b"%PDF-1.7 test"
    assert c.get(f"/v1/cases/{cid}/events", headers=alice).json()[0]["action"] == "document_opened"
    assert c.get(f"/v1/documents/{did}/original", headers=carla).status_code == 404  # not in her personal space
    other = c.post(f"/v1/conversations/{answered_in(history, cid, ALICE)}/turns/2/document", headers=alice).json()["id"]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/documents/{other}?case={cid}", headers=bob)) == (403, "case.not_allowed")  # Alice's
    assert c.delete(f"/v1/documents/{did}?case={cid}", headers=bob).status_code == 204    # his own: Undo


def test_a_closed_case_takes_no_saved_answer(office):
    c, kc, cases, history, _ = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    conv = answered_in(history, cid, ALICE)
    cases.close_case(uuid.UUID(cid))
    r = c.post(f"/v1/conversations/{conv}/turns/2/document", headers=alice)
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{uuid.uuid4()}/turns/2/document", headers=alice)) == (404, "request.not_found")


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
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(f"/v1/cases/{cid}/pin", json={"pinned": True}, headers=as_user(kc, CARLA))) == (404, "case.not_found")  # not hers to see
    assert "pinned" not in [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]


def test_an_upload_goes_into_the_case_and_its_job_is_listed_there(office):
    c, kc, _, _, docs = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    pdf = {"file": ("akte.pdf", b"%PDF-1.7 x", "application/pdf")}
    r = c.post(f"/v1/documents?case={cid}", files=pdf, headers=alice)
    assert r.status_code == 202 and docs.uploads == [("akte.pdf", ALICE, uuid.UUID(cid))]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob)) == (404, "case.not_found")  # not Bob's case
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
    assert asked(c, ask, alice).status_code == 200
    assert docs.seen["case_id"] == uuid.UUID(cid) and docs.seen["owner"] is None
    # a personal document can't be asked about in the case, nor a case document outside it
    assert asked(c, {**ask, "document_ids": [DOC]}, alice).status_code == 404
    assert asked(c, {**ask, "case_id": None}, alice).status_code == 404
    # sūveryn's own output is never a source (decision 7)
    assert asked(c, {**ask, "document_ids": [in_case, generated]}, alice).status_code == 404
    # and Bob can't ask in Alice's case at all
    assert (lambda r: (r.status_code, r.json()["code"]))(asked(c, ask, bob)) == (404, "case.not_found")
    assert asked(c, {**ask, "case_id": "nope"}, alice).status_code == 422


def test_conversations_are_listed_with_their_case(office):
    c, kc, _, history, _ = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    personal, in_case = str(uuid.uuid4()), str(uuid.uuid4())
    turns = [{"role": "user", "text": "Vraag"}, {"role": "assistant", "text": "Antwoord"}]
    assert kept(history, personal, ALICE, turns, "Los")
    assert kept(history, in_case, ALICE, turns, "Dossier", case_id=cid)
    assert [x["id"] for x in c.get("/v1/conversations", headers=alice).json()] == [personal]
    listed = c.get(f"/v1/conversations?case={cid}", headers=alice).json()
    assert [x["id"] for x in listed] == [in_case] and listed[0]["case_id"] == cid
    assert c.get(f"/v1/conversations/{in_case}", headers=alice).json()["case_id"] == cid


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
    c, kc, _, history, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    conv = str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    kept(history, conv, BOB, turns, "Bob's", case_id=cid)
    assert conv not in [x["id"] for x in c.get("/v1/conversations?all=true", headers=alice).json()]
    c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob)
    listed = {x["id"]: x for x in c.get("/v1/conversations?all=true", headers=alice).json()}
    assert listed[conv]["owner_name"] == "Bob Janssens" and listed[conv]["messages"] == 2 and listed[conv]["shared"]
    own = {x["id"]: x for x in c.get("/v1/conversations?all=true", headers=bob).json()}
    assert own[conv]["owner_name"] == ""  # his own: no name needed


def test_a_renamed_conversation_keeps_its_title_as_it_goes_on(office):
    """§4: the owner's title stays; a later question doesn't rename it after its first question."""
    c, kc, _, history, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    conv = str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    kept(history, conv, ALICE, turns, "Question")
    r = c.patch(f"/v1/conversations/{conv}", json={"title": "Sale, the price"}, headers=alice)
    assert r.status_code == 200 and r.json()["title"] == "Sale, the price"
    history.add(uuid.UUID(conv), "user", ALICE, "Question", {"kind": "question", "parent": 2}, set())
    assert c.get(f"/v1/conversations/{conv}", headers=alice).json()["title"] == "Sale, the price"
    assert c.patch(f"/v1/conversations/{conv}", json={"title": "Bob's"}, headers=bob).status_code == 404
    assert c.patch(f"/v1/conversations/{conv}", json={"title": " "}, headers=alice).status_code == 422


def test_a_personal_conversation_is_pinned_and_one_in_a_case_follows_its_case(office):
    """§3: a personal conversation can be pinned by its owner; one in a case can't (pin the case instead)."""
    c, kc, _, history, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    personal, in_case = str(uuid.uuid4()), str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    kept(history, personal, ALICE, turns, "Own")
    kept(history, in_case, ALICE, turns, "Case", case_id=cid)
    r = c.put(f"/v1/conversations/{personal}/pin", json={"pinned": True}, headers=alice)
    assert r.status_code == 200 and r.json()["pinned"]
    assert c.get("/v1/conversations", headers=alice).json()[0]["pinned"]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(f"/v1/conversations/{in_case}/pin", json={"pinned": True}, headers=alice)) == (409, "conversation.in_case")
    assert c.put(f"/v1/conversations/{personal}/pin", json={"pinned": True}, headers=bob).status_code == 404
    assert not c.put(f"/v1/conversations/{personal}/pin", json={"pinned": False}, headers=alice).json()["pinned"]


def test_a_personal_conversation_moves_into_a_case_the_owner_contributes_to(office):
    """§4: moved, it isn't shared, loses its pin, follows the case and is in the case's access log; a reader,
    a closed case and a conversation already in a case are refused."""
    c, kc, cases, history, _ = office
    alice, bob, carla = as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    conv, carlas = str(uuid.uuid4()), str(uuid.uuid4())
    kept(history, conv, BOB, turns, "Bob's")
    c.put(f"/v1/conversations/{conv}/pin", json={"pinned": True}, headers=bob)
    r = c.post(f"/v1/conversations/{conv}/move", json={"case_id": cid}, headers=bob)
    assert r.status_code == 200
    moved = r.json()
    assert moved["case_id"] == cid and not moved["shared"] and not moved["pinned"]
    assert c.get("/v1/conversations", headers=bob).json() == []  # no longer in his own space
    assert [x["id"] for x in c.get(f"/v1/conversations?case={cid}", headers=bob).json()] == [conv]
    assert [(t["role"], t["text"]) for t in c.get(f"/v1/conversations/{conv}", headers=bob).json()["turns"]] == [
        (t["role"], t["text"]) for t in turns]  # its questions came along
    events = c.get(f"/v1/cases/{cid}/events", headers=alice).json()
    assert (events[0]["user"], events[0]["action"], events[0]["detail"]) == (BOB, "conversation_moved_in", {"conversation": conv})
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{conv}/move", json={"case_id": cid}, headers=bob)) == (409, "conversation.in_case")
    # a reader can't move one in
    kept(history, carlas, CARLA, turns, "Carla's")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{carlas}/move", json={"case_id": cid}, headers=carla)) == (403, "case.not_allowed")
    # nor anyone into a closed case, or into a case they can't see, or someone else's conversation
    other = str(uuid.uuid4())
    kept(history, other, ALICE, turns, "Alice's")
    assert c.post(f"/v1/conversations/{other}/move", json={"case_id": cid}, headers=bob).status_code == 404
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{other}/move", json={"case_id": str(uuid.uuid4())}, headers=alice)) == (404, "case.not_found")
    cases.close_case(uuid.UUID(cid))
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{other}/move", json={"case_id": cid}, headers=alice)) == (403, "case.closed")
    assert c.get("/v1/conversations", headers=alice).json()[0]["case_id"] is None


def test_deleting_a_case_deletes_its_documents_and_conversations(office):
    c, kc, _, history, docs = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    turns = [{"role": "user", "text": "Vraag"}, {"role": "assistant", "text": "Antwoord"}]
    kept(history, uuid.uuid4(), ALICE, turns, "Dossier", case_id=cid)
    kept(history, uuid.uuid4(), ALICE, turns, "Los")
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
    kept(history, uuid.uuid4(), ALICE, turns, "Case", case_id=cid)

    def unreachable():
        raise OSError("no database")

    c.app.state.history = Database("conversations", connect=unreachable)
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/cases/{cid}", headers=alice)) == (503, "case.deletion_failed")
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
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/documents/{in_case}?case={cid}", headers=alice)) == (403, "case.closed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=alice)) == (403, "case.closed")


# ------------------------------------------------------------------ stage 3: closing and the keep period
def test_the_manager_closes_a_case_and_it_is_kept_for_the_offices_period(office):
    c, kc, _, _, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/close", headers=bob)) == (403, "case.not_allowed")  # a contributor can't
    r = c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert r.status_code == 200 and r.json()["state"] == "closed" and r.json()["my_role"] == "manager"
    until = datetime.fromisoformat(r.json()["keep_until"])
    assert timedelta(days=182) < until - datetime.now(UTC) < timedelta(days=184)  # 6 months, the office's period
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/close", headers=alice)) == (403, "case.closed")  # closed: read-only, also for closing
    # read-only for everyone: no uploads, questions or changes; reading and the list (behind the filter) stay
    pdf = {"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/documents?case={cid}", files=pdf, headers=alice)) == (403, "case.closed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob)) == (403, "case.closed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.patch(f"/v1/cases/{cid}", json={"name": "x"}, headers=alice)) == (403, "case.closed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)) == (403, "case.closed")
    assert c.get(f"/v1/documents?case={cid}", headers=bob).status_code == 200
    assert c.get("/v1/cases", headers=alice).json() == []
    assert [x["state"] for x in c.get("/v1/cases?closed=true", headers=alice).json()] == ["closed"]
    # the manager reopens it: open again, nothing planned
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/reopen", headers=bob)) == (403, "case.closed")
    r = c.post(f"/v1/cases/{cid}/reopen", headers=alice)
    assert r.status_code == 200 and r.json()["state"] == "open" and r.json()["keep_until"] is None
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/reopen", headers=alice)) == (403, "case.not_allowed")  # not closed: reopen isn't a right
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 202
    events = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert events[:3] == ["uploaded", "reopened", "closed"]


def test_a_closed_case_due_for_deletion_can_be_extended_kept_or_reopened(office):
    c, kc, cases, _, _ = office
    alice, bob, admin = as_user(kc, ALICE), as_user(kc, BOB), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/keep", json={"keep": True}, headers=bob)) == (404, "case.not_found")  # not visible to Bob
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
    kept(history, uuid.uuid4(), ALICE, turns, "Dossier", case_id=cid)
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    keeps = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=alice).json()["id"]
    c.post(f"/v1/cases/{keeps}/close", headers=alice)
    c.post(f"/v1/cases/{keeps}/keep", json={"keep": True}, headers=alice)
    for x in (cid, keeps):  # both past their period
        cases.cases[uuid.UUID(x)] = cases.cases[uuid.UUID(x)].model_copy(update={"keep_until": datetime.now(UTC) - timedelta(days=1)})
    assert cases.due_for_deletion() == [uuid.UUID(cid)]  # the kept one isn't
    import asyncio
    assert asyncio.run(_delete_case_everywhere(c.app, uuid.UUID(cid)))
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{cid}", headers=alice)) == (404, "case.not_found")
    assert in_case not in docs.docs and DOC in docs.docs
    assert not any(r["case_id"] == uuid.UUID(cid) for r in history.rows.values())
    assert c.get(f"/v1/cases/{keeps}", headers=alice).status_code == 200
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
        assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/documents?case={cid}", headers=bob)) == (404, "case.not_found")


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
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{cid}/members", headers=bob)) == (404, "case.not_found")  # not yet a member: unknown case
    r = c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    assert r.status_code == 200 and r.json()["name"] == "Bob Janssens" and r.json()["role"] == "reader"
    assert c.put(f"/v1/cases/{cid}/members/nobody-sub", json={"role": "reader"}, headers=alice).status_code == 404
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "manager"}, headers=alice)) == (422, "case.single_manager")
    # Bob reads, doesn't contribute; a role change makes him a contributor
    in_case = str(uuid.uuid4())
    docs.docs[in_case] = (Scope.case(uuid.UUID(cid)), "uploaded")
    assert c.get(f"/v1/cases/{cid}", headers=bob).json()["my_role"] == "reader"
    assert c.get(f"/v1/documents?case={cid}", headers=bob).status_code == 200
    pdf = {"file": ("a.pdf", b"%PDF-1.7", "application/pdf")}
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob)) == (403, "case.not_allowed")
    ask = {"messages": [{"role": "user", "content": "Vraag?"}], "document_ids": [in_case], "case_id": cid}
    assert (lambda r: (r.status_code, r.json()["code"]))(asked(c, ask, bob)) == (403, "case.not_allowed")
    assert c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice).json()["role"] == "contributor"
    assert c.post(f"/v1/documents?case={cid}", files=pdf, headers=bob).status_code == 202
    assert asked(c, ask, bob).status_code == 200
    # a contributor can't change members, and a reader can't see the log
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=bob)) == (403, "case.not_allowed")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{cid}/events", headers=bob)) == (403, "case.manager_or_administrator_only")
    # members see the list; removal; the manager can't be removed
    assert [m["user"] for m in c.get(f"/v1/cases/{cid}/members", headers=bob).json()] == [ALICE, BOB]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.delete(f"/v1/cases/{cid}/members/{ALICE}", headers=alice)) == (422, "case.single_manager")
    assert c.delete(f"/v1/cases/{cid}/members/{BOB}", headers=alice).status_code == 204
    assert c.delete(f"/v1/cases/{cid}/members/{BOB}", headers=alice).status_code == 404
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/cases/{cid}", headers=bob)) == (404, "case.not_found")
    assert c.get("/v1/cases", headers=carla).json() == []


def test_handover_by_the_manager_or_an_administrator_keeps_one_manager(office):
    c, kc, cases, _, _ = office
    alice, bob, admin = as_user(kc, ALICE), as_user(kc, BOB), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/handover", json={"user": BOB}, headers=bob)) == (404, "case.not_found")  # not even visible
    r = c.post(f"/v1/cases/{cid}/handover", json={"user": BOB}, headers=alice)
    assert r.status_code == 200 and r.json()["manager"] == BOB and r.json()["my_role"] == "contributor"
    roles = {m["user"]: m["role"] for m in c.get(f"/v1/cases/{cid}/members", headers=alice).json()}
    assert roles == {BOB: "manager", ALICE: "contributor"}
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/cases/{cid}/handover", json={"user": ALICE}, headers=alice)) == (403, "case.manager_or_administrator_only")  # no longer manages
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
    asked(c, {"text": "Wat is de koopprijs?", "document_ids": [in_case], "case_id": cid}, bob)
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
        assert (lambda r: (r.status_code, r.json()["code"]))(c.get("/v1/cases")) == (503, "case.unavailable")
        assert (lambda r: (r.status_code, r.json()["code"]))(c.post("/v1/cases", json=NEW)) == (503, "case.unavailable")
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
    assert c.my_role == "manager" and c.manager == alice and c.state == "open"
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
    changed = s.update(uuid.UUID(c.id), CaseUpdate(access="restricted"))
    assert changed.access == "restricted" and changed.updated_at > c.updated_at
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
    assert events[0].detail.model_dump() == {"documents": ["x"]}
    s._execute("UPDATE case_events SET at = now() - interval '181 days' WHERE case_id = %s AND action = 'created'", (cid,))
    assert [e.action for e in s.events(cid)] == ["asked", "opened"]  # purged after 180 days
    # a line a newer version wrote, after going back to this one: left out, said in the server's log, the rest is read
    s.log(cid, alice, "a_future_action", {"user": bob})
    assert [e.action for e in s.events(cid)] == ["asked", "opened"]
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
    assert kept(history, conv, ALICE, body["turns"], body["title"], case_id=cid)
    # private until shared: bob (a reader of the case) sees nothing, neither in the list nor by id
    assert c.get(f"/v1/conversations?case={cid}", headers=bob).json() == []
    assert c.get(f"/v1/conversations/{conv}", headers=bob).status_code == 404
    assert c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob).status_code == 404  # not his
    r = c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=alice)
    assert r.status_code == 200 and r.json()["shared"] and r.json()["owner"] == ALICE
    listed = c.get(f"/v1/conversations?case={cid}", headers=bob).json()
    assert [(x["id"], x["owner"], x["shared"]) for x in listed] == [(conv, ALICE, True)]
    assert c.get(f"/v1/conversations/{conv}", headers=bob).json()["turns"][1]["text"] == "€ 345.000 [1]"
    # read-only for bob: he can't ask in it, share or unshare it, or delete it
    assert c.post(f"/v1/conversations/{conv}/questions", json={"text": "?", "after": 2}, headers=bob).status_code == 404
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
    kept(history, mine, ALICE, body["turns"], "Persoonlijk")
    assert {x["id"] for x in c.get("/v1/conversations?all=true", headers=alice).json()} == {conv, mine}
    assert c.get("/v1/conversations?all=true", headers=bob).json() == []
    # a personal conversation can't be shared; nor can one in a closed case
    personal = str(uuid.uuid4())
    kept(history, personal, ALICE, body["turns"], body["title"])
    assert c.post(f"/v1/conversations/{personal}/share", json={"shared": True}, headers=alice).status_code == 404
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=alice)) == (403, "case.closed")
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
    kept(history, bobs, BOB, turns, "Bob's", case_id=cid)
    # the manager is asked which conversations cite it: bob's too, since it is the case's document
    assert [x["owner"] for x in c.get(f"/v1/documents/{doc}/conversations?case={cid}", headers=alice).json()] == [BOB]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.get(f"/v1/documents/{doc}/conversations?case={cid}", headers=bob)) == (403, "case.not_allowed")  # a contributor can't delete
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
    # the settings: as provisioned (members, 6m) until changed here, then effective at once
    before = c.get("/v1/admin/cases/settings", headers=admin).json()
    assert before == {"default_access": "members", "keep": "6m", "conversations_keep": "manual", "two_step": False,
                      "office_name": "", "updated_at": None, "updated_by": ""}
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
    # the office's name (boards G01, G04): set here, one line, shown to everyone after their own name; "" clears it
    assert c.get("/v1/admin/cases/settings", headers=admin).json()["office_name"] == ""
    r = c.put("/v1/admin/cases/settings", json={"office_name": "  Notariaat   Test  "}, headers=admin)
    assert r.status_code == 200 and r.json()["office_name"] == "Notariaat Test" and r.json()["keep"] == "manual"
    assert c.get("/v1/admin/cases/settings", headers=admin).json()["office_name"] == "Notariaat Test"  # /auth/me shows it (test_auth)
    assert c.put("/v1/admin/cases/settings", json={"office_name": "x" * 121}, headers=admin).status_code == 422
    assert c.put("/v1/admin/cases/settings", json={"office_name": ""}, headers=admin).json()["office_name"] == ""


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
    c, kc, _, history, _ = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    conv = str(uuid.uuid4())
    turns = [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}]
    kept(history, conv, BOB, turns, "Bob's question", case_id=cid)
    c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob)

    assert (lambda r: (r.status_code, r.json()["code"]))(c.patch(f"/v1/cases/{cid}", json={"confidential": True}, headers=bob)) == (403, "case.not_allowed")  # the manager only
    c.put(f"/v1/cases/{cid}/pin", json={"pinned": True}, headers=alice)
    r = c.patch(f"/v1/cases/{cid}", json={"confidential": True}, headers=alice)
    assert r.status_code == 200 and r.json()["confidential"] is True and r.json()["access"] == "restricted"
    assert r.json()["pinned"] is True  # the answer keeps the caller's pin: the sidebar doesn't drop the case
    assert (lambda r: (r.status_code, r.json()["code"]))(c.patch(f"/v1/cases/{cid}", json={"access": "default"}, headers=alice)) == (409, "case.strictly_confidential")
    # unshared, still Bob's; and he can't share it again
    assert c.get(f"/v1/conversations?case={cid}", headers=alice).json() == []
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(f"/v1/conversations/{conv}/share", json={"shared": True}, headers=bob)) == (409, "case.strictly_confidential")
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
    """Administration › Users, deleting an account (decision, 29 October): out of its cases, its name kept."""
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
    """Decision, 29 October (external review, pass 7, item 9): an administrator who isn't a member sees that a
    strictly confidential case exists, by its reference, with its manager, to hand it over or close it; never
    its name. Every other case, and for its members, as before."""
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
        assert seen[secret]["reference"] == "2026/0417" and seen[secret]["name"] == ""
        assert seen[plain]["name"] == "Verkoop Kerkstraat 12"  # not strictly confidential: as before
    assert by_id(c.get("/v1/admin/cases", headers=admin).json())[secret]["manager_name"]  # who manages it, to hand over
    # handed over by the administrator, the answer still holds no name
    handed = c.post(f"/v1/cases/{secret}/handover", json={"user": BOB}, headers=admin).json()
    assert handed["reference"] == "2026/0417" and handed["name"] == ""


def test_store_shows_a_strictly_confidential_case_by_its_number_outside_it(store):
    """The real store's lists: an administrator outside a strictly confidential case gets its reference,
    no name (list, list_all); its member gets all of it."""
    s = store
    alice, admin = f"alice-{uuid.uuid4()}", f"admin-{uuid.uuid4()}"
    c = s.create(CaseIn(**{**NEW, "reference": f"S-{uuid.uuid4().hex[:8]}", "confidential": True}), alice, "alice", "Alice")
    outside = next(x for x in s.list(admin, office_wide=False, admin=True) if x.id == c.id)
    assert (outside.name, outside.my_role) == ("", None) and outside.reference == c.reference
    assert next(x for x in s.list_all(admin) if x.id == c.id).name == ""
    assert next(x for x in s.list_all(alice) if x.id == c.id).name == NEW["name"]
    assert next(x for x in s.list(alice, office_wide=False) if x.id == c.id).name == NEW["name"]


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


def test_every_answer_of_the_offices_settings_is_what_the_description_says(office):
    """The chat UI's code for the office's settings is generated from the description (suveryn-tracker#237)."""
    from described import Checked

    c, kc, _, _, _ = office
    check, alice, admin = Checked(c, "settings"), as_user(kc, ALICE), admin_headers(kc)
    settings, preview = "/v1/admin/cases/settings", "/v1/admin/cases/settings/preview"
    for method, path, sent in (("GET", settings, {}), ("GET", preview, {}), ("PUT", settings, {"json": {"keep": "1y"}})):
        assert check(method, path, 401, **sent).json()["code"] == "auth.signed_out"
        assert check(method, path, 403, keep="not_an_administrator" if method == "PUT" else None, headers=alice, **sent).json()["code"] == "request.forbidden"
    assert check("GET", settings, 200, keep="as_provisioned", headers=admin).json()["updated_at"] is None
    c.post("/v1/cases", json=NEW, headers=alice)
    opened = check("GET", preview, 200, preview + "?default_access=office&apply_to=all", "preview", headers=admin).json()
    assert opened == {"cases_opened": 1, "cases_closed": 0, "conversations_deleted": 0}
    assert "errors" in check("GET", preview, 422, preview + "?apply_to=some", headers=admin).json()
    saved = check("PUT", settings, 200, keep="saved", same_every_run={"updated_at": "2026-11-22T09:00:00Z"}, headers=admin,
                  json={"default_access": "office", "keep": "1y", "office_name": "  Notariaat   Test  "}).json()
    assert (saved["default_access"], saved["keep"], saved["office_name"], saved["updated_by"] != "") == ("office", "1y", "Notariaat Test", True)
    assert check("PUT", settings, 422, keep="nothing_to_change", json={}, headers=admin).json()["code"] == "request.invalid"
    assert "errors" in check("PUT", settings, 422, json={"keep": "2y"}, headers=admin).json()
    check.kept.check()
    # not seen: what nobody planned for; sign-in or the stores down (test_auth.py, test_problems.py, and the cases'
    # own store away, test_cases.py)
    # and an account gone from the sign-in service while two-step sign-in is switched on for everyone (test_users.py)
    assert check.not_seen() == {(m, p, s) for m, p in (("GET", settings), ("GET", preview), ("PUT", settings)) for s in (500, 503)} | {
        ("PUT", settings, 404)}


def test_every_answer_of_cases_is_what_the_description_says(office):
    """The chat UI's code for cases is generated from the description (suveryn-tracker#244): each answer the
    operations give, the refusals too, is checked against it and kept for the chat UI's tests."""
    from described import Checked

    c, kc, _, _, _ = office
    check, alice, bob, carla, admin = Checked(c, "cases"), as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA), admin_headers(kc)
    CASE, OTHER, WHEN = "00000000-0000-4000-8000-0000000000c1", "00000000-0000-4000-8000-0000000000c2", "2026-11-23T09:00:00Z"
    ids: dict[str, str] = {}

    def same(body):  # this run's ids and moments, wherever they are in an answer
        if isinstance(body, list):
            for item in body:
                same(item)
        elif isinstance(body, dict):
            for key, value in body.items():
                if key in ("opened_at", "created_at", "updated_at", "closed_at", "keep_until", "added_at", "at", "last_activity_at") and value:
                    body[key] = WHEN
                elif isinstance(value, str) and value in ids:
                    body[key] = ids[value]
                else:
                    same(value)

    one, members, member = "/v1/cases/{case_id}", "/v1/cases/{case_id}/members", "/v1/cases/{case_id}/members/{user}"
    gone = "/v1/cases/00000000-0000-4000-8000-00000000dead"
    every = [("GET", "/v1/admin/cases", None, {}), ("GET", "/v1/case-types", None, {}), ("GET", "/v1/cases", None, {}),
             ("POST", "/v1/cases", None, {"json": NEW}), ("GET", "/v1/cases/overview", None, {}), ("DELETE", one, gone, {}), ("GET", one, gone, {}),
             ("PATCH", one, gone, {"json": {"name": "x"}}), ("POST", one + "/close", gone + "/close", {}), ("GET", one + "/events", gone + "/events", {}),
             ("POST", one + "/handover", gone + "/handover", {"json": {"user": BOB}}), ("POST", one + "/keep", gone + "/keep", {"json": {"keep": True}}),
             ("GET", members, gone + "/members", {}), ("DELETE", member, gone + f"/members/{BOB}", {}),
             ("PUT", member, gone + f"/members/{BOB}", {"json": {"role": "reader"}}), ("PUT", one + "/pin", gone + "/pin", {"json": {"pinned": True}}),
             ("POST", one + "/reopen", gone + "/reopen", {})]
    for method, path, at, sent in every:
        assert check(method, path, 401, at, **sent).json()["code"] == "auth.signed_out"
        if "{case_id}" in path:  # a case that doesn't exist, or that the caller may not see: the same answer
            assert check(method, path, 404, at, "no_such_case" if method == "GET" and path == one else None, headers=alice, **sent).json()["code"] == "case.not_found"
            # what isn't a case id at all is refused by the gateway itself, before anything is looked up
            r = check(method, path, 422, at.replace(gone, "/v1/cases/not-an-id"), "not_a_case_id" if method == "GET" and path == one else None, headers=alice, **sent)
            assert r.json()["code"] == "request.invalid"
    assert check("GET", "/v1/admin/cases", 403, keep="not_an_administrator", headers=alice).json()["code"] == "request.forbidden"

    assert [t["id"] for t in check("GET", "/v1/case-types", 200, keep="types", headers=alice).json()]
    made = check("POST", "/v1/cases", 201, keep="created", tidy=lambda b: (ids.update({b["id"]: CASE}), same(b)), json=NEW, headers=alice).json()
    cid = made["id"]
    at = lambda rest="": f"/v1/cases/{cid}{rest}"  # noqa: E731
    assert check("POST", "/v1/cases", 409, keep="reference_taken", json=NEW, headers=alice).json()["code"].startswith("case.")
    assert "errors" in check("POST", "/v1/cases", 422, json={"reference": " ", "name": "", "type": "sale"}, headers=alice).json()
    assert check("GET", one, 200, at(), "one", tidy=same, headers=alice).json()["my_role"] == "manager"
    assert check("PATCH", one, 200, at(), "renamed", tidy=same, json={"name": "Verkoop Kerkstraat 14"}, headers=alice).json()["name"].endswith("14")
    assert "errors" in check("PATCH", one, 422, at(), json={"name": ""}, headers=alice).json()
    added = check("PUT", member, 200, at(f"/members/{BOB}"), "member_added", tidy=same, json={"role": "reader"}, headers=alice).json()
    assert added["role"] == "reader" and added["user"] == BOB
    assert "errors" in check("PUT", member, 422, at(f"/members/{BOB}"), json={"role": "owner"}, headers=alice).json()
    assert len(check("GET", members, 200, at("/members"), "members", tidy=same, headers=alice).json()) == 2
    # a reader may read the case, and change nothing in it
    refused = [("PATCH", one, at(), {"json": {"name": "x"}}), ("POST", one + "/close", at("/close"), {}), ("DELETE", one, at(), {}),
               ("POST", one + "/handover", at("/handover"), {"json": {"user": BOB}}), ("POST", one + "/keep", at("/keep"), {"json": {"keep": True}}),
               ("PUT", member, at(f"/members/{CARLA}"), {"json": {"role": "reader"}}), ("DELETE", member, at(f"/members/{ALICE}"), {}),
               ("GET", one + "/events", at("/events"), {}), ("POST", one + "/reopen", at("/reopen"), {})]
    for method, path, where, sent in refused:
        r = check(method, path, 403, where, "not_allowed" if method == "PATCH" else None, headers=bob, **sent)
        assert r.json()["code"] in ("case.not_allowed", "case.manager_or_administrator_only", "request.forbidden"), (method, path, r.json()["code"])
    assert check("PUT", one + "/pin", 200, at("/pin"), "pinned", tidy=same, json={"pinned": True}, headers=bob).json()["pinned"] is True
    assert "errors" in check("PUT", one + "/pin", 422, at("/pin"), json={}, headers=bob).json()
    assert [x["id"] for x in check("GET", "/v1/cases", 200, keep="mine", tidy=same, headers=alice).json()] == [cid]
    assert "errors" in check("GET", "/v1/cases", 422, "/v1/cases?closed=perhaps", headers=alice).json()
    overview = check("GET", "/v1/cases/overview", 200, keep="overview", tidy=same, headers=alice).json()
    assert [m["user"] for m in overview[0]["members"]] == [ALICE, BOB]
    assert check("GET", one + "/events", 200, at("/events"), "events", tidy=same, headers=alice).json()[0]["action"]
    assert check("POST", one + "/handover", 200, at("/handover"), "handed_over", tidy=same, json={"user": BOB}, headers=alice).json()["manager"] == BOB
    assert "errors" in check("POST", one + "/handover", 422, at("/handover"), json={}, headers=bob).json()
    check("DELETE", member, 204, at(f"/members/{ALICE}"), "done", headers=bob)
    assert "errors" in check("POST", one + "/keep", 422, at("/keep"), json={"keep": "always"}, headers=bob).json()
    assert check("POST", one + "/keep", 403, at("/keep"), "still_open", json={"extend": True}, headers=bob).json()["code"] == "request.forbidden"
    assert check("POST", one + "/reopen", 403, at("/reopen"), headers=bob).json()["code"] == "case.not_allowed"  # it is open
    assert check("POST", one + "/close", 200, at("/close"), "closed", tidy=same, headers=bob).json()["state"] == "closed"
    assert check("POST", one + "/close", 403, at("/close"), "already_closed", headers=bob).json()["code"] == "case.closed"
    assert check("PATCH", one, 403, at(), json={"name": "y"}, headers=bob).json()["code"] == "case.closed"
    assert check("POST", one + "/keep", 422, at("/keep"), "nothing_to_change", json={}, headers=bob).json()["code"] == "request.invalid"
    assert check("POST", one + "/keep", 200, at("/keep"), "kept", tidy=same, json={"keep": True}, headers=bob).json()["keep"] is True
    assert check("POST", one + "/reopen", 200, at("/reopen"), "reopened", tidy=same, headers=bob).json()["state"] == "open"
    other = c.post("/v1/cases", json={**NEW, "reference": "2026/0418"}, headers=carla).json()["id"]
    ids[other] = OTHER
    listed = check("GET", "/v1/admin/cases", 200, keep="office", tidy=same, headers=admin).json()
    assert {x["id"] for x in listed} == {cid, other} and all("manager_name" in x for x in listed)
    check("DELETE", one, 204, at(), headers=bob)
    # a strictly confidential case is for its members only: it can't be given the office's default access
    # (the other 409 of a change, a reference another case has, is the database's: the store's own tests, above)
    assert check("PATCH", one, 200, f"/v1/cases/{other}", json={"confidential": True}, headers=carla).json()["access"] == "restricted"
    assert check("PATCH", one, 409, f"/v1/cases/{other}", "members_only", json={"access": "default"}, headers=carla).json()["code"] == "case.strictly_confidential"
    check.kept.check()
    # not seen here, each for a reason: what nobody planned for (500); sign-in or a store down (503: test_auth.py,
    # and the cases' own store away, above in this file); sign-in turned off for another machine, for what anyone
    # signed in may do (403); two people closing, reopening or keeping a case in the same moment: the second is
    # told so (409)
    for method, path, status in check.not_seen():
        assert status in (500, 503) or (status == 409 and path in (one + "/close", one + "/reopen", one + "/keep")) or (
            status == 403 and (method, path) in {("GET", "/v1/case-types"), ("GET", "/v1/cases"), ("POST", "/v1/cases"), ("GET", "/v1/cases/overview"),
                                                 ("GET", one), ("GET", members), ("PUT", one + "/pin")}), (method, path, status)
    assert {s for _, _, s in check.seen} == {200, 201, 204, 401, 403, 404, 409, 422}


def test_every_answer_of_conversations_is_what_the_description_says(office):
    """The chat UI's code for conversations is generated from the description (suveryn-tracker#246): each answer
    the operations give, the refusals too, is checked against it and kept for the chat UI's tests. Here and not
    in test_conversations.py: sharing, moving and a pin need the cases."""
    from described import Checked, same_every_run

    c, kc, _, history, _ = office
    check, alice, bob, carla = Checked(c, "conversations"), as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    CASE, WHEN = "00000000-0000-4000-8000-0000000000c1", "2026-11-23T09:00:00Z"
    OWN, BOBS, CARLAS, GONE = (f"00000000-0000-4000-8000-0000000000{n}" for n in ("a1", "a2", "a3", "ad"))
    ids: dict[str, str] = {}

    def same(body):  # this run's case and moments, wherever they are in an answer
        if isinstance(body, list):
            for item in body:
                same(item)
        elif isinstance(body, dict):
            for key, value in body.items():
                if key in ("created_at", "updated_at", "at") and value:
                    body[key] = WHEN
                elif isinstance(value, str) and value in ids:
                    body[key] = ids[value]
                else:
                    same(value)

    turns = [{"role": "user", "text": "Wat is de koopprijs?"}, {"role": "assistant", "text": "€ 345.000 [1]"}]
    every, one = "/v1/conversations", "/v1/conversations/{conversation_id}"
    with_id = [("DELETE", one, "", {}), ("GET", one, "", {}), ("PATCH", one, "", {"json": {"title": "x"}}),
               ("POST", one + "/move", "/move", {"json": {"case_id": CASE}}), ("PUT", one + "/pin", "/pin", {"json": {"pinned": True}}),
               ("POST", one + "/share", "/share", {"json": {"shared": True}})]
    for method, path, at, sent in [("DELETE", every, None, {}), ("GET", every, None, {})]:
        assert check(method, path, 401, at, **sent).json()["code"] == "auth.signed_out"
    for method, path, rest, sent in with_id:
        assert check(method, path, 401, f"{every}/{GONE}{rest}", **sent).json()["code"] == "auth.signed_out"
        # what isn't a conversation id at all is refused before anything is looked up
        r = check(method, path, 422, f"{every}/not-an-id{rest}", "not_a_conversation_id" if method == "GET" else None, headers=alice, **sent)
        assert r.json()["code"] == "request.invalid"
        # one that doesn't exist, or isn't the caller's: the same answer
        r = check(method, path, 404, f"{every}/{GONE}{rest}", "no_such_conversation" if method == "GET" else None, headers=alice, **sent)
        assert r.json()["code"] == "request.not_found"

    assert check("GET", every, 200, keep="none", headers=alice).json() == []
    kept(history, OWN, ALICE, turns)  # asked as the server keeps it (suveryn-tracker#251)
    opened = check("GET", one, 200, f"{every}/{OWN}", "one", tidy=same, headers=alice).json()
    assert [t["text"] for t in opened["turns"]] == [t["text"] for t in turns] and opened["messages"] == 2
    assert check("PATCH", one, 200, f"{every}/{OWN}", "renamed", tidy=same, json={"title": "De koopprijs"}, headers=alice).json()["title"] == "De koopprijs"
    assert "errors" in check("PATCH", one, 422, f"{every}/{OWN}", json={"title": ""}, headers=alice).json()
    assert check("PUT", one + "/pin", 200, f"{every}/{OWN}/pin", "pinned", tidy=same, json={"pinned": True}, headers=alice).json()["pinned"] is True
    assert "errors" in check("PUT", one + "/pin", 422, f"{every}/{OWN}/pin", json={}, headers=alice).json()
    assert [x["id"] for x in check("GET", every, 200, keep="mine", tidy=same, headers=alice).json()] == [OWN]

    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    ids[cid] = CASE
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    kept(history, BOBS, BOB, turns, "Bob's", case_id=cid)
    kept(history, CARLAS, CARLA, turns, "Carla's", case_id=cid)
    # in a case a conversation follows its case: no pin of its own
    assert check("PUT", one + "/pin", 409, f"{every}/{BOBS}/pin", "in_a_case", json={"pinned": True}, headers=bob).json()["code"] == "conversation.in_case"
    assert check("POST", one + "/share", 200, f"{every}/{BOBS}/share", "shared", tidy=same, json={"shared": True}, headers=bob).json()["shared"] is True
    assert "errors" in check("POST", one + "/share", 422, f"{every}/{BOBS}/share", json={}, headers=bob).json()
    # a reader changes nothing in the case: not what its members see either
    assert check("POST", one + "/share", 403, f"{every}/{CARLAS}/share", "not_allowed", json={"shared": True}, headers=carla).json()["code"] == "case.not_allowed"
    assert check("GET", one, 200, f"{every}/{BOBS}", tidy=same, headers=alice).json()["owner"] == BOB  # shared: Alice reads it
    listed = check("GET", every, 200, f"{every}?all=true", "all", tidy=same, headers=alice).json()
    assert {x["id"]: x["owner_name"] for x in listed} == {OWN: "", BOBS: "Bob Janssens"}
    assert [x["id"] for x in check("GET", every, 200, f"{every}?case={cid}", headers=alice).json()] == [BOBS]
    assert "errors" in check("GET", every, 422, f"{every}?all=perhaps", headers=alice).json()
    assert check("GET", every, 404, f"{every}?case={GONE}", headers=alice).json()["code"] == "case.not_found"
    assert "errors" in check("POST", one + "/move", 422, f"{every}/{OWN}/move", json={}, headers=alice).json()
    moved = check("POST", one + "/move", 200, f"{every}/{OWN}/move", "moved", tidy=same, json={"case_id": cid}, headers=alice).json()
    assert moved["case_id"] == cid and moved["pinned"] is False
    assert check("POST", one + "/move", 409, f"{every}/{OWN}/move", json={"case_id": cid}, headers=alice).json()["code"] == "conversation.in_case"
    kept(history, GONE, CARLA, turns)  # her own, in her personal space
    assert check("POST", one + "/move", 403, f"{every}/{GONE}/move", json={"case_id": cid}, headers=carla).json()["code"] == "case.not_allowed"
    # in a strictly confidential case nothing is shared
    c.patch(f"/v1/cases/{cid}", json={"confidential": True}, headers=alice)
    r = check("POST", one + "/share", 409, f"{every}/{BOBS}/share", "confidential_case", json={"shared": True}, headers=bob)
    assert r.json()["code"] == "case.strictly_confidential"
    # a question asked in a conversation the server keeps (suveryn-tracker#251): the question and its answer are stored
    asking, NEW_ONE = one + "/questions", "00000000-0000-4000-8000-0000000000a4"
    question = {"text": "Wat is de koopprijs?"}
    assert check("POST", asking, 401, f"{every}/{GONE}/questions", json=question).json()["code"] == "auth.signed_out"
    assert check("POST", asking, 422, f"{every}/not-an-id/questions", json=question, headers=alice).json()["code"] == "request.invalid"
    assert "errors" in check("POST", asking, 422, f"{every}/{NEW_ONE}/questions", json={"text": ""}, headers=alice).json()
    assert check("POST", asking, 404, f"{every}/{BOBS}/questions", json=question, headers=alice).json()["code"] == "request.not_found"
    r = check("POST", asking, 409, f"{every}/{NEW_ONE}/questions", "nothing_to_ask_again", json={"again": 1}, headers=alice)
    assert r.json()["code"] == "request.conflict"
    assert check("POST", asking, 403, f"{every}/{NEW_ONE}/questions", json={**question, "case_id": cid}, headers=carla).json()["code"] == "case.not_allowed"
    asked = check("POST", asking, 200, f"{every}/{NEW_ONE}/questions", "asked", tidy=same_every_run(), json=question, headers=alice)
    assert asked.headers["content-type"].startswith("text/event-stream")
    assert check.kept.answers["asked"]["body"][-1]["event"] == "done"
    assert [t["role"] for t in check("GET", one, 200, f"{every}/{NEW_ONE}", headers=alice).json()["turns"]] == ["user", "assistant"]
    FULL = "00000000-0000-4000-8000-0000000000a5"
    kept(history, FULL, ALICE, [{"role": "user", "text": "?"}] * 499)
    r = check("POST", asking, 413, f"{every}/{FULL}/questions", "too_long_to_ask_in", json=question, headers=alice)
    assert r.json()["code"] == "conversation.too_long"  # one turn short of the limit: no room for a question and its answer
    # asking shares the limit on asking, per person (an office of its own, with a limit of one)
    from suveryn_api_gateway.ratelimit import RateLimits

    kc2 = FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc2.handler)))
    limited = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([])), load_documents=False,
                         auth=auth, conversations=FakeConversations(), rate_limits=RateLimits(chat=1))
    with TestClient(limited) as c2:
        check2, alice2 = Checked(c2, "conversations"), as_user(kc2, ALICE)
        check2.kept = check.kept
        check2("POST", asking, 200, f"{every}/{NEW_ONE}/questions", json=question, headers=alice2)
        r = check2("POST", asking, 429, f"{every}/{NEW_ONE}/questions", "too_many_questions", json=question, headers=alice2)
        assert r.json()["code"] == "request.too_many"
        check.seen |= check2.seen

    check("DELETE", one, 204, f"{every}/{BOBS}", "done", headers=bob)
    assert check("DELETE", every, 200, keep="all_deleted", headers=alice).json() == {"deleted": 3}
    check.kept.check()
    # not seen here, each for a reason: what nobody planned for (500); sign-in or the conversations' store down
    # (503: test_auth.py, test_conversations.py); and sign-in turned off for another machine, for what anyone
    # signed in may do with a conversation of their own (403)
    for method, path, status in check.not_seen():
        assert status in (500, 503) or (status == 403 and (path == every or (method, path) in {
            ("DELETE", one), ("GET", one), ("PATCH", one), ("PUT", one + "/pin")})), (method, path, status)
    assert {s for _, _, s in check.seen} == {200, 204, 401, 403, 404, 409, 413, 422, 429}


def test_every_answer_of_documents_is_what_the_description_says(office, monkeypatch):
    """The chat UI's code for documents is generated from the description (suveryn-tracker#248): each answer the
    operations give, the refusals too, is checked against it and kept for the chat UI's tests. Here and not in
    test_documents.py: a case's documents, an upload's mark and a saved answer need the cases and sign-in."""
    import io

    from described import Checked, same_every_run
    from suveryn_api_gateway.app import MAX_UPLOAD_BYTES
    from suveryn_rag.reading import Progress
    from suveryn_rag.service import UploadRejected
    from suveryn_rag.store import Original

    c, kc, _, history, docs = office
    check, alice, bob, carla = Checked(c, "documents"), as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    tidy = same_every_run()
    GONE = "00000000-0000-4000-8000-00000000dead"
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    pdf = lambda name="akte.pdf": {"files": {"file": (name, io.BytesIO(b"%PDF-1.7"), "application/pdf")}}  # noqa: E731

    every, everywhere, upload, one = "/v1/documents", "/v1/documents/all", "/v1/documents/jobs/{job_id}", "/v1/documents/{document_id}"
    source, citing, original, content = one + "/source", one + "/conversations", one + "/original", one + "/content"
    of = lambda path, did, rest="": path.replace("{document_id}", did) + rest  # noqa: E731
    of_document = [("DELETE", one, {}), ("POST", source, {}), ("GET", citing, {}), ("GET", original, {}), ("GET", content, {})]
    for method, path, at, sent in [("GET", every, None, {}), ("POST", every, None, pdf()), ("GET", everywhere, None, {}),
                                   ("GET", upload, upload.replace("{job_id}", "x"), {}), ("DELETE", upload, upload.replace("{job_id}", "x"), {}),
                                   *[(m, p, of(p, DOC), s) for m, p, s in of_document]]:
        assert check(method, path, 401, at, **sent).json()["code"] == "auth.signed_out"
    for method, path, sent in of_document:
        # what isn't a document id at all; a document that isn't there (a case that isn't, where only its manager may ask)
        assert check(method, path, 422, of(path, "not-an-id"), headers=alice, **sent).json()["code"] == "request.invalid"
        r = check(method, path, 404, of(path, GONE, f"?case={GONE}" if path == citing else ""), "no_such_document" if path == content else None, headers=alice, **sent)
        assert r.json()["code"] in ("request.not_found", "case.not_found")
        if path in (one, source, citing):  # a reader of the case reads its documents, and changes nothing
            assert check(method, path, 403, of(path, DOC, f"?case={cid}"), headers=carla, **sent).json()["code"] == "case.not_allowed"
    for method, path, sent in [("GET", every, {}), ("POST", every, pdf())]:
        assert check(method, path, 422, f"{every}?case=not-an-id", headers=alice, **sent).json()["code"] == "request.invalid"
        assert check(method, path, 404, f"{every}?case={GONE}", headers=alice, **sent).json()["code"] == "case.not_found"

    # an upload: a document, or an archive of them; refused by its size, by what it is, or while there is no room
    assert check("POST", every, 403, f"{every}?case={cid}", headers=carla, **pdf()).json()["code"] == "case.not_allowed"
    assert "errors" in check("POST", every, 422, headers=alice, data={"note": "no file"}).json()
    waiting = check("POST", every, 202, keep="uploading", tidy=tidy, headers=alice, **pdf()).json()
    assert (waiting["status"], waiting["document_id"], waiting["failure"], waiting["warnings"]) == ("queued", None, None, [])
    packed = check("POST", every, 202, f"{every}?case={cid}", "archive", tidy=tidy, headers=bob, **pdf("stukken.zip")).json()
    assert [j["filename"] for j in packed["jobs"]] == ["akte.pdf", "notes.docx"] and packed["skipped"][0]["failure"]["code"] == "upload.unsupported"
    r = check("POST", every, 411, content=iter([b"%PDF-"]), headers={**alice, "content-type": "multipart/form-data; boundary=x"})
    assert r.json()["code"] == "request.invalid"
    r = check("POST", every, 413, keep="too_large", content=b"%PDF-", headers={**alice, "content-length": str(MAX_UPLOAD_BYTES * 2), "content-type": "multipart/form-data; boundary=x"})
    assert (r.json()["code"], r.json()["params"]["max_mb"] > 0) == ("upload.too_large", True)
    accept = docs.accept_upload
    for status_, code, name in [(415, "upload.unsupported", "not_read"), (429, "upload.too_many", "too_many_waiting")]:
        def refuse(*_, code=code, **__):  # as document handling itself refuses (suveryn_rag.service)
            raise UploadRejected("refused", code)
        docs.accept_upload = refuse
        assert check("POST", every, status_, keep=name, headers=alice, **pdf("notes.txt")).json()["code"] == code
    docs.accept_upload = accept
    with monkeypatch.context() as m:
        m.setattr("suveryn_api_gateway.routes.documents.disk_low", lambda: True)
        assert check("POST", every, 507, keep="disk_full", headers=alice, **pdf()).json()["code"] == "upload.disk_full"

    # an upload is followed while it is read, cancelled until it is read
    job = docs.jobs[waiting["id"]]
    from suveryn_api_gateway.routes.documents import Upload
    assert set(job.public()) == set(Upload.model_fields)  # all the rag says of an upload is described, and no more
    at = upload.replace("{job_id}", job.id)
    assert check("GET", upload, 404, upload.replace("{job_id}", "nope"), headers=alice).json()["code"] == "request.not_found"
    assert check("GET", upload, 404, at, headers=bob).json()["code"] == "request.not_found"  # another's: the same answer
    job.status, job.progress, job.pages = "processing", Progress("ocr", 2, 5), 5
    reading = check("GET", upload, 200, at, "reading", tidy=tidy, headers=alice).json()
    assert (reading["status"], reading["progress"]) == ("processing", {"step": "ocr", "done": 2, "total": 5})
    job.status, job.progress, job.error, job.error_code, job.error_detail = "failed", None, "too many pages", "document.pages_too_many", {"pages": 900, "max": 500}
    failed = check("GET", upload, 200, at, "failed", tidy=tidy, headers=alice).json()
    assert (failed["failure"]["code"], failed["failure"]["kind"]) == ("document.pages_too_many", "refused")
    assert check("DELETE", upload, 409, at, "already_read", headers=alice).json()["code"] == "upload.already_read"
    assert check("DELETE", upload, 404, upload.replace("{job_id}", "nope"), headers=alice).json()["code"] == "request.not_found"
    second = check("POST", every, 202, headers=alice, **pdf("tweede.pdf")).json()["id"]
    check("DELETE", upload, 204, upload.replace("{job_id}", second), "done", headers=alice)

    # the documents of a place, and everywhere; one that carries sūveryn's own mark is no source until someone says so
    marked = str(uuid.uuid4())
    docs.docs[marked] = (Scope.case(uuid.UUID(cid)), "uploaded")
    docs.noticed[marked] = {"ref": "A-3f9c2e1b", "kind": "answer", "line": "sūveryn · A-3f9c2e1b"}
    mine = check("GET", every, 200, keep="mine", tidy=tidy, headers=alice).json()
    assert [d["origin"] for d in mine["documents"]] == ["uploaded"] and [j["status"] for j in mine["jobs"]] == ["failed"]
    in_case = check("GET", every, 200, f"{every}?case={cid}", "in_case", tidy=tidy, headers=carla).json()
    assert (in_case["documents"][0]["source"], in_case["documents"][0]["provenance"]["noticed"]["ref"]) == (False, "A-3f9c2e1b")
    assert {d["case_id"] for d in check("GET", everywhere, 200, keep="everywhere", tidy=tidy, headers=alice).json()["documents"]} == {None, cid}
    assert check("POST", source, 200, of(source, marked, f"?case={cid}"), "used_as_source", tidy=tidy, headers=bob).json()["source"] is True
    confirmed = check("GET", every, 200, f"{every}?case={cid}", "confirmed", tidy=tidy, headers=carla).json()["documents"][0]
    assert confirmed["source"] is True and confirmed["provenance"]["confirmed"]["by"]
    assert check("GET", citing, 200, of(citing, DOC), "citing", headers=alice).json() == []

    # the file as uploaded, where one was kept
    docs.originals = {DOC: ("Compromis.pdf", Original("application/pdf", b"%PDF-1.7 test")), marked: ("notes.md", Original("text/plain; charset=utf-8", b"# notes"))}
    assert check("GET", original, 200, of(original, DOC), headers=alice).content == b"%PDF-1.7 test"
    assert check("GET", original, 200, of(original, marked, f"?case={cid}"), headers=carla).headers["content-type"].startswith("text/plain")

    # an answer the server stored, saved by naming it (suveryn-tracker#251, step 2): the server copies it
    turn = "/v1/conversations/{conversation_id}/turns/{seq}/document"
    ASKED, MINE = "00000000-0000-4000-8000-0000000000a2", "00000000-0000-4000-8000-0000000000a3"
    at_turn = lambda conversation, seq: turn.replace("{conversation_id}", conversation).replace("{seq}", str(seq))  # noqa: E731
    c.post(f"/v1/conversations/{ASKED}/questions", json={"text": "What is the price?", "case_id": cid}, headers=bob)
    c.post(f"/v1/conversations/{MINE}/questions", json={"text": "What is the price?"}, headers=alice)  # her personal space
    assert check("POST", turn, 401, at_turn(ASKED, 2)).json()["code"] == "auth.signed_out"
    assert check("POST", turn, 422, at_turn("not-an-id", 2), headers=bob).json()["code"] == "request.invalid"
    assert "errors" in check("POST", turn, 422, at_turn(ASKED, "x"), headers=bob).json()
    assert check("POST", turn, 404, at_turn(ASKED, 2), headers=alice).json()["code"] == "request.not_found"  # Bob's
    assert check("POST", turn, 404, at_turn(ASKED, 1), "no_such_answer", headers=bob).json()["code"] == "request.not_found"  # a question
    assert check("POST", turn, 409, at_turn(MINE, 2), "not_in_a_case", headers=alice).json()["code"] == "request.conflict"
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    assert check("POST", turn, 403, at_turn(ASKED, 2), headers=bob).json()["code"] == "case.not_allowed"
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
    copied = check("POST", turn, 201, at_turn(ASKED, 2), "saved_from_turn", tidy=tidy, headers=bob).json()
    assert copied["created"] is True and copied["filename"] == "What is the price.docx"
    assert check("POST", turn, 200, at_turn(ASKED, 2), headers=bob).json() == {**copied, "created": False}
    stored = check("GET", content, 200, of(content, copied["id"], f"?case={cid}"), "content_from_turn",
                   tidy=same_every_run(moments=("answeredOn",)), headers=carla).json()["content"]
    assert (stored["question"], stored["answer"], stored["turnId"]) == ("What is the price?", "De koopprijs is EUR 412.500,00 [1].", f"{ASKED}/2")

    # deleted, with the conversations that cite it cleaned; accepted when that cleaning is still to be done
    assert "errors" in check("DELETE", one, 422, of(one, DOC, "?conversations=keep"), headers=alice).json()
    check("DELETE", one, 204, of(one, copied["id"], f"?case={cid}"), headers=bob)  # his own saved answer: undone

    def later(*_, **__):
        raise RuntimeError("the conversations' store went away")
    monkeypatch.setattr(history, "remove_document", later)
    check("DELETE", one, 202, of(one, DOC), headers=alice)
    check.kept.check()
    # not seen here, each for a reason: what nobody planned for (500); sign-in, document handling or the saved
    # conversations down (503: test_auth.py, test_documents.py); an upload's id is any text, so nothing about it
    # is refused as invalid (422); and sign-in turned off for another machine, for what is the caller's own or
    # what whoever sees the case may read (403)
    for method, path, status_code in check.not_seen():
        assert status_code in (500, 503) or (status_code == 422 and path == upload) or (
            status_code == 403 and (path in (upload, everywhere, original, content) or (method, path) == ("GET", every))), (method, path, status_code)
    assert {s for _, _, s in check.seen} == {200, 201, 202, 204, 401, 403, 404, 409, 411, 413, 415, 422, 429, 507}


def test_every_answer_as_it_streams_is_what_the_description_says(office):
    """The chat UI's code for an answer is generated from the description (suveryn-tracker#249): each event of an answer
    as it streams, the refusals too, are checked against it and kept for the chat UI's tests. An answer is asked in a
    conversation the server keeps (suveryn-tracker#251): one new conversation per question here."""
    from described import Checked, same_every_run
    from suveryn_api_gateway.ratelimit import RateLimits
    from suveryn_harness import DocumentsUnavailable

    c, kc, _, _, docs = office
    check, alice, bob, carla = Checked(c, "answers"), as_user(kc, ALICE), as_user(kc, BOB), as_user(kc, CARLA)
    tidy, asking = same_every_run(), "/v1/conversations/{conversation_id}/questions"
    numbered = iter(range(1, 100))
    at = lambda: asking.replace("{conversation_id}", f"00000000-0000-4000-8000-0000000001{next(numbered):02d}")  # noqa: E731
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    ask = {"text": "Wat is de koopprijs?"}
    assert check("POST", asking, 401, at(), json=ask).json()["code"] == "auth.signed_out"
    # refused before anything is asked: not a document id, a model this appliance doesn't have
    assert check("POST", asking, 422, at(), json={**ask, "document_ids": ["nope"]}, headers=alice).json()["code"] == "request.invalid"
    assert check("POST", asking, 422, at(), "no_such_model", json={**ask, "model": "nope"}, headers=alice).json()["code"] == "model.not_found"
    # a case the caller doesn't see, a document that isn't the caller's, and a reader, who may read and not ask
    assert check("POST", asking, 404, at(), json={**ask, "case_id": str(uuid.uuid4())}, headers=alice).json()["code"] == "case.not_found"
    r = check("POST", asking, 404, at(), "no_such_document", json={**ask, "document_ids": [DOC]}, headers=bob)
    assert r.json()["code"] == "answer.document_not_found"
    assert check("POST", asking, 403, at(), json={**ask, "case_id": cid}, headers=carla).json()["code"] == "case.not_allowed"

    # an answer as it streams: what the server does, the passages, the words, then the whole answer
    stream = check("POST", asking, 200, at(), "stream", tidy=tidy, json={**ask, "document_ids": [DOC]}, headers=alice)
    assert stream.headers["content-type"].startswith("text/event-stream")
    names = [e["event"] for e in check.kept.answers["stream"]["body"]]
    assert names[-1] == "done" and {"status", "sources", "delta", "done"} <= set(names) and names.index("sources") < names.index("delta")
    done = check.kept.answers["stream"]["body"][-1]["data"]
    assert done["citations"][0]["source"]["page"] == 2 and done["answer"].endswith("[1].") and done["complete"] is True

    # one that can't be completed ends with why, as a code of the registry
    def away(*_, **__):
        raise DocumentsUnavailable("the documents can't be searched")
    found, docs.retrieve = docs.retrieve, away
    check("POST", asking, 200, at(), "stream_failed", tidy=tidy, json={**ask, "document_ids": [DOC]}, headers=alice)
    docs.retrieve = found
    last = check.kept.answers["stream_failed"]["body"][-1]
    assert (last["event"], last["data"]["code"], last["data"]["kind"]) == ("error", "document.unavailable", "unavailable")

    # the limit on asking, per person (an office of its own, with a limit of one)
    kc2 = FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc2.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    limited = create_app(llm, documents=FakeDocuments(owner=ALICE), load_documents=False, auth=auth, rate_limits=RateLimits(chat=1),
                         conversations=FakeConversations())
    with TestClient(limited) as c2:
        check2, alice2 = Checked(c2, "answers"), as_user(kc2, ALICE)
        check2.kept = check.kept
        check2("POST", asking, 200, at(), json=ask, headers=alice2)
        assert check2("POST", asking, 429, at(), "too_many", json=ask, headers=alice2).json()["code"] == "request.too_many"
        check.seen |= check2.seen
    # *Thorough*: the model thinks first, and its reasoning comes as events of its own, never in the answer
    thinks = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text="<think>Article 2 gives the price.</think>The price is EUR 412.500,00 [1]."))
    with TestClient(create_app(thinks, documents=FakeDocuments(owner=ALICE), load_documents=False, auth=auth,
                               conversations=FakeConversations())) as c3:
        check3 = Checked(c3, "answers")
        check3.kept = check.kept
        check3("POST", asking, 200, at(), "stream_thorough", tidy=tidy, json={**ask, "document_ids": [DOC], "thinking": True},
               headers=as_user(kc2, ALICE))
    thorough = check.kept.answers["stream_thorough"]["body"]
    assert [e["data"]["text"] for e in thorough if e["event"] == "thinking"] == ["Article 2 gives the price."] and thorough[-1]["data"]["reasoning"]
    check.kept.check()


def test_the_keep_periods_are_one_list():
    """A period is asked and answered as a fixed list (``KeepPeriod``) and counted by ``KEEP_PERIODS``: one added to
    the one and not the other would refuse a setting the office has, or fail who is signed in."""
    from typing import get_args

    from suveryn_api_gateway.cases import KEEP_PERIODS, KeepPeriod

    assert get_args(KeepPeriod) == tuple(KEEP_PERIODS)



def test_every_line_the_gateway_writes_in_an_access_log_is_described():
    """The access log's actions and details are described (suveryn-tracker#250): each action the gateway writes is one
    ``CaseAction`` names, and each detail one ``EventDetail`` has. Read from the code, so a new line can't be missed."""
    import ast
    import pathlib
    from typing import get_args

    from suveryn_api_gateway.cases import CaseAction, EventDetail

    package = pathlib.Path(__import__("suveryn_api_gateway").__file__).parent
    actions, details, calls = set(), set(), 0

    def words(node) -> set[str]:  # an action as written: a word, or one of two (``"a" if … else "b"``)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return words(node.body) | words(node.orelse)
        raise AssertionError(f"an action that isn't written as a word: {ast.unparse(node)}")

    for module in [*package.glob("*.py"), *(package / "routes").glob("*.py")]:
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name == "log_access" and len(node.args) >= 3 or name == "log" and module.name == "cases.py" and len(node.args) == 4:
                calls += 1
                actions |= words(node.args[2])
                for part in ast.walk(node.args[3]) if len(node.args) > 3 else []:
                    if isinstance(part, ast.Dict):
                        details |= {k.value for k in part.keys if isinstance(k, ast.Constant)}
    assert calls > 25 and actions and details
    assert actions <= set(get_args(CaseAction)), sorted(actions - set(get_args(CaseAction)))
    assert details <= set(EventDetail.model_fields), sorted(details - set(EventDetail.model_fields))


def test_a_line_kept_in_another_shape_is_still_read():
    """A line of the access log is read back with what is known of its detail: one member kept in another shape is
    left out, never the line, and only what the line said is sent."""
    from suveryn_api_gateway.cases import EventDetail

    assert EventDetail.kept({"user": "bob-sub", "role": "reader"}).model_dump() == {"user": "bob-sub", "role": "reader"}
    assert EventDetail.kept({"user": "bob-sub", "role": "owner", "colour": "blue"}).model_dump() == {"user": "bob-sub"}
    assert EventDetail.kept({"keep_until": None}).model_dump() == {"keep_until": None}  # said: kept until deleted by hand
    assert EventDetail.kept(None).model_dump() == {} and EventDetail.kept("closed").model_dump() == {}
