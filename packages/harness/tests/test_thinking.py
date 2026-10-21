"""Thinking before answering (*Thorough*, docs/design/sidebar.md §5): asked per request, only for a model
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


def ask(**over) -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role="user", content="What is the price?")], **over)


def server(events: list[dict], state: dict):
    """A llama-server that streams ``events`` (deltas), or answers them joined when not streaming."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(404)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": state.get("model", "Qwen3.8-27B.gguf")}]})
        state["payload"] = payload = json.loads(request.content)
        if not payload["stream"]:
            message = {"content": "".join(e.get("content", "") for e in events)}
            if any("reasoning_content" in e for e in events):
                message["reasoning_content"] = "".join(e.get("reasoning_content", "") for e in events)
            return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}], "usage": {}})
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
    """Pod check of 7c48279: a plain answer in Dutch said "je" and "jouw"."""
    from suveryn_harness.grounding import GROUNDED_INSTRUCTIONS, REGISTER

    state: dict = {}
    asyncio.run(_collect(ChatService(client([{"content": "U kunt…"}], state)).answer_stream(ask(), "alice")))
    first = state["payload"]["messages"][0]
    assert first["role"] == "system" and '"u"' in first["content"] and "vous" in first["content"]
    assert REGISTER in GROUNDED_INSTRUCTIONS and "{register}" not in GROUNDED_INSTRUCTIONS


async def _collect(events):
    return [e async for e in events]
