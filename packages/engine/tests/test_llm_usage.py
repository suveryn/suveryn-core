"""suveryn-tracker#7: every model call made for a user reports its token counts, and only counts."""

import asyncio
import json

import httpx
from suveryn_engine import ChatMessage, ChatRequest, LlamaServerClient, LLMSettings, UsageRecord

USAGE = {"prompt_tokens": 1200, "completion_tokens": 85}


def server():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B-UD-Q4_K_M.gguf"}]})
        if request.url.path == "/models":
            return httpx.Response(404)
        body = json.loads(request.content)
        if body["stream"]:
            assert body["stream_options"] == {"include_usage": True}
            events = [{"choices": [{"delta": {"content": "Antwoord"}, "finish_reason": None}]},
                      {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                      {"choices": [], "usage": USAGE}]
            sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": "Antwoord"}, "finish_reason": "stop"}],
                                         "usage": USAGE})
    return httpx.MockTransport(handler)


REQ = ChatRequest(messages=[ChatMessage(role="user", content="Wat is de koopprijs?")])


def run(coro):
    return asyncio.run(coro)


def test_complete_and_stream_report_counts_for_the_user():
    seen: list[UsageRecord] = []

    async def record(r: UsageRecord) -> None:
        seen.append(r)

    async def go():
        llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=server(), on_usage=record)
        await llm.complete(REQ, user="user-a")
        async for _ in llm.stream(REQ, user="user-b", kind="summary"):
            pass
        await llm.complete(REQ)  # no user (e.g. an operator tool): nothing recorded
        await llm.aclose()

    run(go())
    assert [(r.user, r.kind, r.model, r.prompt_tokens, r.completion_tokens, r.total_tokens) for r in seen] == [
        ("user-a", "chat", "Qwen3.8-27B-UD-Q4_K_M.gguf", 1200, 85, 1285),
        ("user-b", "summary", "Qwen3.8-27B-UD-Q4_K_M.gguf", 1200, 85, 1285),
    ]
    assert set(vars(seen[0])) == {"user", "kind", "model", "prompt_tokens", "completion_tokens"}  # counts only, no text


def test_a_failing_recorder_never_breaks_the_answer():
    async def broken(_: UsageRecord) -> None:
        raise RuntimeError("database down")

    async def go():
        llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=server(), on_usage=broken)
        answer = (await llm.complete(REQ, user="user-a")).answer
        text = "".join([c.text async for c in llm.stream(REQ, user="user-a")])
        await llm.aclose()
        return answer, text

    assert run(go()) == ("Antwoord", "Antwoord")
