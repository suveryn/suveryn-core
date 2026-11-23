"""suveryn-tracker#251: the server stores each turn of a conversation as it answers.

A question goes to ``POST /v1/conversations/{id}/questions``: the server stores it, builds what the model reads of the
conversation from the turns it stored, and stores the answer as it was written, however it ends. The route's tests
run against a real PostgreSQL and are skipped unless SUVERYN_TEST_DATABASE_URL is set; the parts that need none
(what the model reads, what an answer's row keeps) are tested without it.
"""

import json
import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.conversations import ConversationIn, ConversationSettings, ConversationStore, Turn, answered_turn, history_pairs
from suveryn_api_gateway.routes import conversations as routes
from suveryn_harness import ChatResponse, Citation, LlamaServerClient, LLMSettings, SourceRef, conversation_history
from suveryn_harness.history import HISTORY_CHARS, MAX_HISTORY
from suveryn_harness.schemas import MAX_TOTAL_CHARS
from test_auth import SETTINGS, FakeKeycloak
from test_documents import llm_transport

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")
ALICE, BOB = "user-q-a", "user-q-b"
DOC, OTHER = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


# What the model reads of a conversation: no database needed.

def test_only_questions_with_a_completed_answer_go_to_the_model_in_turn():
    history = conversation_history([("Wat is de koopprijs?", "€ 345.000 [1]"), ("En de datum?", None), ("Wie koopt?", "Jan [2]")])
    assert [(m.role, m.content) for m in history] == [("user", "Wat is de koopprijs?"), ("assistant", "€ 345.000 [1]"),
                                                      ("user", "Wie koopt?"), ("assistant", "Jan [2]")]


def test_the_oldest_pairs_go_first_and_the_new_question_has_room():
    many = [(f"q{i}", f"a{i}") for i in range(30)]
    assert len(conversation_history(many)) == MAX_HISTORY and conversation_history(many)[0].content == "q10"
    long = [("q" * 1000, "a" * 20_000)] * 4  # 84,000 characters: more than the history may take
    assert sum(len(m.content) for m in conversation_history(long)) <= HISTORY_CHARS
    question = "x" * 100_000  # the longest question: what is left of the request's total, 50,000
    pairs = [("q", "a" * 29_999)] * 3  # 30,000 a pair: two fit the history's own 60,000, one fits beside the question
    assert len(conversation_history(pairs)) == 4
    kept = conversation_history(pairs, question)
    assert len(kept) == 2 and sum(len(m.content) for m in kept) + len(question) <= MAX_TOTAL_CHARS


def turn(seq, role, text, **meta):
    return Turn(seq=seq, role=role, by="x", at="2026-11-23T10:00:00Z", text=text, meta=meta)


def test_the_pairs_are_read_from_the_servers_turns_and_from_turns_the_chat_ui_saved():
    turns = [turn(1, "user", "q1"), turn(2, "assistant", "a1", kind="answer", outcome="done"),
             turn(3, "user", "q2"), turn(4, "assistant", "", kind="answer", outcome="failed"),
             turn(5, "user", "q3"), turn(6, "assistant", "a3", status="done"),  # saved by the chat UI before #251
             turn(7, "user", "q4"), turn(8, "assistant", "a4 so far", kind="answer", outcome="stopped"),
             turn(9, "user", "q5")]
    assert history_pairs(turns) == [("q1", "a1"), ("q2", None), ("q3", "a3"), ("q4", None), ("q5", None)]


# What an answer's row keeps.

def cited(doc: str, n: int = 1) -> Citation:
    return Citation(text=f"Passage {n}", source=SourceRef(document_id=doc, page=1))


def test_an_answer_written_out_keeps_its_checks_and_not_the_file_name_it_was_narrowed_to():
    done = ChatResponse(id="x", model="m.gguf", answer="€ 345.000 [1]", citations=[cited(DOC)], narrowed_to="Compromis_Peeters.pdf")
    text, meta = answered_turn("", "", [], done, None)
    assert text == "€ 345.000 [1]" and meta["kind"] == "answer" and meta["outcome"] == "done"
    assert meta["narrowed_to"] == DOC and "Compromis_Peeters.pdf" not in json.dumps(meta)
    assert "usage" not in meta and "id" not in meta and meta["citations"][0]["source"]["document_id"] == DOC
    two = done.model_copy(update={"citations": [cited(DOC), cited(OTHER, 2)]})
    assert answered_turn("", "", [], two, None)[1]["narrowed_to"] is None  # can't tell which: no name either


def test_what_an_answer_keeps_is_everything_the_answer_says_beside_its_words():
    """``AnsweredTurn`` holds an answer written out as ``ChatResponse`` gives it: a member added to the one and not the
    other would be lost when it is stored."""
    from suveryn_api_gateway.conversations import AnsweredTurn

    kept = set(ChatResponse.model_fields) - {"id", "answer", "usage"}
    assert set(AnsweredTurn.model_fields) == kept | {"kind", "outcome", "failure"}


def test_a_failed_answer_keeps_no_words_and_a_stopped_one_keeps_what_was_written():
    failure = {"kind": "unavailable", "code": "model.unavailable", "params": {}}
    text, meta = answered_turn("Half an ans", "", [cited(DOC)], None, failure)
    assert (text, meta["outcome"], meta["failure"], meta["citations"]) == ("", "failed", failure, [])
    text, meta = answered_turn("Half an ans", "thought", [cited(DOC)], None, None)
    assert text == "Half an ans" and meta["outcome"] == "stopped" and meta["reasoning"] == "thought"
    assert meta["citations"][0]["source"]["document_id"] == DOC


# The route, against a real PostgreSQL.

@pytest.fixture
def store():
    s = ConversationStore(ConversationSettings(database_url=URL))
    s._execute("DELETE FROM conversations WHERE owner IN (%s, %s)", (ALICE, BOB))
    yield s
    s._execute("DELETE FROM conversations WHERE owner IN (%s, %s)", (ALICE, BOB))
    s.close()


def app(store, transport, **more):
    kc = FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=transport)
    return TestClient(create_app(llm, load_documents=False, auth=auth, conversations=store, **more)), kc


def as_user(kc, sub):
    return {"Authorization": f"Bearer {kc.tokens(over={'sub': sub})['access_token']}"}


def events(stream) -> list[tuple[str, dict]]:
    out, name = [], None
    for line in stream.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            out.append((name, json.loads(line[6:])))
    return out


def stored(store, cid) -> list[tuple[str, str, dict]]:
    return [(t.role, t.text, t.meta) for t in store.turns_of(uuid.UUID(cid))]


@needs_db
def test_a_question_and_its_answer_are_stored_by_the_server_and_read_back_to_the_model(store):
    captured: list[dict] = []
    c, kc = app(store, llm_transport(captured, text="€ 345.000"))
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())
    with c:
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is  de\nkoopprijs?"}, headers=alice) as r:
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            assert [name for name, _ in events(r)][-1] == "done"
        got = c.get(f"/v1/conversations/{cid}", headers=alice).json()
        assert got["title"] == "Wat is de koopprijs?" and got["messages"] == 2 and got["case_id"] is None
        (q_role, q_text, q_meta), (a_role, a_text, a_meta) = stored(store, cid)
        assert (q_role, q_text, q_meta["kind"], q_meta["document_ids"]) == ("user", "Wat is  de\nkoopprijs?", "question", [])
        assert (a_role, a_text, a_meta["kind"], a_meta["outcome"]) == ("assistant", "€ 345.000", "answer", "done")
        # The next question: what the model reads before it is what the server stored, not what the browser says.
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "En de datum?"}, headers=alice) as r:
            events(r)
        sent = [m for m in captured[-1]["messages"] if m["role"] != "system"]
        assert [m["role"] for m in sent] == ["user", "assistant", "user"]
        assert sent[1]["content"] == "€ 345.000" and sent[2]["content"].endswith("En de datum?")
        assert len(stored(store, cid)) == 4


@needs_db
def test_someone_elses_conversation_or_a_runs_is_not_asked_in(store):
    c, kc = app(store, llm_transport([]))
    cid = uuid.uuid4()
    store.save(cid, ALICE, ConversationIn(title="Prijs", turns=[{"role": "user", "text": "Wat is de koopprijs?"}]))
    run = uuid.uuid4()
    store.create_for_run(run, uuid.uuid4(), ALICE, "Akte", uuid.uuid4())
    with c:
        assert c.post(f"/v1/conversations/{cid}/questions", json={"text": "?"}, headers=as_user(kc, BOB)).status_code == 404
        assert c.post(f"/v1/conversations/{run}/questions", json={"text": "?"}, headers=as_user(kc, ALICE)).status_code == 404
        assert c.post("/v1/conversations/not-an-id/questions", json={"text": "?"}, headers=as_user(kc, ALICE)).status_code == 422
    assert len(store.turns_of(cid)) == 1


@needs_db
def test_a_conversation_past_the_keep_period_is_not_asked_in(store):
    """Gone from every list once the office's keep period has passed, and deleted by the next sweep: not continued in
    the meantime either (the route answers 404 for what ``place`` says can't be asked in)."""
    old = uuid.uuid4()
    store.save(old, ALICE, ConversationIn(title="Oud", turns=[{"role": "user", "text": "?"}]))
    store._execute("UPDATE conversations SET updated_at = now() - interval '400 days' WHERE id = %s", (old,))
    assert store.place(old) == (ALICE, None, False)  # kept until deleted by hand: still asked in
    store.keep = "1y"
    assert store.place(old) == (ALICE, None, True)


@needs_db
def test_a_conversation_the_chat_ui_saved_goes_on_on_the_server(store):
    """A conversation saved the old way (the chat UI's whole list): its completed answers are read to the model."""
    captured: list[dict] = []
    c, kc = app(store, llm_transport(captured))
    cid = uuid.uuid4()
    store.save(cid, ALICE, ConversationIn(title="Prijs", turns=[
        {"role": "user", "text": "Wat is de koopprijs?", "attachments": []},
        {"role": "assistant", "text": "€ 345.000", "status": "done", "citations": []}]))
    with c, c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "En de datum?"}, headers=as_user(kc, ALICE)) as r:
        events(r)
    assert [m["content"] for m in captured[-1]["messages"] if m["role"] == "assistant"] == ["€ 345.000"]
    assert len(store.turns_of(cid)) == 4


@needs_db
def test_asking_again_replaces_the_last_answer_and_needs_one(store):
    c, kc = app(store, llm_transport([], text="Tweede antwoord"))
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())
    with c:
        assert c.post(f"/v1/conversations/{cid}/questions", json={"text": "?", "again": True}, headers=alice).status_code == 409
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?"}, headers=alice) as r:
            events(r)
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?", "again": True}, headers=alice) as r:
            events(r)
        assert [(role, text) for role, text, _ in stored(store, cid)] == [("user", "Wat is de koopprijs?"), ("assistant", "Tweede antwoord")]
        assert c.get(f"/v1/conversations/{cid}", headers=alice).json()["messages"] == 2


@needs_db
def test_a_second_question_waits_for_the_answer_being_written(store):
    c, kc = app(store, llm_transport([]))
    cid = uuid.uuid4()
    routes.ANSWERING.add(cid)
    try:
        with c:
            r = c.post(f"/v1/conversations/{cid}/questions", json={"text": "?"}, headers=as_user(kc, ALICE))
        assert r.status_code == 409 and r.json()["code"] == "request.conflict"
    finally:
        routes.ANSWERING.discard(cid)
    assert store.place(cid) is None  # nothing started


@needs_db
def test_a_failed_answer_is_stored_as_failed_without_its_words(store):
    def down(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "m.gguf"}]})
        return httpx.Response(500, text="the model server's own words")
    c, kc = app(store, httpx.MockTransport(down))
    cid = str(uuid.uuid4())
    with c, c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?"}, headers=as_user(kc, ALICE)) as r:
        assert [name for name, _ in events(r)][-1] == "error"
    (_, _, _), (role, text, meta) = stored(store, cid)
    assert (role, text, meta["outcome"], meta["failure"]["code"]) == ("assistant", "", "failed", "model.unavailable")
    assert uuid.UUID(cid) not in routes.ANSWERING


@needs_db
def test_an_answer_stopped_by_closing_the_connection_keeps_what_was_written(store):
    """The person pressed *Stop* (or the tab closed): the connection closes, the model stops, and the words so far are
    stored as a stopped answer, so a reopened conversation shows them as the person saw them. (Starlette's test
    client never closes a connection early, so the request is made by hand, as test_api.py's stop does.)"""
    import anyio
    from test_api import endless_backend

    state: dict = {}
    application = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=endless_backend(state, 2)),
                             load_documents=False, auth=Authenticator.disabled(), conversations=store)
    cid = str(uuid.uuid4())
    path = f"/v1/conversations/{cid}/questions"

    async def ask() -> list[str]:
        gone, seen, sent = anyio.Event(), [], False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps({"text": "Wat is de koopprijs?"}).encode(), "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                seen.extend(line[7:] for line in message["body"].decode().split("\n") if line.startswith("event: "))
                if seen.count("delta") >= 2:
                    gone.set()  # the person pressed Stop

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
                 "root_path": "", "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
                 "client": ("127.0.0.1", 1), "server": ("test", 80)}
        with anyio.fail_after(10):
            await application(scope, receive, send)
        return seen

    try:
        with TestClient(application) as c:
            seen = c.portal.call(ask)
        assert "done" not in seen and state.get("closed")
        (_, _, _), (role, text, meta) = stored(store, cid)
        assert role == "assistant" and meta["outcome"] == "stopped" and text and uuid.UUID(cid) not in routes.ANSWERING
    finally:
        store.delete(uuid.UUID(cid), store.place(uuid.UUID(cid))[0] if store.place(uuid.UUID(cid)) else "")


@needs_db
def test_two_regenerates_at_once_take_out_one_answer_only(store):
    """Review of #251, finding 1: a double click on *Regenerate* sent two requests; both passed the check before
    either was noted, and each took out "the last" question, an earlier one too."""
    import anyio

    application = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text="A")),
                             load_documents=False, auth=Authenticator.disabled(), conversations=store)
    cid = str(uuid.uuid4())

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(application), base_url="http://test") as c:
            for q in ("q1", "q2"):
                assert (await c.post(f"/v1/conversations/{cid}/questions", json={"text": q})).status_code == 200
            statuses: list[int] = []

            async def again():
                statuses.append((await c.post(f"/v1/conversations/{cid}/questions", json={"text": "q2", "again": True})).status_code)
            async with anyio.create_task_group() as g:
                g.start_soon(again)
                g.start_soon(again)
            return sorted(statuses)

    try:
        with TestClient(application) as c:
            assert c.portal.call(go) == [200, 409]
        assert [(role, text) for role, text, _ in stored(store, cid)] == [("user", "q1"), ("assistant", "A"), ("user", "q2"), ("assistant", "A")]
    finally:
        store._execute("DELETE FROM conversations WHERE id = %s", (uuid.UUID(cid),))


@needs_db
def test_regenerate_asks_the_last_question_again_and_nothing_else(store):
    c, kc = app(store, llm_transport([]))
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())
    with c:
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?"}, headers=alice) as r:
            events(r)
        r = c.post(f"/v1/conversations/{cid}/questions", json={"text": "Iets anders", "again": True}, headers=alice)
        assert r.status_code == 409 and r.json()["code"] == "request.conflict"
    assert [text for _, text, _ in stored(store, cid)][0] == "Wat is de koopprijs?" and len(stored(store, cid)) == 2


@needs_db
def test_a_document_deleted_while_the_answer_is_written_leaves_no_passage_in_it(store):
    """Review of #251, finding 2: the answer is stored when it ends; a document deleted meanwhile had already been
    cleaned out of the conversation, before its passages were in it."""
    from test_documents import DOC as DEED, FakeDocuments

    docs = FakeDocuments(owner=ALICE)
    found = docs.retrieve

    def read_then_deleted(*args, **kwargs):
        passages = found(*args, **kwargs)
        del docs.docs[DEED]  # deleted by a colleague while the model writes
        return passages
    docs.retrieve = read_then_deleted
    kc = FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    cid = str(uuid.uuid4())
    with TestClient(create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=store)) as c, c.stream(
            "POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?", "document_ids": [DEED]},
            headers=as_user(kc, ALICE)) as r:
        assert [name for name, _ in events(r)][-1] == "done"
    (_, _, _), (_, _, meta) = stored(store, cid)
    assert meta["outcome"] == "done" and "412.500" not in json.dumps(meta["citations"]) and meta["citations"][0]["removed"] is True


@needs_db
def test_a_question_shows_only_documents_the_caller_may_see(store):
    from test_documents import DOC as DEED, FakeDocuments

    kc = FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    cid = str(uuid.uuid4())
    with TestClient(create_app(llm, documents=FakeDocuments(owner=ALICE), load_documents=False, auth=auth, conversations=store)) as c:
        bob = as_user(kc, BOB)
        r = c.post(f"/v1/conversations/{cid}/questions", json={"text": "?", "about": [DEED]}, headers=bob)  # Alice's
        assert r.status_code == 404 and r.json()["code"] == "answer.document_not_found"
        assert c.post(f"/v1/conversations/{cid}/questions", json={"text": "?", "attached": ["x" * 10_000]}, headers=bob).status_code == 422
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "?", "attached": [DEED]}, headers=as_user(kc, ALICE)) as r:
            assert r.status_code == 200
            events(r)
    assert store.place(uuid.UUID(cid))[0] == ALICE and stored(store, cid)[0][2]["attached"] == [DEED]
