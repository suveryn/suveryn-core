"""suveryn-tracker#5: saved conversations, per user.

The API tests use an in-memory store with the same methods as ``ConversationStore``; the store
tests at the end run against a real PostgreSQL and are skipped unless SUVERYN_TEST_DATABASE_URL is set.
"""

import os
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.conversations import (
    Conversation,
    ConversationIn,
    ConversationSettings,
    ConversationStore,
    ConversationSummary,
    cited_documents,
    redact,
)
from suveryn_harness import LlamaServerClient, LLMSettings
from test_auth import SETTINGS, FakeKeycloak
from test_documents import llm_transport

ALICE, BOB = "user-a", "user-b"
TURNS = [
    {"id": "t1", "role": "user", "text": "Wat is de koopprijs?", "attachments": []},
    {"id": "t2", "role": "assistant", "text": "€ 345.000 [1]", "status": "done", "grounded": True,
     "citations": [{"n": 1, "text": "De koopprijs bedraagt € 345.000."}]},
]
BODY = {"title": "Wat is de koopprijs?", "turns": TURNS}


class FakeConversations:
    """In-memory stand-in for ``ConversationStore``."""

    def __init__(self):
        self.rows: dict[uuid.UUID, dict] = {}
        self.keep = "manual"  # the gateway sets the office's period before listing (routes/common.py)

    def purge(self):
        return 0

    # unfinished cleanings after a document's deletion (routes/documents.py): (owner, document) -> (delete, case)
    cleanups: dict

    def note_cleanup(self, owner, document_id, delete_conversations, case_id):
        self.__dict__.setdefault("cleanups", {})[(owner, document_id)] = (delete_conversations, case_id)

    def cleanup_done(self, owner, document_id):
        self.__dict__.setdefault("cleanups", {}).pop((owner, document_id), None)

    def finish_cleanups(self):
        pending = list(self.__dict__.setdefault("cleanups", {}).items())
        for (owner, did), (delete, case_id) in pending:
            self.remove_document(owner, did, delete, case_id)
            self.cleanup_done(owner, did)
        return len(pending)

    def summaries_all(self, owner, case_ids):
        rows = sorted((r for r in self.rows.values() if (r["owner"] == owner and (r["case_id"] is None or r["case_id"] in case_ids))
                       or (r["shared"] and r["case_id"] in case_ids)),
                      key=lambda r: r["updated_at"], reverse=True)
        return [self._summary(r) for r in rows]

    def summaries(self, owner, case_id=None):
        rows = sorted((r for r in self.rows.values() if r["case_id"] == case_id
                       and (r["owner"] == owner or (r["shared"] and case_id is not None))),
                      key=lambda r: r["updated_at"], reverse=True)
        return [self._summary(r) for r in rows]

    @staticmethod
    def _summary(r):
        return ConversationSummary(**{k: r[k] for k in ("id", "title", "created_at", "updated_at", "owner", "shared")},
                                   case_id=str(r["case_id"]) if r["case_id"] else None, messages=len(r["turns"]),
                                   pinned=bool(r.get("pinned")))

    def get(self, cid, owner):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner:
            return None
        return Conversation(**self._summary(r).model_dump(), turns=r["turns"])

    def get_shared(self, cid):
        r = self.rows.get(cid)
        if not r or not r["shared"] or r["case_id"] is None:
            return None
        return Conversation(**self._summary(r).model_dump(), turns=r["turns"])

    def rename(self, cid, owner, title):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner:
            return None
        r["title"], r["renamed"] = title, True
        return self._summary(r)

    def set_pinned(self, cid, owner, pinned):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner or r["case_id"] is not None:
            return None
        r["pinned"] = pinned
        return self._summary(r)

    def move(self, cid, owner, case_id):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner or r["case_id"] is not None:
            return None
        r.update(case_id=case_id, shared=False, pinned=False)
        return self._summary(r)

    def unshare_case(self, case_id):
        rows = [r for r in self.rows.values() if str(r["case_id"]) == str(case_id) and r["shared"]]
        for r in rows:
            r["shared"] = False
        return len(rows)

    def set_shared(self, cid, owner, shared):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner or r["case_id"] is None:
            return None
        r["shared"] = shared
        return self._summary(r)

    def save(self, cid, owner, body: ConversationIn, gone=None):
        old = self.rows.get(cid)
        if old and old["owner"] != owner:
            return False
        now = datetime.now(UTC)
        turns = [t.model_dump() for t in body.turns]
        if gone is not None:
            redact(turns, gone)
        self.rows[cid] = {"id": str(cid), "owner": owner, "title": old["title"] if old and old.get("renamed") else body.title,
                          "renamed": bool(old and old.get("renamed")), "pinned": bool(old and old.get("pinned")), "turns": turns,
                          "created_at": old["created_at"] if old else now, "updated_at": now,
                          "case_id": old["case_id"] if old else (uuid.UUID(body.case_id) if body.case_id else None),
                          "shared": old["shared"] if old else False}
        return True

    def using_document(self, owner, document_id, case_id=None):
        rows = sorted((r for r in self.rows.values() if (r["case_id"] == case_id if case_id is not None else r["owner"] == owner)),
                      key=lambda r: r["updated_at"], reverse=True)
        return [self._summary(r) for r in rows if str(document_id) in cited_documents(r["turns"])]

    def remove_document(self, owner, document_id, delete_conversations=False, case_id=None):
        hits = self.using_document(owner, document_id, case_id)
        for h in hits:
            if delete_conversations:
                del self.rows[uuid.UUID(h.id)]
            else:
                redact(self.rows[uuid.UUID(h.id)]["turns"], lambda d: d == str(document_id))
        return len(hits)

    def delete(self, cid, owner):
        if cid in self.rows and self.rows[cid]["owner"] == owner:
            del self.rows[cid]
            return True
        return False

    def delete_all(self, owner):
        mine = [c for c, r in self.rows.items() if r["owner"] == owner]
        for c in mine:
            del self.rows[c]
        return len(mine)

    def delete_case(self, case_id):
        gone = [c for c, r in self.rows.items() if r["case_id"] == case_id]
        for c in gone:
            del self.rows[c]
        return len(gone)


@pytest.fixture
def setup():
    kc = FakeKeycloak()
    store = FakeConversations()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=auth, conversations=store)) as c:
        yield c, kc, store


def as_user(kc: FakeKeycloak, sub: str) -> dict:
    return {"Authorization": f"Bearer {kc.tokens(over={'sub': sub})['access_token']}"}


def test_save_list_open_and_delete(setup):
    c, kc, _ = setup
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())
    assert c.get("/v1/conversations", headers=alice).json() == []
    assert c.put(f"/v1/conversations/{cid}", json=BODY, headers=alice).status_code == 204
    listed = c.get("/v1/conversations", headers=alice).json()
    assert [(x["id"], x["title"]) for x in listed] == [(cid, "Wat is de koopprijs?")]
    assert "turns" not in listed[0]  # the list carries no content
    opened = c.get(f"/v1/conversations/{cid}", headers=alice).json()
    assert opened["turns"] == TURNS  # saved as the UI sent it, extra fields included
    second = {**BODY, "turns": [*TURNS, {"id": "t3", "role": "user", "text": "En de notariskosten?"}]}
    assert c.put(f"/v1/conversations/{cid}", json=second, headers=alice).status_code == 204  # replaces
    assert len(c.get(f"/v1/conversations/{cid}", headers=alice).json()["turns"]) == 3
    assert c.delete(f"/v1/conversations/{cid}", headers=alice).status_code == 204
    assert c.get(f"/v1/conversations/{cid}", headers=alice).status_code == 404


def test_a_database_that_cant_be_reached_is_a_503_with_a_sentence(setup):
    """Pod check of f0ff96c: a stopped PostgreSQL gave a bare HTTP 500."""
    import psycopg

    c, kc, store = setup

    def down(*a, **k):
        raise psycopg.OperationalError("connection to server on socket /run/postgresql failed")

    store.summaries = down
    r = c.get("/v1/conversations", headers=as_user(kc, ALICE))
    assert r.status_code == 503 and r.json()["detail"] == "The database can't be reached right now. Try again shortly."
    assert "socket" not in r.text  # the server's own error text isn't sent


def test_another_users_conversation_is_unknown(setup):
    c, kc, store = setup
    alice, bob, cid = as_user(kc, ALICE), as_user(kc, BOB), str(uuid.uuid4())
    c.put(f"/v1/conversations/{cid}", json=BODY, headers=alice)
    assert c.get("/v1/conversations", headers=bob).json() == []
    assert c.get(f"/v1/conversations/{cid}", headers=bob).status_code == 404
    assert c.put(f"/v1/conversations/{cid}", json={**BODY, "title": "overwritten"}, headers=bob).status_code == 404
    assert c.delete(f"/v1/conversations/{cid}", headers=bob).status_code == 404
    assert c.delete("/v1/conversations", headers=bob).json() == {"deleted": 0}
    assert store.rows[uuid.UUID(cid)]["title"] == "Wat is de koopprijs?"


def test_delete_history_removes_only_your_own(setup):
    c, kc, store = setup
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    for who in (alice, alice, bob):
        c.put(f"/v1/conversations/{uuid.uuid4()}", json=BODY, headers=who)
    assert c.delete("/v1/conversations", headers=alice).json() == {"deleted": 2}
    assert c.get("/v1/conversations", headers=alice).json() == []
    assert len(c.get("/v1/conversations", headers=bob).json()) == 1


def test_bad_requests(setup):
    c, kc, _ = setup
    alice = as_user(kc, ALICE)
    assert c.get("/v1/conversations").status_code == 401
    assert c.get("/v1/conversations/not-a-uuid", headers=alice).status_code == 422
    url = f"/v1/conversations/{uuid.uuid4()}"
    assert c.put(url, json={"title": "", "turns": TURNS}, headers=alice).status_code == 422
    assert c.put(url, json={"title": "x", "turns": []}, headers=alice).status_code == 422
    assert c.put(url, json={"title": "x", "turns": [{"role": "system", "text": "x"}]}, headers=alice).status_code == 422
    huge = {"title": "x", "turns": [{"role": "user", "text": "a" * 150_000}] * 15}  # over 2 MB
    assert c.put(url, json=huge, headers=alice).status_code == 413


def test_without_a_database_history_is_unavailable():
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled())) as c:
        assert c.get("/v1/conversations").status_code == 503
        assert c.get("/health").json()["history"] == {"status": "unavailable", "detail": None}


def test_health_reports_history_ready(setup):
    c, _, _ = setup
    assert c.get("/health").json()["history"]["status"] == "ready"


def test_keep_period_is_one_of_the_offices_choices(monkeypatch):
    """The data lifecycle (suveryn-tracker#31): the same periods as cases, nothing chosen for the office."""
    monkeypatch.setenv("SUVERYN_CONVERSATIONS_KEEP", "6m")
    assert ConversationSettings.from_env().max_age_days == 183
    monkeypatch.setenv("SUVERYN_CONVERSATIONS_KEEP", "")
    assert ConversationSettings.from_env().keep == "manual"
    assert ConversationSettings.from_env().max_age_days is None
    for bad in ("30", "2y", "forever"):
        monkeypatch.setenv("SUVERYN_CONVERSATIONS_KEEP", bad)
        with pytest.raises(ValueError):
            ConversationSettings.from_env()


# ------------------------------------------------------------------ against a real PostgreSQL

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


@pytest.fixture
def store():
    s = ConversationStore(ConversationSettings(database_url=URL))
    s._execute("DELETE FROM conversations WHERE owner IN (%s, %s)", (ALICE, BOB))
    yield s
    s._execute("DELETE FROM conversations WHERE owner IN (%s, %s)", (ALICE, BOB))
    s.close()


@needs_db
def test_store_round_trip_and_ownership(store):
    cid, body = uuid.uuid4(), ConversationIn(**BODY)
    assert store.save(cid, ALICE, body)
    assert not store.save(cid, BOB, ConversationIn(**{**BODY, "title": "overwritten"}))
    assert store.get(cid, BOB) is None and store.summaries(BOB) == []
    got = store.get(cid, ALICE)
    assert got.title == "Wat is de koopprijs?" and got.turns == TURNS
    assert [s.id for s in store.summaries(ALICE)] == [str(cid)]
    assert not store.delete(cid, BOB) and store.delete(cid, ALICE)
    assert store.get(cid, ALICE) is None


@needs_db
def test_store_keeps_a_conversation_in_its_case(store):
    """suveryn-tracker#10: listed with its case, not in the personal space, and it doesn't move on a later save."""
    case, in_case, personal = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert store.save(in_case, ALICE, ConversationIn(**{**BODY, "case_id": str(case)}))
    assert store.save(personal, ALICE, ConversationIn(**BODY))
    assert [s.id for s in store.summaries(ALICE)] == [str(personal)]
    assert [(s.id, s.case_id) for s in store.summaries(ALICE, case)] == [(str(in_case), str(case))]
    assert store.get(in_case, ALICE).case_id == str(case) and store.get(personal, ALICE).case_id is None
    store.save(in_case, ALICE, ConversationIn(**{**BODY, "title": "later"}))  # no case_id: stays where it was
    assert [s.title for s in store.summaries(ALICE, case)] == ["later"]
    assert store.delete_case(case) == 1 and store.summaries(ALICE, case) == []


@needs_db
def test_store_lists_newest_first_and_deletes_all(store):
    first, second = uuid.uuid4(), uuid.uuid4()
    store.save(first, ALICE, ConversationIn(**BODY))
    store.save(second, ALICE, ConversationIn(**BODY))
    store.save(first, ALICE, ConversationIn(**BODY))  # changed last
    assert [s.id for s in store.summaries(ALICE)] == [str(first), str(second)]
    store.save(uuid.uuid4(), BOB, ConversationIn(**BODY))
    assert store.delete_all(ALICE) == 2
    assert len(store.summaries(BOB)) == 1


@needs_db
def test_store_age_cap(store):
    old, new = uuid.uuid4(), uuid.uuid4()
    store.save(old, ALICE, ConversationIn(**BODY))
    store.save(new, ALICE, ConversationIn(**BODY))
    store._execute("UPDATE conversations SET updated_at = now() - interval '200 days' WHERE id = %s", (old,))
    capped = ConversationStore(ConversationSettings(database_url=URL, keep="6m"))  # purges on start
    try:
        assert [s.id for s in capped.summaries(ALICE)] == [str(new)]
        assert store.get(old, ALICE) is None  # deleted, not only hidden
    finally:
        capped.close()


@needs_db
def test_store_hides_expired_conversations_and_leaves_deleting_them_to_the_sweep(store):
    """External review, pass 6: a listing no longer runs a DELETE; the expired one is left out, and purge (the
    hourly sweep's part) deletes it."""
    capped = ConversationStore(ConversationSettings(database_url=URL, keep="6m"))
    try:
        old = uuid.uuid4()
        store.save(old, ALICE, ConversationIn(**BODY))
        store._execute("UPDATE conversations SET updated_at = now() - interval '200 days' WHERE id = %s", (old,))
        assert str(old) not in [s.id for s in capped.summaries(ALICE)] + [s.id for s in capped.summaries_all(ALICE, [])]
        assert store._execute("SELECT count(*) FROM conversations WHERE id = %s", (old,)).fetchone()[0] == 1  # still there
        assert capped.purge() >= 1
        assert store._execute("SELECT count(*) FROM conversations WHERE id = %s", (old,)).fetchone()[0] == 0
    finally:
        capped.close()


@needs_db
def test_store_lists_all_of_the_owners_conversations_across_cases(store):
    """The column's Recent and the Conversations overview (docs/design/chat-ui.md §2, §4): own conversations in
    the personal space and in readable cases, and the ones colleagues shared with those cases."""
    mine_personal, mine_in_case, mine_elsewhere, others = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    case_a, case_b = uuid.uuid4(), uuid.uuid4()
    store.save(mine_personal, ALICE, ConversationIn(**BODY))
    store.save(mine_in_case, ALICE, ConversationIn(**BODY, case_id=str(case_a)))
    store.save(mine_elsewhere, ALICE, ConversationIn(**BODY, case_id=str(case_b)))
    store.save(others, BOB, ConversationIn(**BODY, case_id=str(case_a)))
    store.set_shared(others, BOB, True)
    found = {s.id: s for s in store.summaries_all(ALICE, [case_a])}
    assert set(found) == {str(mine_personal), str(mine_in_case), str(others)}  # not the case she can't read
    assert found[str(others)].owner == BOB and found[str(others)].shared
    assert found[str(mine_personal)].messages == len(BODY["turns"])
    store.set_shared(others, BOB, False)
    assert str(others) not in {s.id for s in store.summaries_all(ALICE, [case_a])}  # no longer shared: Bob's alone


@needs_db
def test_store_keep_period_changed_by_an_administrator(store):
    """The gateway sets ``keep`` from the dashboard's setting; a shorter period deletes at the next listing."""
    old, new = uuid.uuid4(), uuid.uuid4()
    store.save(old, ALICE, ConversationIn(**BODY))
    store.save(new, ALICE, ConversationIn(**BODY))
    store._execute("UPDATE conversations SET updated_at = now() - interval '200 days' WHERE id = %s", (old,))
    assert store.keep == "manual" and {s.id for s in store.summaries(ALICE)} == {str(old), str(new)}
    store.keep = "6m"
    assert [s.id for s in store.summaries(ALICE)] == [str(new)]
    assert store.get(old, ALICE) is None


# ---------------------------------------------------------------- deleted documents (suveryn-tracker#12)

DOC, OTHER = str(uuid.uuid4()), str(uuid.uuid4())


def cited_turns(doc=DOC):
    return [
        {"id": "u1", "role": "user", "text": "Wat is de koopprijs?",
         "attachments": [{"key": "a", "filename": "akte-peeters.pdf", "status": "ready", "documentId": doc}]},
        {"id": "a1", "role": "assistant", "text": "€ 345.000 [1], verkoper Peeters [2]", "status": "done", "grounded": True,
         "citations": [{"text": "De koopprijs bedraagt € 345.000.", "source": {"document_id": doc, "page": 3,
                                                                               "location": "p. 3 · Artikel 2 - Koopprijs"}},
                       {"text": "Verkoper: Jan Peeters.", "source": {"document_id": OTHER, "page": 1, "location": "p. 1"}}]},
    ]


def test_redact_takes_out_passages_and_names_of_deleted_documents_only():
    turns = cited_turns()
    assert cited_documents(turns) == {DOC, OTHER}
    assert redact(turns, lambda d: d == DOC) is True
    gone, kept = turns[1]["citations"]
    assert gone == {"text": "", "source": {"document_id": DOC, "page": 3, "location": None}, "removed": True}
    assert kept["text"] == "Verkoper: Jan Peeters." and "removed" not in kept
    assert turns[0]["attachments"][0]["filename"] == "" and turns[0]["attachments"][0]["removed"] is True
    assert turns[1]["text"] == "€ 345.000 [1], verkoper Peeters [2]"  # the answer stays; the UI offers to delete it
    assert redact(turns, lambda d: d == DOC) is False  # idempotent


def test_a_document_a_question_was_asked_about_is_redacted_too():
    """Ask about (docs/design/chat-ui.md §10): the choice saved with a question names documents too."""
    turns = [{"id": "u1", "role": "user", "text": "What is the price?", "attachments": [],
              "about": [{"documentId": DOC, "filename": "deed-north.pdf"}, {"documentId": OTHER, "filename": "lease.pdf"}]}]
    assert cited_documents(turns) == {DOC, OTHER}
    assert redact(turns, lambda d: d == DOC) is True
    assert turns[0]["about"] == [{"documentId": DOC, "filename": "", "removed": True},
                                 {"documentId": OTHER, "filename": "lease.pdf"}]


class FakeDocs:
    state, error = "ready", None

    def __init__(self):
        self.ids = {DOC, OTHER}

    def delete(self, document_id, scope):
        if document_id in self.ids:
            self.ids.discard(document_id)
            return True
        return False

    def existing(self, ids, scope):
        return {i for i in ids if i in self.ids}

    def stop(self):
        pass


@pytest.fixture
def with_docs():
    kc, store, docs = FakeKeycloak(), FakeConversations(), FakeDocs()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=store)) as c:
        yield c, as_user(kc, ALICE), store, docs


def test_deleting_a_document_takes_its_passages_out_of_saved_conversations(with_docs):
    c, alice, store, _ = with_docs
    cid = str(uuid.uuid4())
    assert c.put(f"/v1/conversations/{cid}", json={"title": "Prijs", "turns": cited_turns()}, headers=alice).status_code == 204
    assert [s["id"] for s in c.get(f"/v1/documents/{DOC}/conversations", headers=alice).json()] == [cid]
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 204
    saved = c.get(f"/v1/conversations/{cid}", headers=alice).json()["turns"]
    assert "345.000." not in str(saved[1]["citations"]) and "Artikel 2" not in str(saved) and "akte-peeters" not in str(saved)
    assert "Jan Peeters" in str(saved[1]["citations"])  # the other document's passage stays
    assert c.get(f"/v1/documents/{OTHER}/conversations", headers=alice).json()[0]["id"] == cid


def test_deleting_a_document_can_delete_the_conversations_that_used_it(with_docs):
    c, alice, store, _ = with_docs
    cid, other = str(uuid.uuid4()), str(uuid.uuid4())
    c.put(f"/v1/conversations/{cid}", json={"title": "Prijs", "turns": cited_turns()}, headers=alice)
    c.put(f"/v1/conversations/{other}", json=BODY, headers=alice)  # doesn't use the document
    assert c.delete(f"/v1/documents/{DOC}", params={"conversations": "delete"}, headers=alice).status_code == 204
    assert [s["id"] for s in c.get("/v1/conversations", headers=alice).json()] == [other]
    assert c.delete(f"/v1/documents/{OTHER}", params={"conversations": "everything"}, headers=alice).status_code == 422


def test_a_tab_still_open_cant_save_the_passages_back(with_docs):
    c, alice, store, docs = with_docs
    docs.ids.discard(DOC)  # deleted in another tab
    cid = str(uuid.uuid4())
    assert c.put(f"/v1/conversations/{cid}", json={"title": "Prijs", "turns": cited_turns()}, headers=alice).status_code == 204
    saved = store.rows[uuid.UUID(cid)]["turns"]
    assert saved[1]["citations"][0]["removed"] is True and saved[1]["citations"][0]["text"] == ""
    assert saved[1]["citations"][1]["text"] == "Verkoper: Jan Peeters."


def test_a_document_isnt_deleted_while_saved_conversations_cant_be_reached(with_docs):
    """Audit of 21 October 2026, finding 3: before, the document went and its passages stayed in the conversations."""
    from suveryn_api_gateway.routes.common import Database

    c, alice, store, docs = with_docs
    cid = str(uuid.uuid4())
    c.put(f"/v1/conversations/{cid}", json={"title": "Price", "turns": cited_turns()}, headers=alice)

    def unreachable():
        raise OSError("no database")

    c.app.state.history = Database("conversations", connect=unreachable)
    r = c.delete(f"/v1/documents/{DOC}", headers=alice)
    assert r.status_code == 503 and DOC in docs.ids  # nothing deleted
    c.app.state.history = Database("conversations", store=store)
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 204
    assert store.rows[uuid.UUID(cid)]["turns"][1]["citations"][0]["removed"] is True


def test_a_cleaning_that_fails_after_the_deletion_is_finished_by_the_sweep(with_docs):
    c, alice, store, docs = with_docs
    cid = str(uuid.uuid4())
    c.put(f"/v1/conversations/{cid}", json={"title": "Price", "turns": cited_turns()}, headers=alice)
    real = store.remove_document

    def broken(*a, **k):
        raise OSError("connection lost")

    store.remove_document = broken
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 202  # deleted; the cleaning is still to do
    assert DOC not in docs.ids and store.cleanups == {(ALICE, uuid.UUID(DOC)): (False, None)}
    store.remove_document = real
    assert store.finish_cleanups() == 1 and store.cleanups == {}  # what the hourly sweep does
    assert store.rows[uuid.UUID(cid)]["turns"][1]["citations"][0]["removed"] is True


def test_a_save_that_crosses_a_deletion_doesnt_keep_the_passages(with_docs):
    """The document still existed when the save was checked, and was deleted (and its conversations cleaned)
    before the save was written: the save takes them out itself."""
    c, alice, store, docs = with_docs
    checks = []
    real = docs.existing

    def deleted_meanwhile(ids, scope):
        checks.append(1)
        if len(checks) == 2:
            docs.ids.discard(DOC)  # deleted between the check and the save
        return real(ids, scope)

    docs.existing = deleted_meanwhile
    cid = str(uuid.uuid4())
    assert c.put(f"/v1/conversations/{cid}", json={"title": "Price", "turns": cited_turns()}, headers=alice).status_code == 204
    saved = store.rows[uuid.UUID(cid)]["turns"]
    assert saved[1]["citations"][0]["removed"] is True and saved[1]["citations"][1]["text"] == "Verkoper: Jan Peeters."


@needs_db
def test_store_cleans_or_deletes_conversations_of_a_deleted_document(store):
    used, unused, bobs = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.save(used, ALICE, ConversationIn(title="Prijs", turns=cited_turns()))
    store.save(unused, ALICE, ConversationIn(**BODY))
    store.save(bobs, BOB, ConversationIn(title="Prijs", turns=cited_turns()))  # same document id, another owner
    assert [s.id for s in store.using_document(ALICE, uuid.UUID(DOC))] == [str(used)]
    before = store.get(used, ALICE).updated_at
    assert store.remove_document(ALICE, uuid.UUID(DOC)) == 1
    after = store.get(used, ALICE)
    assert after.turns[1]["citations"][0] == {"text": "", "source": {"document_id": DOC, "page": 3, "location": None},
                                              "removed": True}
    assert after.updated_at == before  # cleaned, not "changed by the user": the sidebar order stays
    assert store.get(bobs, BOB).turns[1]["citations"][0]["text"]  # another owner's conversation is untouched
    assert store.remove_document(ALICE, uuid.UUID(OTHER), delete_conversations=True) == 1
    assert [s.id for s in store.summaries(ALICE)] == [str(unused)]
    late = uuid.uuid4()  # saved from a tab that still held the passages
    store.save(late, ALICE, ConversationIn(title="Prijs", turns=cited_turns()), gone=lambda d: d == DOC)
    cits = store.get(late, ALICE).turns[1]["citations"]
    assert cits[0]["removed"] and cits[0]["text"] == "" and cits[1]["text"] == "Verkoper: Jan Peeters."


@needs_db
def test_store_unshares_every_conversation_of_a_case(store):
    """§11: a case made strictly confidential unshares its conversations; their owners keep them."""
    case, other, a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.save(a, ALICE, ConversationIn(**{**BODY, "case_id": str(case)}))
    store.save(b, BOB, ConversationIn(**{**BODY, "case_id": str(case)}))
    store.save(c, ALICE, ConversationIn(**{**BODY, "case_id": str(other)}))
    for cid, owner in ((a, ALICE), (b, BOB), (c, ALICE)):
        store.set_shared(cid, owner, True)
    assert store.unshare_case(case) == 2 and store.unshare_case(case) == 0
    assert store.get_shared(a) is None and store.get(a, ALICE) is not None
    assert store.get_shared(c) is not None  # another case's stays shared


@needs_db
def test_store_renames_pins_and_moves_a_personal_conversation(store):
    """§3 and §4: the owner's title stays over later saves; a pin only for a personal conversation; moved into a
    case, it isn't shared and has no pin of its own."""
    case, cid, in_case = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.save(cid, ALICE, ConversationIn(**BODY))
    store.save(in_case, ALICE, ConversationIn(**{**BODY, "case_id": str(case)}))
    assert store.rename(cid, BOB, "Bob's") is None
    assert store.rename(cid, ALICE, "Sale, the price").title == "Sale, the price"
    store.save(cid, ALICE, ConversationIn(**BODY))
    assert store.get(cid, ALICE).title == "Sale, the price"
    assert store.set_pinned(cid, BOB, True) is None and store.set_pinned(in_case, ALICE, True) is None
    assert store.set_pinned(cid, ALICE, True).pinned and store.summaries(ALICE)[0].pinned
    assert store.get(cid, ALICE).pinned
    assert store.move(cid, BOB, case) is None and store.move(in_case, ALICE, uuid.uuid4()) is None
    moved = store.move(cid, ALICE, case)
    assert moved.case_id == str(case) and not moved.pinned and not moved.shared
    assert store.summaries(ALICE) == [] and {s.id for s in store.summaries(ALICE, case)} == {str(cid), str(in_case)}
    assert store.get(cid, ALICE).turns == TURNS


def test_store_shares_a_conversation_with_its_case_and_cleans_every_members(store):
    """Stage 4 of docs/design/cases.md: shared conversations, and a case's document taken out of
    everyone's conversations when it is deleted."""
    case, alices, bobs, personal = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.save(alices, ALICE, ConversationIn(**{**BODY, "case_id": str(case)}))
    store.save(bobs, BOB, ConversationIn(**{**BODY, "case_id": str(case)}))
    store.save(personal, ALICE, ConversationIn(**BODY))
    assert [s.id for s in store.summaries(BOB, case)] == [str(bobs)]  # alice's is private
    assert store.get_shared(alices) is None
    assert store.set_shared(alices, BOB, True) is None       # not his
    assert store.set_shared(personal, ALICE, True) is None   # not in a case
    shared = store.set_shared(alices, ALICE, True)
    assert shared.shared and shared.owner == ALICE
    assert sorted((s.id, s.owner, s.shared) for s in store.summaries(BOB, case)) == sorted(
        [(str(bobs), BOB, False), (str(alices), ALICE, True)])
    assert store.get_shared(alices).turns == TURNS and store.get(alices, BOB) is None  # readable, not his
    assert store.summaries(ALICE) == [store.summaries(ALICE)[0]] and store.summaries(ALICE)[0].id == str(personal)
    assert store.set_shared(alices, ALICE, False).shared is False and store.get_shared(alices) is None
    # the case's document is cited in bob's conversation too: everyone's are cleaned
    doc = "11111111-1111-1111-1111-111111111111"
    turns = [{"role": "user", "text": "?"}, {"role": "assistant", "text": "x [1]",
             "citations": [{"n": 1, "text": "secret", "source": {"document_id": doc, "page": 1}}]}]
    store.save(bobs, BOB, ConversationIn(title="b", turns=turns))
    store.save(alices, ALICE, ConversationIn(title="a", turns=turns))
    assert sorted(s.owner for s in store.using_document(ALICE, uuid.UUID(doc), case)) == [ALICE, BOB]
    assert [s.owner for s in store.using_document(ALICE, uuid.UUID(doc))] == [ALICE]  # personal: own only
    assert store.remove_document(ALICE, uuid.UUID(doc), case_id=case) == 2
    assert store.get(bobs, BOB).turns[1]["citations"][0]["text"] == ""
    assert store.remove_document(ALICE, uuid.UUID(doc), delete_conversations=True, case_id=case) == 2  # both, whoever's
    assert store.delete_case(case) == 0


@needs_db
def test_store_finishes_a_cleaning_a_deletion_left_unfinished(store):
    """Audit of 21 October 2026, finding 3: the cleaning is noted before the document goes, and done after."""
    cid, did = uuid.uuid4(), uuid.UUID(DOC)
    store.save(cid, ALICE, ConversationIn(title="Price", turns=cited_turns()))
    store._execute("DELETE FROM conversation_cleanups WHERE owner IN (%s, %s)", (ALICE, BOB))
    store.note_cleanup(ALICE, did, False, None)
    store.note_cleanup(ALICE, did, True, None)  # asked again, to delete the conversations: the stronger wins
    assert store._execute("SELECT delete_conversations FROM conversation_cleanups WHERE owner = %s", (ALICE,)).fetchall() == [(True,)]
    store._execute("UPDATE conversation_cleanups SET delete_conversations = false WHERE owner = %s", (ALICE,))
    assert store.finish_cleanups() >= 1
    assert store.get(cid, ALICE).turns[1]["citations"][0]["removed"] is True
    assert store._execute("SELECT count(*) FROM conversation_cleanups WHERE owner = %s", (ALICE,)).fetchone()[0] == 0


@needs_db
def test_the_turn_count_and_cited_documents_are_kept_on_save_and_found_without_the_turns(store):
    """Lists and "which conversations cite this document" no longer open the turns (database review of
    510c87b): the count and the documents are kept beside them on every save."""
    cid = uuid.uuid4()
    assert store.save(cid, ALICE, ConversationIn(title="Koopprijs", turns=cited_turns()))
    messages, documents = store._execute("SELECT messages, documents FROM conversations WHERE id = %s", (cid,)).fetchone()
    assert messages == 2 and documents == sorted([DOC, OTHER])
    assert store.summaries(ALICE)[0].messages == 2
    assert [s.id for s in store.using_document(ALICE, uuid.UUID(DOC))] == [str(cid)]
    assert store.using_document(BOB, uuid.UUID(DOC)) == []  # someone else's conversation isn't searched
    assert store.save(cid, ALICE, ConversationIn(title="Koopprijs", turns=cited_turns()[:1]))  # a later save
    assert store._execute("SELECT messages, documents FROM conversations WHERE id = %s", (cid,)).fetchone() == (1, [DOC])
    assert store.using_document(ALICE, uuid.UUID(OTHER)) == []


@needs_db
def test_conversations_saved_before_the_count_was_kept_get_it_on_start(store):
    cid = uuid.uuid4()
    assert store.save(cid, ALICE, ConversationIn(title="Koopprijs", turns=cited_turns()))
    store._execute("UPDATE conversations SET messages = NULL, documents = NULL WHERE id = %s", (cid,))  # as an older version left it
    again = ConversationStore(ConversationSettings(database_url=URL))  # the gateway starting
    try:
        assert again._execute("SELECT messages, documents FROM conversations WHERE id = %s", (cid,)).fetchone() == (2, sorted([DOC, OTHER]))
        assert again.fill_in() == 0  # nothing left to do on the next start
    finally:
        again.close()
