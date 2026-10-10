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
)
from suveryn_engine import LlamaServerClient, LLMSettings
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

    def summaries(self, owner):
        rows = sorted((r for r in self.rows.values() if r["owner"] == owner), key=lambda r: r["updated_at"], reverse=True)
        return [ConversationSummary(**{k: r[k] for k in ("id", "title", "created_at", "updated_at")}) for r in rows]

    def get(self, cid, owner):
        r = self.rows.get(cid)
        return Conversation(**{k: v for k, v in r.items() if k != "owner"}) if r and r["owner"] == owner else None

    def save(self, cid, owner, body: ConversationIn):
        old = self.rows.get(cid)
        if old and old["owner"] != owner:
            return False
        now = datetime.now(UTC)
        self.rows[cid] = {"id": str(cid), "owner": owner, "title": body.title, "turns": [t.model_dump() for t in body.turns],
                          "created_at": old["created_at"] if old else now, "updated_at": now}
        return True

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


def test_age_cap_must_be_whole_days(monkeypatch):
    monkeypatch.setenv("SUVERYN_CONVERSATION_MAX_AGE_DAYS", "30")
    assert ConversationSettings.from_env().max_age_days == 30
    monkeypatch.setenv("SUVERYN_CONVERSATION_MAX_AGE_DAYS", "")
    assert ConversationSettings.from_env().max_age_days is None
    for bad in ("0", "-1", "2.5", "a month"):
        monkeypatch.setenv("SUVERYN_CONVERSATION_MAX_AGE_DAYS", bad)
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
    store._execute("UPDATE conversations SET updated_at = now() - interval '31 days' WHERE id = %s", (old,))
    capped = ConversationStore(ConversationSettings(database_url=URL, max_age_days=30))  # purges on start
    try:
        assert [s.id for s in capped.summaries(ALICE)] == [str(new)]
        assert store.get(old, ALICE) is None  # deleted, not only hidden
    finally:
        capped.close()
