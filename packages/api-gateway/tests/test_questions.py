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
from suveryn_api_gateway.conversations import (
    ConversationIn,
    ConversationSettings,
    ConversationStore,
    Turn,
    answered_turn,
    history_pairs,
    path_to,
)
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


def test_the_model_reads_the_branch_of_the_tree_on_the_way_to_the_question():
    """A conversation is a tree (suveryn-tracker#251, as in Claude and ChatGPT): each turn names
    the one it follows. Two answers to q1; q2 followed the first, q3 the second; then a turn the chat UI saved."""
    turns = [turn(1, "user", "q1", parent=None), turn(2, "assistant", "a1", parent=1, outcome="done"),
             turn(3, "assistant", "a1b", parent=1, outcome="done"),
             turn(4, "user", "q2", parent=2), turn(5, "assistant", "a2", parent=4, outcome="done"),
             turn(6, "user", "q3", parent=3), turn(7, "assistant", "", parent=6, outcome="failed"),
             turn(8, "user", "q4 saved by the chat UI"), turn(9, "assistant", "a4", status="done")]  # no parent: the turn before
    assert [t.seq for t in path_to(turns, 5)] == [1, 2, 4, 5]
    assert history_pairs(path_to(turns, 5)) == [("q1", "a1"), ("q2", "a2")]
    assert history_pairs(path_to(turns, 7)) == [("q1", "a1b"), ("q3", None)]
    assert [t.seq for t in path_to(turns, 9)] == [1, 3, 6, 7, 8, 9]
    assert path_to(turns, None) == [] and path_to(turns, 99) == []
    looped = [turn(1, "user", "q", parent=2), turn(2, "assistant", "a", parent=1, outcome="done")]
    assert len(path_to(looped, 2)) <= 3  # a loop in what was stored ends


def test_the_pairs_are_read_from_the_servers_turns_and_from_turns_the_chat_ui_saved():
    turns = [turn(1, "user", "q1"), turn(2, "assistant", "a1", kind="answer", outcome="done"),
             turn(3, "user", "q2"), turn(4, "assistant", "", kind="answer", outcome="failed"),
             turn(5, "user", "q3"), turn(6, "assistant", "a3", status="done"),  # saved by the chat UI before #251
             turn(7, "user", "q4"), turn(8, "assistant", "a4 so far", kind="answer", outcome="stopped"),
             turn(9, "user", "q5")]
    assert history_pairs(turns) == [("q1", "a1"), ("q2", None), ("q3", "a3"), ("q4", None), ("q5", None)]
    assert history_pairs(path_to(turns, 9)) == history_pairs(turns)  # without parents: each follows the one before


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
    assert set(AnsweredTurn.model_fields) == kept | {"kind", "parent", "outcome", "failure"}


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
        answer = store.turns_of(uuid.UUID(cid))[1].seq
        r = c.post(f"/v1/conversations/{cid}/questions", json={"text": "En de datum?"}, headers=alice)
        assert r.status_code == 409 and r.json()["code"] == "request.conflict"  # which answer it follows: said
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "En de datum?", "after": answer}, headers=alice) as r:
            events(r)
        assert captured[-1]["max_tokens"] == 3000  # as long an answer as the chat UI asked for (routes/conversations.py)
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
    with c, c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "En de datum?", "after": 2}, headers=as_user(kc, ALICE)) as r:
        events(r)
    assert [m["content"] for m in captured[-1]["messages"] if m["role"] == "assistant"] == ["€ 345.000"]
    assert len(store.turns_of(cid)) == 4


def numbered(captured: list[dict]) -> httpx.MockTransport:
    """A model that answers "Antwoord 1", "Antwoord 2"… in turn, keeping what each request sent."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "m.gguf"}]})
        if request.url.path != "/v1/chat/completions":
            return httpx.Response(404)
        captured.append(json.loads(request.content))
        text = f"Antwoord {len(captured)}"
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
                                                                {"choices": [{"delta": {}, "finish_reason": "stop"}]}])
        return httpx.Response(200, text=sse + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


@needs_db
def test_regenerate_keeps_the_earlier_answers_and_a_question_goes_on_from_the_one_chosen(store):
    """A conversation is a tree, as in Claude and ChatGPT (suveryn-tracker#251): *Regenerate*
    gives a question another answer, the earlier ones stay, and a question follows the answer the person has in front
    of them, anywhere in the conversation; the model reads that branch."""
    captured: list[dict] = []
    c, kc = app(store, numbered(captured))
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())

    def ask(**body) -> list[tuple[str, dict]]:
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json=body, headers=alice) as r:
            assert r.status_code == 200, r.read()
            return events(r)

    def read_before(i: int) -> list[str]:  # the answers the model read before request i's question
        return [m["content"] for m in captured[i]["messages"] if m["role"] == "assistant"]

    def seq(text: str) -> int:
        return next(t.seq for t in store.turns_of(uuid.UUID(cid)) if t.text == text)
    with c:
        ask(text="Wat is de koopprijs?", thinking=False)
        q1 = seq("Wat is de koopprijs?")
        ask(again=q1)
        assert [(role, text) for role, text, _ in stored(store, cid)] == [
            ("user", "Wat is de koopprijs?"), ("assistant", "Antwoord 1"), ("assistant", "Antwoord 2")]
        assert [m["parent"] for _, _, m in stored(store, cid)] == [None, q1, q1] and read_before(1) == []
        ask(text="En de datum?", after=seq("Antwoord 1"))  # the person switched back to the first answer
        assert read_before(2) == ["Antwoord 1"]
        ask(text="Wie koopt?", after=seq("Antwoord 3"))
        assert read_before(3) == ["Antwoord 1", "Antwoord 3"]
        ask(again=seq("En de datum?"))  # another answer to it, on the same branch
        assert read_before(4) == ["Antwoord 1"]
        ask(text="Wie verkoopt?", after=seq("Antwoord 2"))  # carrying on from the second answer, after all that
        assert read_before(5) == ["Antwoord 2"]
        assert c.get(f"/v1/conversations/{cid}", headers=alice).json()["messages"] == 10


@needs_db
def test_regenerate_asks_a_stored_question_as_it_was_asked_and_nothing_else(store):
    """Review, finding 1: asked again, a question is asked with its own documents and settings, which its stored row
    says, never new ones from the browser. Finding 2: a refused request leaves nothing behind."""
    captured: list[dict] = []
    c, kc = app(store, numbered(captured))
    alice, cid = as_user(kc, ALICE), str(uuid.uuid4())
    with c:
        for body in ({"again": 1}, {"text": "?", "after": 1}):  # a new conversation has nothing to follow or ask again
            r = c.post(f"/v1/conversations/{cid}/questions", json=body, headers=alice)
            assert r.status_code == 409 and r.json()["code"] == "request.conflict"
        assert c.get(f"/v1/conversations/{cid}", headers=alice).status_code == 404  # nothing was started
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?", "thinking": True}, headers=alice) as r:
            events(r)
        first, answer = (t.seq for t in store.turns_of(uuid.UUID(cid)))
        assert c.post(f"/v1/conversations/{cid}/questions", json={"again": first, "thinking": False}, headers=alice).status_code == 422
        assert c.post(f"/v1/conversations/{cid}/questions", json={}, headers=alice).status_code == 422
        for body in ({"again": answer}, {"again": 99}, {"text": "?", "after": first}, {"text": "?", "after": 99}):
            assert c.post(f"/v1/conversations/{cid}/questions", json=body, headers=alice).status_code == 409, body
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"again": first}, headers=alice) as r:
            events(r)
    assert captured[0].get("chat_template_kwargs") == captured[1].get("chat_template_kwargs") == {"enable_thinking": True}  # Thorough both times
    assert [role for role, _, _ in stored(store, cid)] == ["user", "assistant", "assistant"]


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
def test_two_regenerates_at_once_make_one_version(store):
    """Review of #251, finding 1: a double click on *Regenerate* sent two requests; both passed the check before
    either was noted (then each took out "the last" question, an earlier one too). The second is refused."""
    import anyio

    application = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text="A")),
                             load_documents=False, auth=Authenticator.disabled(), conversations=store)
    cid = str(uuid.uuid4())

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(application), base_url="http://test") as c:
            assert (await c.post(f"/v1/conversations/{cid}/questions", json={"text": "q1"})).status_code == 200
            a1 = store.turns_of(uuid.UUID(cid))[1].seq
            assert (await c.post(f"/v1/conversations/{cid}/questions", json={"text": "q2", "after": a1})).status_code == 200
            statuses: list[int] = []
            q2 = next(t.seq for t in store.turns_of(uuid.UUID(cid)) if t.text == "q2")

            async def again():
                statuses.append((await c.post(f"/v1/conversations/{cid}/questions", json={"again": q2})).status_code)
            async with anyio.create_task_group() as g:
                g.start_soon(again)
                g.start_soon(again)
            return sorted(statuses)

    try:
        with TestClient(application) as c:
            assert c.portal.call(go) == [200, 409]
        assert [(role, text) for role, text, _ in stored(store, cid)] == [
            ("user", "q1"), ("assistant", "A"), ("user", "q2"), ("assistant", "A"), ("assistant", "A")]
    finally:
        store._execute("DELETE FROM conversations WHERE id = %s", (uuid.UUID(cid),))


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


# Saving an answer the server stored to its case (step 2).

def test_a_saved_answers_file_name_and_search_text_are_the_chat_uis():
    """As the chat UI's ``answerFileName`` and ``searchText`` make them for an answer it saves itself."""
    from suveryn_api_gateway.conversations import file_name, search_text

    assert file_name("Wat is: de prijs?/..  ") == "Wat is de prijs.docx"
    assert file_name("???") == "answer.docx" and file_name("a" * 90) == "a" * 80 + ".docx"
    assert search_text("Wat is de prijs?", "De prijs is € 1 [1]. Ook [2] , zo [12];") == "Wat is de prijs?\n\nDe prijs is € 1. Ook, zo;"


def test_a_saved_answer_keeps_every_check_the_stored_answer_has():
    """What is copied into the saved answer's content is what the stored answer says beside its words: a check added
    to the one and not the other would be lost from the Word file."""
    from suveryn_api_gateway.conversations import AnsweredTurn, SavedAnswer

    checks = set(AnsweredTurn.model_fields) - {"kind", "parent", "outcome", "failure", "finish_reason", "reasoning", "thought_seconds",
                                                 "thinking_cut", "narrowed_to", "complete", "asked_again"}
    assert checks <= set(SavedAnswer.model_fields), checks - set(SavedAnswer.model_fields)
    # in the shape the chat UI saves and reads (its SavedAnswer, lib/saved.ts)
    assert {f.alias or name for name, f in SavedAnswer.model_fields.items()} == {
        "question", "answer", "answeredOn", "model", "citations", "calculations", "unverifiedFigures", "citationIssues",
        "supportSpans", "instructionLikeSources", "filenames", "turnId", "caseRef"}


@needs_db
def test_an_answer_saved_to_its_case_is_the_one_the_server_stored(store):
    """The browser names the answer; the server copies it with its question, so what is saved is what the model
    wrote. Only an answer written out; the conversation's owner only."""
    from test_cases import NEW, FakeCases
    from test_documents import FakeDocuments

    docs, kc = FakeDocuments(owner=ALICE), FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=store, cases=FakeCases())) as c:
        alice = as_user(kc, ALICE)
        case = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]

        def asked() -> tuple[str, int, int]:
            cid = str(uuid.uuid4())
            with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat is de koopprijs?", "case_id": case},
                          headers=alice) as r:
                events(r)
            question, answer = (t.seq for t in store.turns_of(uuid.UUID(cid)))
            return cid, question, answer
        cid, question, answer = asked()
        r = c.post(f"/v1/conversations/{cid}/turns/{answer}/document", headers=alice)
        assert r.status_code == 201 and r.json()["filename"] == "Wat is de koopprijs.docx"
        _, origin, content = docs.contents[r.json()["id"]]
        assert (origin, content["question"], content["answer"], content["turnId"], content["caseRef"]) == (
            "answer", "Wat is de koopprijs?", "De koopprijs is EUR 412.500,00 [1].", f"{cid}/{answer}", NEW["reference"])
        assert docs.stored_provenance == {"conversation": cid, "message": f"{cid}/{answer}", "turn": answer}
        assert c.post(f"/v1/conversations/{cid}/turns/{answer}/document", headers=alice).status_code == 200  # once
        assert c.post(f"/v1/conversations/{cid}/turns/{question}/document", headers=alice).status_code == 404
        assert c.post(f"/v1/conversations/{cid}/turns/{answer}/document", headers=as_user(kc, BOB)).status_code == 404
        stopped, _, answer = asked()
        store._execute("UPDATE turns SET meta = meta || '{\"outcome\": \"stopped\"}' WHERE conversation_id = %s AND seq = %s",
                       (uuid.UUID(stopped), answer))
        r = c.post(f"/v1/conversations/{stopped}/turns/{answer}/document", headers=alice)
        assert r.status_code == 409 and r.json()["code"] == "request.conflict"  # a stopped answer isn't saved


@needs_db
def test_an_answer_saved_to_its_case_keeps_its_passages_checks_and_a_deleted_source_as_removed(store):
    """What the copy is about (review of step 2): the passages and file names of its sources, its checks, and a
    source deleted since the answer was written, kept out and marked removed as the conversation shows it."""
    from suveryn_rag.store import Scope
    from test_cases import NEW, FakeCases
    from test_documents import DOC as DEED, FakeDocuments

    docs, kc = FakeDocuments(owner=ALICE), FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text="Het kost EUR 412.500,00 [1], de kosten EUR 7.250,00 [1]."))
    with TestClient(create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=store, cases=FakeCases())) as c:
        alice = as_user(kc, ALICE)
        case = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        docs.docs[DEED] = (Scope.case(uuid.UUID(case)), "uploaded")  # the deed is in the case

        def saved(cid: str) -> dict:
            with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat kost het?", "case_id": case,
                                                                              "document_ids": [DEED]}, headers=alice) as r:
                events(r)
            answer = store.turns_of(uuid.UUID(cid))[1]
            r = c.post(f"/v1/conversations/{cid}/turns/{answer.seq}/document", headers=alice)
            assert r.status_code == 201, r.text
            return answer.meta, docs.contents[r.json()["id"]][2]

        stored, content = saved(str(uuid.uuid4()))
        assert content["citations"] == stored["citations"] and content["citations"][0]["text"] == "De koopprijs bedraagt EUR 412.500,00."
        assert content["filenames"] == {DEED: "akte.pdf"}
        assert content["unverifiedFigures"] == stored["unverified_figures"] and stored["unverified_figures"]  # 7.250,00: in no passage
        assert (content["calculations"], content["citationIssues"]) == (stored["calculations"], stored["citation_issues"])
        cid = str(uuid.uuid4())
        with c.stream("POST", f"/v1/conversations/{cid}/questions", json={"text": "Wat kost het?", "case_id": case,
                                                                          "document_ids": [DEED]}, headers=alice) as r:
            events(r)
        store.remove_document(ALICE, uuid.UUID(DEED), False, uuid.UUID(case))  # deleted since the answer was written
        answer = store.turns_of(uuid.UUID(cid))[1].seq
        r = c.post(f"/v1/conversations/{cid}/turns/{answer}/document", headers=alice)
        content = docs.contents[r.json()["id"]][2]
        assert content["citations"][0]["removed"] is True and content["citations"][0]["text"] == "" and content["filenames"] == {}


@needs_db
def test_the_answer_is_stored_before_its_last_event_goes_out(store):
    """The browser reads the conversation back once the answer has ended, for the numbers of the question and its
    answer: the answer must be there by then, so it is stored before ``done`` is sent. (By hand, as the Stop test:
    Starlette's test client reads the whole answer before it gives any of it.)"""
    application = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([])),
                             load_documents=False, auth=Authenticator.disabled(), conversations=store)
    cid = str(uuid.uuid4())
    path = f"/v1/conversations/{cid}/questions"
    when_done: list[list[str]] = []

    async def ask() -> None:
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps({"text": "Wat is de koopprijs?"}).encode(), "more_body": False}
            await anyio.sleep(30)
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and b"event: done" in message.get("body", b""):
                when_done.append([t.role for t in await run_in_threadpool(store.turns_of, uuid.UUID(cid))])

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
                 "root_path": "", "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
                 "client": ("127.0.0.1", 1), "server": ("test", 80)}
        with anyio.fail_after(10):
            await application(scope, receive, send)

    import anyio
    from fastapi.concurrency import run_in_threadpool

    try:
        with TestClient(application) as c:
            c.portal.call(ask)
        assert when_done == [["user", "assistant"]]
    finally:
        store._execute("DELETE FROM conversations WHERE id = %s", (uuid.UUID(cid),))
