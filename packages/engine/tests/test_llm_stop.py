"""Stopping a streamed answer (docs/design/sidebar.md §5): the connection to llama-server is closed, so it
stops generating, and the tokens used until then are still recorded for the user (suveryn-tracker#7)."""

import asyncio
import json

import httpx
import pytest
from suveryn_engine import (
    ChatMessage,
    ChatRequest,
    LlamaServerClient,
    LLMSettings,
    UsageRecord,
)

REQ = ChatRequest(messages=[ChatMessage(role="user", content="What is the price?")])


def chunk(text: str, timings: dict | None = None) -> bytes:
    event = {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
    if timings is not None:
        event["timings"] = timings
    return f"data: {json.dumps(event)}\n\n".encode()


def endless_server(state: dict, with_timings: bool = True):
    """A llama-server that writes two words, then keeps the stream open as if still generating."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "model.gguf"}]})
        if request.url.path == "/models":
            return httpx.Response(404)
        state["payload"] = json.loads(request.content)

        async def body():
            try:
                yield chunk("The ", {"prompt_n": 1800, "predicted_n": 1} if with_timings else None)
                yield chunk("price", {"prompt_n": 1800, "predicted_n": 2} if with_timings else None)
                await asyncio.sleep(3600)  # still generating
                yield chunk(" never sent")
            finally:
                state["closed"] = True  # the connection is gone: llama-server stops the task

        return httpx.Response(200, content=body(), headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


async def read_two_then(stop: str, with_timings: bool = True):
    state: dict = {}
    seen: list[UsageRecord] = []

    async def record(r: UsageRecord) -> None:
        seen.append(r)

    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=endless_server(state, with_timings), on_usage=record)
    got: list[str] = []
    two = asyncio.Event()

    async def consume():
        stream = llm.stream(REQ, user="user-a")
        try:
            async for c in stream:
                got.append(c.text)
                if len(got) == 2:
                    two.set()
                    if stop == "close":
                        break
        finally:
            await stream.aclose()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(two.wait(), 5)
    if stop == "cancel":  # as the gateway does when the person stops or goes away
        task.cancel()
    with pytest.raises(asyncio.CancelledError) if stop == "cancel" else _nothing():
        await asyncio.wait_for(task, 5)
    await llm.aclose()
    return got, seen, state


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("stop", ["close", "cancel"])
def test_a_stopped_stream_closes_the_connection_and_records_what_was_used(stop):
    got, seen, state = asyncio.run(read_two_then(stop))
    assert got == ["The ", "price"]
    assert state["closed"]  # llama-server sees the connection close and stops generating
    assert state["payload"]["timings_per_token"] is True
    assert [(r.user, r.prompt_tokens, r.completion_tokens) for r in seen] == [("user-a", 1800, 2)]


def test_without_running_counts_the_words_received_are_recorded():
    _, seen, state = asyncio.run(read_two_then("cancel", with_timings=False))
    assert state["closed"]
    assert [(r.prompt_tokens, r.completion_tokens) for r in seen] == [(0, 2)]  # the prompt isn't known
