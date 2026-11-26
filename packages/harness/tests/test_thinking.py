"""Thinking before answering (*Thorough*, docs/design/chat-ui.md §5): asked per request, only for a model
that can; the reasoning kept apart from the answer, whether llama-server sends it apart or in the text."""

import asyncio
import json

import httpx
import pytest
from suveryn_harness import (
    ChatMessage,
    ChatRequest,
    ChatService,
    Delta,
    Done,
    LlamaServerClient,
    LLMSettings,
    Status,
    Thinking,
)
from suveryn_harness.thinking import THINKING_TOKENS, ThinkSplitter


def streamed(text: str) -> httpx.Response:
    """An answer as llama-server streams it: every call the harness makes streams (suveryn-tracker#270)."""
    body = f"data: {json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': None}]})}\n\n"
    body += f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\ndata: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def ask(**over) -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role="user", content="What is the price?")], **over)


def server(events: list[dict], state: dict):
    """A llama-server that streams ``events`` (deltas)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(404)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": state.get("model", "Qwen3.8-27B.gguf")}]})
        state["payload"] = json.loads(request.content)
        body = "".join(f"data: {json.dumps({'choices': [{'delta': e, 'finish_reason': None}]})}\n\n" for e in events)
        body += f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


def client(events, state, default="qwen3.8-27b") -> LlamaServerClient:
    return LlamaServerClient(LLMSettings(base_url="http://llm", default_model=default), transport=server(events, state))


@pytest.mark.parametrize("thinking", [True, False])
def test_a_model_that_can_think_is_told_per_request(thinking):
    asyncio.run(_test_a_model_that_can_think_is_told_per_request(thinking))


async def _test_a_model_that_can_think_is_told_per_request(thinking):
    state: dict = {}
    await client([{"content": "EUR 1."}], state).complete(ask(thinking=thinking, max_tokens=1000))
    assert state["payload"]["chat_template_kwargs"] == {"enable_thinking": thinking}
    assert state["payload"]["max_tokens"] == 1000 + (THINKING_TOKENS if thinking else 0)


def test_a_model_that_cant_think_is_never_asked_to():
    asyncio.run(_test_a_model_that_cant_think_is_never_asked_to())


async def _test_a_model_that_cant_think_is_never_asked_to():
    state: dict = {}
    await client([{"content": "EUR 1."}], state, default="mistral-small-3.2-24b").complete(ask(thinking=True, max_tokens=1000))
    assert "chat_template_kwargs" not in state["payload"] and state["payload"]["max_tokens"] == 1000


def test_the_reasoning_llama_server_sends_apart_stays_apart():
    asyncio.run(_test_the_reasoning_llama_server_sends_apart_stays_apart())


async def _test_the_reasoning_llama_server_sends_apart_stays_apart():
    events = [{"reasoning_content": "The deed says "}, {"reasoning_content": "1."}, {"content": "EUR 1."}]
    got = [c async for c in client(events, {}).stream(ask(thinking=True))]
    assert "".join(c.reasoning for c in got) == "The deed says 1." and "".join(c.text for c in got) == "EUR 1."
    whole = await client(events, {}).complete(ask(thinking=True))
    assert whole.answer == "EUR 1." and whole.reasoning == "The deed says 1."


def test_reasoning_left_in_the_text_is_taken_out_even_split_over_chunks():
    asyncio.run(_test_reasoning_left_in_the_text_is_taken_out_even_split_over_chunks())


async def _test_reasoning_left_in_the_text_is_taken_out_even_split_over_chunks():
    events = [{"content": "<thi"}, {"content": "nk>The deed says 1.</th"}, {"content": "ink>\n\nEUR 1."}]
    got = [c async for c in client(events, {}).stream(ask(thinking=True))]
    assert "".join(c.reasoning for c in got) == "The deed says 1." and "".join(c.text for c in got) == "EUR 1."
    assert (await client(events, {}).complete(ask(thinking=True))).answer == "EUR 1."


def test_the_splitter_leaves_an_ordinary_answer_alone():
    s = ThinkSplitter()
    assert s.feed("The price is <think> not a tag") == ("", "The price is <think> not a tag")
    s = ThinkSplitter()
    assert s.feed("<") == ("", "") and s.flush() == ("", "<")  # never a tag after all
    s = ThinkSplitter()
    assert s.feed("<think>still thinking") == ("still thinking", "") and s.flush() == ("", "")


def test_the_service_streams_the_reasoning_then_the_answer_with_its_duration():
    asyncio.run(_test_the_service_streams_the_reasoning_then_the_answer_with_its_duration())


async def _test_the_service_streams_the_reasoning_then_the_answer_with_its_duration():
    events = [{"reasoning_content": "The deed says 1."}, {"content": "EUR 1."}]
    seen = [e async for e in ChatService(client(events, {})).answer_stream(ask(thinking=True), "alice")]
    assert [type(e).__name__ for e in seen] == ["Status", "Status", "Thinking", "Delta", "Done"]
    assert seen[1] == Status("thinking") and isinstance(seen[2], Thinking) and isinstance(seen[3], Delta)
    done = seen[-1]
    assert isinstance(done, Done) and done.response.answer == "EUR 1." and done.response.reasoning == "The deed says 1."
    assert done.response.thought_seconds is not None and done.response.thought_seconds >= 0


def test_a_fast_answer_has_no_reasoning():
    asyncio.run(_test_a_fast_answer_has_no_reasoning())


async def _test_a_fast_answer_has_no_reasoning():
    seen = [e async for e in ChatService(client([{"content": "EUR 1."}], {})).answer_stream(ask(), "alice")]
    done = seen[-1]
    assert done.response.reasoning == "" and done.response.thought_seconds is None
    assert not any(isinstance(e, Thinking) for e in seen)


def test_a_grounded_answer_that_cites_nothing_is_logged_by_counts_only(caplog):
    """suveryn-tracker#54: the follow-ups that cite nothing can be studied on real documents, without their text."""
    from suveryn_harness import Citation, SourceRef

    async def retriever(question, ids, k, owner, case_id):
        return [(Citation(text="Price: EUR 1.", source=SourceRef(document_id="d1", page=1)), "deed.pdf")], True

    async def run():
        service = ChatService(client([{"content": "Secret answer text."}], {}), retriever)
        req = ChatRequest(messages=[ChatMessage(role="user", content="Secret question?"),
                                    ChatMessage(role="assistant", content="Earlier [1]."),
                                    ChatMessage(role="user", content="And then?")], document_ids=["d1"])
        return [e async for e in service.answer_stream(req, "alice")]

    with caplog.at_level("INFO", logger="suveryn.harness"):
        asyncio.run(run())
    lines = [r.getMessage() for r in caplog.records if "cites no passage" in r.getMessage()]
    assert lines == [("grounded answer cites no passage: passages=1 complete=True earlier_answers=1 earlier_markers=1 "
                      "answer_chars=19 thinking=False")]
    assert not any("Secret" in r.getMessage() or "EUR" in r.getMessage() for r in caplog.records)


def test_every_answer_is_told_to_address_the_person_formally():
    """Pod check of f0ff96c: a plain answer in Dutch said "je" and "jouw"."""
    from suveryn_harness.grounding import GROUNDED_INSTRUCTIONS, REGISTER

    state: dict = {}
    asyncio.run(_collect(ChatService(client([{"content": "U kunt…"}], state)).answer_stream(ask(), "alice")))
    first = state["payload"]["messages"][0]
    assert first["role"] == "system" and '"u"' in first["content"] and "vous" in first["content"]
    assert REGISTER in GROUNDED_INSTRUCTIONS and "{register}" not in GROUNDED_INSTRUCTIONS


async def _collect(events):
    return [e async for e in events]


def _thinker(reasoning_pieces: int, finish: str = "length"):
    """A model that, asked to think, thinks in ``reasoning_pieces`` pieces and stops with ``finish`` before a word of
    answer; asked not to, answers "EUR 1."."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/models", "/v1/models"):
            return httpx.Response(404 if request.url.path == "/models" else 200, json={"data": [{"id": "Qwen3.8-27B.gguf"}]})
        payload = json.loads(request.content)
        thinking = payload.get("chat_template_kwargs", {}).get("enable_thinking")
        events = ([{"reasoning_content": "Secret "}] * reasoning_pieces) if thinking else [{"content": "EUR 1."}]
        body = "".join(f"data: {json.dumps({'choices': [{'delta': e, 'finish_reason': None}]})}\n\n" for e in events)
        body += f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': finish if thinking else 'stop'}]})}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})
    return LlamaServerClient(LLMSettings(base_url="http://llm", default_model="qwen3.8-27b"), transport=httpx.MockTransport(handler))


def test_thinking_to_the_length_limit_without_an_answer_is_asked_again_without_thinking(caplog):
    """Pod check of a318b65: Thorough thought for three minutes and the answer came back empty, with no word why.
    VM regression 03c8f74, finding 1: it still did on wide questions. Now it is asked again without thinking,
    and the answer says so (``thinking_cut``); the log has counts only."""
    with caplog.at_level("INFO", logger="suveryn.harness"):
        seen = asyncio.run(_collect(ChatService(_thinker(3)).answer_stream(ask(thinking=True), "alice")))
    done = seen[-1].response
    assert done.answer == "EUR 1." and done.thinking_cut and done.finish_reason == "stop"
    assert any("asked again without thinking" in r.getMessage() for r in caplog.records)
    assert not any("Secret" in r.getMessage() for r in caplog.records)


def test_thinking_past_its_allowance_is_stopped_before_the_length_limit():
    seen = asyncio.run(_collect(ChatService(_thinker(THINKING_TOKENS + 50, finish="stop")).answer_stream(ask(thinking=True), "alice")))
    done = seen[-1].response
    assert done.answer == "EUR 1." and done.thinking_cut
    assert sum(isinstance(e, Thinking) for e in seen) == THINKING_TOKENS + 1  # stopped at the allowance, not at its end


def test_without_streaming_thinking_without_an_answer_is_asked_again_too(caplog):
    """VM regression 9c97d76, findings 1 and 9: an answer asked for whole still came back empty after three
    minutes, and ``thought_seconds`` was empty."""
    with caplog.at_level("INFO", logger="suveryn.harness"):
        done = asyncio.run(ChatService(_thinker(3)).answer(ask(thinking=True), "alice"))
    assert done.answer == "EUR 1." and done.thinking_cut and done.reasoning
    assert done.thought_seconds is not None
    assert any("asked again without thinking" in r.getMessage() for r in caplog.records)
    plain = asyncio.run(ChatService(_thinker(0)).answer(ask(thinking=False), "alice"))
    assert plain.answer == "EUR 1." and not plain.thinking_cut and plain.thought_seconds is None


@pytest.mark.parametrize("whole", [True, False])
def test_a_grounded_answer_says_whether_it_saw_the_documents_whole(whole):
    """A playbook's read tells the person when the documents were longer than one reading takes (the answer read
    the best-matching passages, not every page): the answer carries the retriever's word for it, whole or streamed."""
    from suveryn_harness import Citation, SourceRef

    async def retriever(question, ids, k, owner, case_id):
        return [(Citation(text="Price: EUR 1.", source=SourceRef(document_id="d1", page=1)), "deed.pdf")], whole

    async def run():
        req = ChatRequest(messages=[ChatMessage(role="user", content="The price?")], document_ids=["d1"])
        whole_answer = await ChatService(client([{"content": "EUR 1 [1]."}], {}), retriever).answer(req, "alice")
        streamed = [e async for e in ChatService(client([{"content": "EUR 1 [1]."}], {}), retriever).answer_stream(req, "alice")]
        plain = await ChatService(client([{"content": "EUR 1."}], {}), retriever).answer(ask(), "alice")
        return whole_answer, streamed[-1].response, plain

    whole_answer, streamed, plain = asyncio.run(run())
    assert whole_answer.complete is whole and streamed.complete is whole
    assert plain.complete is None  # no documents, nothing to have read in part


def test_when_asking_again_gets_an_answer_that_cant_be_read_the_first_answer_stands():
    """Asking again is a second chance, not a new failure: a garbled second answer keeps the first, with its warning (#164)."""
    from suveryn_harness import Citation, SourceRef

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/models", "/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B.gguf"}]})
        calls.append(1)
        if len(calls) > 1:
            return httpx.Response(200, text="data: {not json\n\n", headers={"content-type": "text/event-stream"})
        return streamed("Samen 1.000 aandelen [1].")

    async def retriever(question, ids, k, owner, case_id):
        return [(Citation(text="A neemt 400 aandelen, B neemt 600 aandelen.", source=SourceRef(document_id="d1", page=1)), "akte.pdf")], True

    service = ChatService(LlamaServerClient(LLMSettings(base_url="http://llm", default_model="q"), transport=httpx.MockTransport(handler)), retriever)
    r = asyncio.run(service.answer(ChatRequest(messages=[ChatMessage(role="user", content="Hoeveel aandelen samen?")], document_ids=["d1"]), "alice"))
    assert len(calls) == 2 and r.asked_again and r.unverified_figures == ["1.000"] and "1.000" in r.answer


@pytest.mark.parametrize("stream", [False, True])
def test_an_answer_with_a_figure_it_worked_out_is_asked_again(stream):
    """The model must never compute: an answer with a figure in no passage that the server didn't compute is asked
    once more, told which figure; a clean second answer replaces it (GPU round of 10 November 2026)."""
    from suveryn_harness import Citation, SourceRef

    replies = ["Samen 1.000 aandelen [1].", "Samen [[calc: 400 + 600]] aandelen [1]."]
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/models", "/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B.gguf"}]})
        payload = json.loads(request.content)
        seen.append(payload["messages"][-1]["content"])
        text = replies[min(len(seen) - 1, 1)]
        return streamed(text)

    async def retriever(question, ids, k, owner, case_id):
        return [(Citation(text="A neemt 400 aandelen, B neemt 600 aandelen.", source=SourceRef(document_id="d1", page=1)), "akte.pdf")], True

    async def run():
        service = ChatService(LlamaServerClient(LLMSettings(base_url="http://llm", default_model="q"), transport=httpx.MockTransport(handler)), retriever)
        req = ChatRequest(messages=[ChatMessage(role="user", content="Hoeveel aandelen samen?")], document_ids=["d1"])
        if stream:
            return [e async for e in service.answer_stream(req, "alice")][-1].response
        return await service.answer(req, "alice")

    r = asyncio.run(run())
    assert r.asked_again and r.unverified_figures == [] and "400 + 600 = 1000" in r.answer
    assert len(seen) == 2 and "1.000" in seen[1] and "[[calc:" in seen[1]  # told which figure, and how


SELLER = "The seller is John Smith, living in Ghent, who sold 12.500 shares on 12 March 2021."
BUYER = "The buyer is Anna Peeters, living in Bruges."


def _two_parties(replies: list[str], seen: list[str], schema: dict | None = None, stream: bool = False, fail_after: int = 0):
    """A question about two passages (the seller on page 1, the buyer on page 2), answered by ``replies`` in turn;
    with ``fail_after``, the model server fails from that call on."""
    from suveryn_harness import Citation, SourceRef

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/models", "/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B.gguf"}]})
        payload = json.loads(request.content)
        seen.append(payload["messages"][-1]["content"])
        if fail_after and len(seen) > fail_after:
            return httpx.Response(500, text="busy")
        text = replies[min(len(seen) - 1, len(replies) - 1)]
        return streamed(text)

    async def retriever(question, ids, k, owner, case_id):
        return [(Citation(text=SELLER, source=SourceRef(document_id="d1", page=1)), "deed.pdf"),
                (Citation(text=BUYER, source=SourceRef(document_id="d1", page=2)), "deed.pdf")], True

    async def run():
        service = ChatService(LlamaServerClient(LLMSettings(base_url="http://llm", default_model="q"), transport=httpx.MockTransport(handler)), retriever)
        req = ChatRequest(messages=[ChatMessage(role="user", content="Who is the buyer?")], document_ids=["d1"], json_schema=schema)
        if stream:
            return [e async for e in service.answer_stream(req, "alice")][-1].response
        return await service.answer(req, "alice")

    return asyncio.run(run())


@pytest.mark.parametrize("stream", [False, True])
def test_a_name_cited_to_the_wrong_passage_is_asked_again(stream, caplog):
    """The model had the name and cited the wrong passage (suveryn-tracker#109): it is told once which passage holds
    it, and a second answer that cites it right replaces the first. The log counts; it never names."""
    seen: list[str] = []
    with caplog.at_level("INFO", logger="suveryn.harness"):
        r = _two_parties(["The buyer is Anna Peeters [1].", "The buyer is Anna Peeters [2]."], seen, stream=stream)
    assert len(seen) == 2 and '"Peeters" is in [2], not in [1]' in seen[1] and '"Anna" is in [2], not in [1]' in seen[1]
    assert r.asked_again and r.citation_issues == [] and r.answer == "The buyer is Anna Peeters [2]."
    assert "Peeters" not in caplog.text and "asked again: names cited" in caplog.text and "is kept" in caplog.text


@pytest.mark.parametrize("second", [
    "The buyer lives in Bruges [2].",                     # the name dropped: fewer flags, but no fix
    "The buyer is Anna Peeters [1], of Bruges [1].",      # more flags than before
    "The buyer is Annabel Peetersen [2].",                # the names only inside other words: not stated
    "",                                                   # nothing
    "The buyer is Anna Peeters [2], who paid 250.000 [2].",  # cited right, but a figure in no passage
])
def test_a_second_answer_that_isnt_better_leaves_the_first(second):
    """The second answer is kept only when it has fewer citation issues, no figure in no passage, and still states
    every name the first misplaced, as a word; otherwise the first stands, with its flags."""
    seen: list[str] = []
    r = _two_parties(["The buyer is Anna Peeters [1].", second], seen)
    assert len(seen) == 2 and r.asked_again and r.answer == "The buyer is Anna Peeters [1]."
    assert {i.item for i in r.citation_issues} == {"Anna", "Peeters"}


def test_when_the_second_call_fails_the_first_answer_stands():
    seen: list[str] = []
    r = _two_parties(["The buyer is Anna Peeters [1]."], seen, fail_after=1)
    assert len(seen) == 2 and r.asked_again and r.answer == "The buyer is Anna Peeters [1]." and r.citation_issues


def test_only_a_misplaced_name_asks_again():
    """A clean answer, a figure or a date cited to the wrong passage, a name spelled differently, and a playbook's
    read (an answer of a fixed shape, checked value by value) are not asked again. (A place is a name to the check.)"""
    from suveryn_harness.support import misplaced_names

    for reply in ["The buyer is Anna Peeters [2].",      # cited right
                  "The seller sold 12.500 shares [2].",  # a figure in another passage: not a name
                  "The sale was on 12 March 2021 [2]."]:  # a date in another passage: not a name
        seen: list[str] = []
        r = _two_parties([reply], seen)
        assert not r.asked_again and len(seen) == 1, reply
    seen = []
    schema = {"type": "object", "properties": {"buyer": {"type": "string"}}}
    assert not _two_parties(["The buyer is Anna Peeters [1]."], seen, schema=schema).asked_again and len(seen) == 1
    from suveryn_harness import CitationIssue
    spelled = CitationIssue(marker=0, n=1, item="Petters", found_in=[2], written_as="Peeters")
    assert misplaced_names([spelled]) == []


def test_a_figure_in_no_passage_comes_first():
    """An answer with both a figure in no passage and a misplaced name is asked once, for the figure: one retry at most."""
    seen: list[str] = []
    r = _two_parties(["The buyer Anna Peeters [1] paid 250.000 [1].", "The buyer is Anna Peeters [2]."], seen)
    assert len(seen) == 2 and "250.000" in seen[1] and "[[calc:" in seen[1] and "is in [2]" not in seen[1]
    assert r.asked_again


@pytest.mark.parametrize("second", ["", "Together 1.000 shares [1]."])
def test_a_figure_retry_that_isnt_clean_leaves_the_first(second, caplog):
    """The figure retry keeps the first answer when the second is empty or still has the figure, and the log says so."""
    from suveryn_harness import Citation, SourceRef

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/models", "/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B.gguf"}]})
        seen.append(1)
        return streamed("Together 1.000 shares [1]." if len(seen) == 1 else second)

    async def retriever(question, ids, k, owner, case_id):
        return [(Citation(text="A takes 400 shares, B takes 600 shares.", source=SourceRef(document_id="d1", page=1)), "deed.pdf")], True

    service = ChatService(LlamaServerClient(LLMSettings(base_url="http://llm", default_model="q"), transport=httpx.MockTransport(handler)), retriever)
    with caplog.at_level("INFO", logger="suveryn.harness"):
        r = asyncio.run(service.answer(ChatRequest(messages=[ChatMessage(role="user", content="How many shares together?")],
                                                   document_ids=["d1"]), "alice"))
    assert len(seen) == 2 and r.asked_again and r.answer == "Together 1.000 shares [1]." and r.unverified_figures == ["1.000"]
    assert "isn't better; the first stands" in caplog.text
