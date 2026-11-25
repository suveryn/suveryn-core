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
    ConversationSettings,
    ConversationStore,
    cited_documents,
    redact,
)
from suveryn_harness import LlamaServerClient, LLMSettings
from conftest import FakeConversations, kept
from test_auth import SETTINGS, FakeKeycloak
from test_documents import llm_transport

ALICE, BOB = "user-a", "user-b"
TURNS = [
    {"id": "t1", "role": "user", "text": "Wat is de koopprijs?", "attachments": []},
    {"id": "t2", "role": "assistant", "text": "€ 345.000 [1]", "status": "done", "grounded": True,
     "citations": [{"n": 1, "text": "De koopprijs bedraagt € 345.000."}]},
]


def said(turns: list[dict]) -> list[tuple[str, str]]:
    """Who said what, in order: the turns as kept, without what the server adds."""
    return [(t["role"], t["text"]) for t in turns]


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


def test_list_open_and_delete(setup):
    c, kc, store = setup
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())
    assert c.get("/v1/conversations", headers=alice).json() == []
    assert kept(store, cid, ALICE, TURNS)
    listed = c.get("/v1/conversations", headers=alice).json()
    assert [(x["id"], x["title"]) for x in listed] == [(cid, "Wat is de koopprijs?")]
    assert "turns" not in listed[0]  # the list carries no content
    opened = c.get(f"/v1/conversations/{cid}", headers=alice).json()
    assert said(opened["turns"]) == said(TURNS) and opened["turns"][1]["citations"] == TURNS[1]["citations"]
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
    bob, cid = as_user(kc, BOB), str(uuid.uuid4())
    kept(store, cid, ALICE, TURNS)
    assert c.get("/v1/conversations", headers=bob).json() == []
    assert c.get(f"/v1/conversations/{cid}", headers=bob).status_code == 404
    assert c.delete(f"/v1/conversations/{cid}", headers=bob).status_code == 404
    assert c.delete("/v1/conversations", headers=bob).json() == {"deleted": 0}
    assert store.rows[uuid.UUID(cid)]["title"] == "Wat is de koopprijs?"


def test_delete_history_removes_only_your_own(setup):
    c, kc, store = setup
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    for who in (ALICE, ALICE, BOB):
        kept(store, uuid.uuid4(), who, TURNS)
    assert c.delete("/v1/conversations", headers=alice).json() == {"deleted": 2}
    assert c.get("/v1/conversations", headers=alice).json() == []
    assert len(c.get("/v1/conversations", headers=bob).json()) == 1


def test_bad_requests(setup):
    c, kc, _ = setup
    alice = as_user(kc, ALICE)
    assert c.get("/v1/conversations").status_code == 401
    assert c.get("/v1/conversations/not-a-uuid", headers=alice).status_code == 422


def test_without_a_database_history_is_unavailable():
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled())) as c:
        assert (lambda r: (r.status_code, r.json()["code"]))(c.get("/v1/conversations")) == (503, "conversation.unavailable")
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
    cid = uuid.uuid4()
    assert kept(store, cid, ALICE, TURNS)
    assert not kept(store, cid, BOB, TURNS)  # the id is taken
    assert store.get(cid, BOB) is None and store.summaries(BOB) == []
    got = store.get(cid, ALICE)
    assert got.title == "Wat is de koopprijs?" and said(got.turns) == said(TURNS)
    assert [s.id for s in store.summaries(ALICE)] == [str(cid)]
    assert not store.delete(cid, BOB) and store.delete(cid, ALICE)
    assert store.get(cid, ALICE) is None


@needs_db
def test_store_keeps_a_conversation_in_its_case(store):
    """suveryn-tracker#10: listed with its case, not in the personal space, and it doesn't move as it goes on."""
    case, in_case, personal = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert kept(store, in_case, ALICE, TURNS, case_id=case)
    assert kept(store, personal, ALICE, TURNS)
    assert [s.id for s in store.summaries(ALICE)] == [str(personal)]
    assert [(s.id, s.case_id) for s in store.summaries(ALICE, case)] == [(str(in_case), str(case))]
    assert store.get(in_case, ALICE).case_id == str(case) and store.get(personal, ALICE).case_id is None
    store.append(in_case, "user", ALICE, "En de kosten?")  # a question later: it stays where it was
    assert [s.id for s in store.summaries(ALICE, case)] == [str(in_case)]
    assert store.delete_case(case) == 1 and store.summaries(ALICE, case) == []


@needs_db
def test_store_lists_newest_first_and_deletes_all(store):
    first, second = uuid.uuid4(), uuid.uuid4()
    kept(store, first, ALICE, TURNS)
    kept(store, second, ALICE, TURNS)
    store.append(first, "user", ALICE, "En de kosten?")  # changed last
    assert [s.id for s in store.summaries(ALICE)] == [str(first), str(second)]
    kept(store, uuid.uuid4(), BOB, TURNS)
    assert store.delete_all(ALICE) == 2
    assert len(store.summaries(BOB)) == 1


@needs_db
def test_store_age_cap(store):
    old, new = uuid.uuid4(), uuid.uuid4()
    kept(store, old, ALICE, TURNS)
    kept(store, new, ALICE, TURNS)
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
        kept(store, old, ALICE, TURNS)
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
    kept(store, mine_personal, ALICE, TURNS)
    kept(store, mine_in_case, ALICE, TURNS, case_id=case_a)
    kept(store, mine_elsewhere, ALICE, TURNS, case_id=case_b)
    kept(store, others, BOB, TURNS, case_id=case_a)
    store.set_shared(others, BOB, True)
    found = {s.id: s for s in store.summaries_all(ALICE, [case_a])}
    assert set(found) == {str(mine_personal), str(mine_in_case), str(others)}  # not the case she can't read
    assert found[str(others)].owner == BOB and found[str(others)].shared
    assert found[str(mine_personal)].messages == len(TURNS)
    store.set_shared(others, BOB, False)
    assert str(others) not in {s.id for s in store.summaries_all(ALICE, [case_a])}  # no longer shared: Bob's alone


@needs_db
def test_store_keep_period_changed_by_an_administrator(store):
    """The gateway sets ``keep`` from the dashboard's setting; a shorter period deletes at the next listing."""
    old, new = uuid.uuid4(), uuid.uuid4()
    kept(store, old, ALICE, TURNS)
    kept(store, new, ALICE, TURNS)
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
                                                                               "location": "p. 3 · Artikel 2 - Koopprijs"},
                        "context": {"text": "Artikel 2. De koopprijs bedraagt € 345.000. Betaalbaar bij de akte.", "start": 11, "end": 43}},
                       {"text": "Verkoper: Jan Peeters.", "source": {"document_id": OTHER, "page": 1, "location": "p. 1"}}]},
    ]


def test_redact_takes_out_passages_and_names_of_deleted_documents_only():
    turns = cited_turns()
    assert cited_documents(turns) == {DOC, OTHER}
    assert redact(turns, lambda d: d == DOC) is True
    gone, kept = turns[1]["citations"]
    assert gone == {"text": "", "source": {"document_id": DOC, "page": 3, "location": None}, "removed": True}  # its context too
    assert kept["text"] == "Verkoper: Jan Peeters." and "removed" not in kept
    assert turns[0]["attachments"][0]["filename"] == "" and turns[0]["attachments"][0]["removed"] is True
    assert turns[1]["text"] == "€ 345.000 [1], verkoper Peeters [2]"  # the answer stays; the UI offers to delete it
    assert redact(turns, lambda d: d == DOC) is False  # idempotent


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
    assert kept(store, cid, ALICE, cited_turns(), "Prijs")
    assert [s["id"] for s in c.get(f"/v1/documents/{DOC}/conversations", headers=alice).json()] == [cid]
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 204
    saved = c.get(f"/v1/conversations/{cid}", headers=alice).json()["turns"]
    assert "345.000." not in str(saved[1]["citations"]) and "Artikel 2" not in str(saved) and "akte-peeters" not in str(saved)
    assert "Jan Peeters" in str(saved[1]["citations"])  # the other document's passage stays
    assert c.get(f"/v1/documents/{OTHER}/conversations", headers=alice).json()[0]["id"] == cid


def test_deleting_a_document_can_delete_the_conversations_that_used_it(with_docs):
    c, alice, store, _ = with_docs
    cid, other = str(uuid.uuid4()), str(uuid.uuid4())
    kept(store, cid, ALICE, cited_turns(), "Prijs")
    kept(store, other, ALICE, TURNS)  # doesn't use the document
    assert c.delete(f"/v1/documents/{DOC}", params={"conversations": "delete"}, headers=alice).status_code == 204
    assert [s["id"] for s in c.get("/v1/conversations", headers=alice).json()] == [other]
    assert c.delete(f"/v1/documents/{OTHER}", params={"conversations": "everything"}, headers=alice).status_code == 422


def test_a_document_isnt_deleted_while_saved_conversations_cant_be_reached(with_docs):
    """Audit of 21 October 2026, finding 3: before, the document went and its passages stayed in the conversations."""
    from suveryn_api_gateway.routes.common import Database

    c, alice, store, docs = with_docs
    cid = str(uuid.uuid4())
    kept(store, cid, ALICE, cited_turns(), "Price")

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
    kept(store, cid, ALICE, cited_turns(), "Price")
    real = store.remove_document

    def broken(*a, **k):
        raise OSError("connection lost")

    store.remove_document = broken
    assert c.delete(f"/v1/documents/{DOC}", headers=alice).status_code == 202  # deleted; the cleaning is still to do
    assert DOC not in docs.ids and store.cleanups == {(ALICE, uuid.UUID(DOC)): (False, None)}
    store.remove_document = real
    assert store.finish_cleanups() == 1 and store.cleanups == {}  # what the hourly sweep does
    assert store.rows[uuid.UUID(cid)]["turns"][1]["citations"][0]["removed"] is True


@needs_db
def test_store_cleans_or_deletes_conversations_of_a_deleted_document(store):
    used, unused, bobs = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kept(store, used, ALICE, cited_turns(), "Prijs")
    kept(store, unused, ALICE, TURNS)
    kept(store, bobs, BOB, cited_turns(), "Prijs")  # same document id, another owner
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


@needs_db
def test_store_unshares_every_conversation_of_a_case(store):
    """§11: a case made strictly confidential unshares its conversations; their owners keep them."""
    case, other, a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kept(store, a, ALICE, TURNS, case_id=case)
    kept(store, b, BOB, TURNS, case_id=case)
    kept(store, c, ALICE, TURNS, case_id=other)
    for cid, owner in ((a, ALICE), (b, BOB), (c, ALICE)):
        store.set_shared(cid, owner, True)
    assert store.unshare_case(case) == 2 and store.unshare_case(case) == 0
    assert store.get_shared(a) is None and store.get(a, ALICE) is not None
    assert store.get_shared(c) is not None  # another case's stays shared


@needs_db
def test_store_renames_pins_and_moves_a_personal_conversation(store):
    """§3 and §4: the owner's title stays as the conversation goes on; a pin only for a personal conversation; moved
    into a case, it isn't shared and has no pin of its own."""
    case, cid, in_case = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kept(store, cid, ALICE, TURNS)
    kept(store, in_case, ALICE, TURNS, case_id=case)
    assert store.rename(cid, BOB, "Bob's") is None
    assert store.rename(cid, ALICE, "Sale, the price").title == "Sale, the price"
    store.append(cid, "user", ALICE, "En de kosten?")
    assert store.get(cid, ALICE).title == "Sale, the price"
    assert store.set_pinned(cid, BOB, True) is None and store.set_pinned(in_case, ALICE, True) is None
    assert store.set_pinned(cid, ALICE, True).pinned and store.summaries(ALICE)[0].pinned
    assert store.get(cid, ALICE).pinned
    assert store.move(cid, BOB, case) is None and store.move(in_case, ALICE, uuid.uuid4()) is None
    moved = store.move(cid, ALICE, case)
    assert moved.case_id == str(case) and not moved.pinned and not moved.shared
    assert store.summaries(ALICE) == [] and {s.id for s in store.summaries(ALICE, case)} == {str(cid), str(in_case)}
    assert said(store.get(cid, ALICE).turns) == [*said(TURNS), ("user", "En de kosten?")]  # its turns came along


@needs_db
def test_store_shares_a_conversation_with_its_case_and_cleans_every_members(store):
    """Stage 4 of docs/design/cases.md: shared conversations, and a case's document taken out of
    everyone's conversations when it is deleted."""
    case, alices, bobs, personal = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kept(store, alices, ALICE, TURNS, case_id=case)
    kept(store, bobs, BOB, TURNS, case_id=case)
    kept(store, personal, ALICE, TURNS)
    assert [s.id for s in store.summaries(BOB, case)] == [str(bobs)]  # alice's is private
    assert store.get_shared(alices) is None
    assert store.set_shared(alices, BOB, True) is None       # not his
    assert store.set_shared(personal, ALICE, True) is None   # not in a case
    shared = store.set_shared(alices, ALICE, True)
    assert shared.shared and shared.owner == ALICE
    assert sorted((s.id, s.owner, s.shared) for s in store.summaries(BOB, case)) == sorted(
        [(str(bobs), BOB, False), (str(alices), ALICE, True)])
    assert said(store.get_shared(alices).turns) == said(TURNS) and store.get(alices, BOB) is None  # readable, not his
    assert store.summaries(ALICE) == [store.summaries(ALICE)[0]] and store.summaries(ALICE)[0].id == str(personal)
    assert store.set_shared(alices, ALICE, False).shared is False and store.get_shared(alices) is None
    # the case's document is cited in bob's conversation too: everyone's are cleaned
    doc = "11111111-1111-1111-1111-111111111111"
    turns = [{"role": "user", "text": "?"}, {"role": "assistant", "text": "x [1]",
             "citations": [{"n": 1, "text": "secret", "source": {"document_id": doc, "page": 1}}]}]
    bobs, alices = uuid.uuid4(), uuid.uuid4()  # a question each that cites it
    kept(store, bobs, BOB, turns, "b", case_id=case)
    kept(store, alices, ALICE, turns, "a", case_id=case)
    assert sorted(s.owner for s in store.using_document(ALICE, uuid.UUID(doc), case)) == [ALICE, BOB]
    assert [s.owner for s in store.using_document(ALICE, uuid.UUID(doc))] == [ALICE]  # personal: own only
    assert store.remove_document(ALICE, uuid.UUID(doc), case_id=case) == 2
    assert store.get(bobs, BOB).turns[1]["citations"][0]["text"] == ""
    assert store.remove_document(ALICE, uuid.UUID(doc), delete_conversations=True, case_id=case) == 2  # both, whoever's
    assert store.delete_case(case) == 2  # the first two, which didn't cite it


@needs_db
def test_store_finishes_a_cleaning_a_deletion_left_unfinished(store):
    """Audit of 21 October 2026, finding 3: the cleaning is noted before the document goes, and done after."""
    cid, did = uuid.uuid4(), uuid.UUID(DOC)
    kept(store, cid, ALICE, cited_turns(), "Price")
    store._execute("DELETE FROM conversation_cleanups WHERE owner IN (%s, %s)", (ALICE, BOB))
    store.note_cleanup(ALICE, did, False, None)
    store.note_cleanup(ALICE, did, True, None)  # asked again, to delete the conversations: the stronger wins
    assert store._execute("SELECT delete_conversations FROM conversation_cleanups WHERE owner = %s", (ALICE,)).fetchall() == [(True,)]
    store._execute("UPDATE conversation_cleanups SET delete_conversations = false WHERE owner = %s", (ALICE,))
    assert store.finish_cleanups() >= 1
    assert store.get(cid, ALICE).turns[1]["citations"][0]["removed"] is True
    assert store._execute("SELECT count(*) FROM conversation_cleanups WHERE owner = %s", (ALICE,)).fetchone()[0] == 0


@needs_db
def test_the_turn_count_and_cited_documents_are_kept_as_turns_are_added_and_found_without_the_turns(store):
    """Lists and "which conversations cite this document" no longer open the turns (database review of
    510c87b): the count and the documents are kept beside them as every turn is added."""
    cid = uuid.uuid4()
    assert kept(store, cid, ALICE, cited_turns(), "Koopprijs")
    messages, documents = store._execute("SELECT messages, documents FROM conversations WHERE id = %s", (cid,)).fetchone()
    assert messages == 2 and documents == sorted([DOC, OTHER])
    assert store.summaries(ALICE)[0].messages == 2
    assert [s.id for s in store.using_document(ALICE, uuid.UUID(DOC))] == [str(cid)]
    assert store.using_document(BOB, uuid.UUID(DOC)) == []  # someone else's conversation isn't searched


@needs_db
def test_store_deletes_an_accounts_own_conversations_and_keeps_those_shared_with_a_case(store):
    """Administration › Users, deleting an account (decision, 29 October)."""
    case = uuid.uuid4()
    personal, unshared, shared = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kept(store, personal, ALICE, TURNS)
    kept(store, unshared, ALICE, TURNS, case_id=case)
    kept(store, shared, ALICE, TURNS, case_id=case)
    store.set_shared(shared, ALICE, True)
    kept(store, uuid.uuid4(), BOB, TURNS)
    assert (store.personal(ALICE), store.shared_count(ALICE)) == (2, 1)
    assert store.delete_personal(ALICE) == 2
    assert store.get_shared(shared) is not None and store.get(personal, ALICE) is None and len(store.summaries(BOB)) == 1


# ------------------------------------------------------------------ turns, one row each (``TurnStore``)

@needs_db
def test_turns_are_appended_in_order_and_two_writers_never_collide():
    """The ``turns`` table (docs/design/playbooks.md, "The thread"): rows, not a blob. Two sessions
    appending at the same moment get consecutive numbers (the conversation's row is locked while the
    next is taken); nothing is overwritten. A turn always belongs to a conversation, and goes with it."""
    import threading

    from suveryn_api_gateway.conversations import TurnStore

    store, conv, rid = TurnStore(URL), uuid.uuid4(), uuid.uuid4()
    store.create_for_run(conv, rid, ALICE, "Akte-intake", uuid.uuid4())
    try:
        first = store.append(conv, "playbook", "playbook/x/y", "Upload the agreement.", "agreement")
        assert (first.seq, first.role, first.step_id, first.by) == (1, "playbook", "agreement", "playbook/x/y")
        writers = [TurnStore(URL) for _ in range(4)]
        go = threading.Barrier(4)

        def write(s, i):
            go.wait()
            s.append(conv, "user", f"user-{i}", f"answer {i}", "agreement", {"n": i})

        threads = [threading.Thread(target=write, args=(s, i)) for i, s in enumerate(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        turns = store.turns_of(conv)
        assert [t.seq for t in turns] == [1, 2, 3, 4, 5] and {t.by for t in turns[1:]} == {f"user-{i}" for i in range(4)}
        assert store.turns_of(conv, limit=2)[-1].seq == 2 and store.turns_of(uuid.uuid4()) == []
        assert store._execute("SELECT messages FROM conversations WHERE id = %s", (conv,)).fetchone()[0] == 5
        with pytest.raises(LookupError):
            store.append(uuid.uuid4(), "user", "x", "y")
        with pytest.raises(Exception):  # a turn always belongs to a conversation
            store._execute("INSERT INTO turns (seq, role, \"by\", text) VALUES (1, 'user', 'x', 'y')")
        store._execute("DELETE FROM conversations WHERE id = %s", (conv,))
        assert store.turns_of(conv) == []
        for s in writers:
            s.close()
    finally:
        store._execute("DELETE FROM conversations WHERE id = %s", (conv,))
        store.close()


@needs_db
def test_a_playbook_runs_conversation_goes_with_its_case(store):
    """A run's conversation is listed and read like a shared one, but the server writes it: it isn't saved
    over, deleted, unshared or purged on its own, and "Delete history" leaves it."""
    conv, rid, case = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.create_for_run(conv, rid, ALICE, "Akte-intake", case)
    try:
        store.append(conv, "playbook", "playbook/notarial-be/deed-intake", "Laad de compromis op.", "agreement")
        listed = store.summaries(BOB, case)
        assert [(s.id, s.run_id, s.shared, s.title, s.messages) for s in listed] == [(str(conv), str(rid), True, "Akte-intake", 1)]
        assert store.get_shared(conv).turns[0]["step_id"] == "agreement"
        assert not kept(store, conv, ALICE, TURNS)
        assert not store.delete(conv, ALICE) and store.set_shared(conv, ALICE, False) is None
        assert store.unshare_case(case) == 0 and store.delete_all(ALICE) == 0
        store._execute("UPDATE conversations SET updated_at = now() - interval '400 days' WHERE id = %s", (conv,))
        store.keep = "6m"
        assert store.purge() == 0 and store.get(conv, ALICE) is not None
    finally:
        store.keep = "manual"
        store._execute("DELETE FROM conversations WHERE id = %s", (conv,))


def test_a_deletion_flushes_the_journal_shortly_once(setup, monkeypatch):
    """VM regression 03c8f74, finding 3: after a deletion the WAL holding the text is let go (suveryn_rag.journal);
    deletions close together share one flush."""
    import time

    from suveryn_api_gateway.routes import common

    c, kc, _ = setup
    flushed: list[str] = []
    monkeypatch.setattr(common, "flush_journal", flushed.append)
    journal = c.app.state.journal
    journal.database_url, journal.delay = "postgresql://appliance/suveryn", 0.05
    alice = as_user(kc, ALICE)
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for cid in ids:
        assert kept(c.app.state.history.get(), cid, ALICE, TURNS)
    for cid in ids:
        assert c.delete(f"/v1/conversations/{cid}", headers=alice).status_code == 204
    for _ in range(40):
        if journal.flushes:
            break
        time.sleep(0.05)
    assert flushed == ["postgresql://appliance/suveryn"]  # once, for the three
    assert c.delete("/v1/conversations", headers=alice).status_code == 200
    for _ in range(40):
        if journal.flushes == 2:
            break
        time.sleep(0.05)
    assert len(flushed) == 2


def test_without_a_database_nothing_is_flushed():
    from suveryn_api_gateway.routes.common import JournalFlush

    j = JournalFlush(database_url="")
    j.soon()  # no running loop needed: it returns at once
    assert j._task is None


def test_deletions_during_the_wait_share_one_flush(monkeypatch, caplog):
    """VM regression 9c97d76, finding 4: five deletions in 2.6 s flushed twice: the flag was cleared before the wait,
    so a deletion during it asked for a second flush. And each flush is now a line in the journal."""
    import asyncio

    from suveryn_api_gateway.routes import common

    flushed: list[str] = []
    monkeypatch.setattr(common, "flush_journal", lambda url: flushed.append(url) or True)

    async def five_deletions():
        j = common.JournalFlush(database_url="postgresql://appliance/suveryn", delay=0.2)
        for _ in range(5):
            j.soon()
            await asyncio.sleep(0.03)  # all within the wait
        await j._task
        return j

    with caplog.at_level("INFO", logger="suveryn.gateway"):
        j = asyncio.run(five_deletions())
    assert flushed == ["postgresql://appliance/suveryn"] and j.flushes == 1
    assert sum("journal flushed after a deletion" in r.getMessage() for r in caplog.records) == 1


DELETED, STAYS = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
# The turns the server writes, in a run's thread and a conversation (fictional): a question with the documents it was
# given (a playbook's attachments, by id and name), and an answer with its passages, one with the text around it.
WRITTEN = [
    {"role": "user", "text": "Lees het compromis.", "attachments": [{"documentId": DELETED, "filename": "Compromis_Peeters.pdf"},
                                                                    {"documentId": STAYS, "filename": "Bodemattest.pdf"}]},
    {"role": "assistant", "text": "De koopprijs is € 345.000 [1]; het bodemattest is blanco [2].", "kind": "answer", "parent": 1,
     "outcome": "done", "citations": [
         {"text": "De koopprijs bedraagt € 345.000.", "source": {"document_id": DELETED, "page": 3, "location": "p. 3 · Artikel 2 - Prijs"},
          "context": {"text": "Artikel 2. De koopprijs bedraagt € 345.000. Te betalen bij de akte.", "start": 11, "end": 44}},
         {"text": "Het bodemattest is blanco.", "source": {"document_id": STAYS, "page": 1, "location": "p. 1"}}]},
]


def test_a_deleted_documents_passages_and_name_are_taken_out_of_what_the_server_wrote():
    """Deleting a document takes its passages, the text around them, its headings and its file name out of every turn
    the server wrote (``redact``) and out of an answer saved to the case (the rag's ``without``); the answer's words,
    the page and the other documents stay. Since suveryn-tracker#251 this is the only clean-up: the screens read the
    conversation again."""
    import copy
    import json

    from suveryn_api_gateway.conversations import SavedAnswer, redact
    from suveryn_rag.store import without

    turns = copy.deepcopy(WRITTEN)
    assert redact(turns, lambda d: d == DELETED) is True
    saved = SavedAnswer(question="Wat is de koopprijs?", answer=WRITTEN[1]["text"], answered_on=datetime.now(UTC), model=None,
                        citations=copy.deepcopy(WRITTEN[1]["citations"]), calculations=[], unverified_figures=[], citation_issues=[],
                        support_spans=[], instruction_like_sources=[], filenames={DELETED: "Compromis_Peeters.pdf", STAYS: "Bodemattest.pdf"},
                        turn_id="c/2", case_ref=None)
    answer = without(saved.model_dump(mode="json"), DELETED)
    for cleaned in (json.dumps(turns, ensure_ascii=False), json.dumps(answer, ensure_ascii=False)):
        assert not [g for g in ("Compromis_Peeters", "345.000.", "Te betalen bij de akte", "Artikel 2 - Prijs") if g in cleaned], cleaned
    everything = json.dumps([turns, answer], ensure_ascii=False)
    assert all(s in everything for s in ("De koopprijs is € 345.000 [1]", "Bodemattest.pdf", "Het bodemattest is blanco.", '"page": 3'))
    assert turns[0]["attachments"][0] == {"documentId": DELETED, "filename": "", "removed": True}
    assert redact(turns, lambda d: d == DELETED) is False  # once is enough
