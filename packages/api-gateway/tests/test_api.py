"""Gateway tests against a fake llama-server (no GPU needed)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_engine import LlamaServerClient, LLMSettings

MODEL = "Qwen3.8-27B-UD-Q4_K_M.gguf"


def fake_backend(health_status: int = 200, chat_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(health_status, json={"status": "ok" if health_status == 200 else "loading"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": f"/workspace/models/{MODEL}"}]})
        if request.url.path == "/v1/chat/completions":
            if chat_status != 200:
                return httpx.Response(chat_status, text="boom")
            body = json.loads(request.content)
            if body["stream"]:
                chunks = [{"choices": [{"delta": {"content": t}, "finish_reason": None}]} for t in ("Een ", "akte.")]
                chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
                chunks.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
                sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
                return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
            return httpx.Response(200, json={
                "id": "chatcmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "Een akte."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            })
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def unreachable_backend():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)
    return httpx.MockTransport(handler)


@pytest.fixture
def make_client():
    def _make(transport):
        return TestClient(create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=transport),
                                     load_documents=False))
    return _make


REQ = {"messages": [{"role": "user", "content": "Wat is een akte?"}]}


def test_chat_json_shape(make_client):
    with make_client(fake_backend()) as c:
        r = c.post("/v1/chat", json=REQ)
    assert r.status_code == 200
    d = r.json()
    assert d["answer"] == "Een akte."
    assert d["citations"] == []
    assert d["model"] == MODEL
    assert d["usage"] == {"prompt_tokens": 12, "completion_tokens": 3}


def test_chat_stream_events(make_client):
    with make_client(fake_backend()) as c, c.stream("POST", "/v1/chat", json={**REQ, "stream": True}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:]))
                  for b in r.read().decode().strip().split("\n\n")]
    assert [e for e, _ in events] == ["delta", "delta", "done"]
    assert "".join(p["text"] for e, p in events if e == "delta") == "Een akte."
    done = events[-1][1]
    assert done["answer"] == "Een akte." and done["citations"] == [] and done["finish_reason"] == "stop"
    assert done["usage"]["completion_tokens"] == 3


def test_chat_backend_error_is_502(make_client):
    with make_client(fake_backend(chat_status=500)) as c:
        assert c.post("/v1/chat", json=REQ).status_code == 502


def test_stream_backend_error_event(make_client):
    with make_client(unreachable_backend()) as c, c.stream("POST", "/v1/chat", json={**REQ, "stream": True}) as r:
        body = r.read().decode()
    assert body.startswith("event: error")


def test_empty_messages_rejected(make_client):
    with make_client(fake_backend()) as c:
        assert c.post("/v1/chat", json={"messages": []}).status_code == 422


def test_no_cdn_docs_pages_by_default(make_client):
    with make_client(fake_backend()) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/redoc").status_code == 404
        assert c.get("/openapi.json").status_code == 200


def test_health_ok(make_client):
    with make_client(fake_backend()) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["backend"] == {"reachable": True, "status": "ok", "url": "http://llm", "model": MODEL, "detail": None}
    assert r.json()["documents"] == {"status": "unavailable", "detail": None}


def test_health_loading_is_503(make_client):
    with make_client(fake_backend(health_status=503)) as c:
        r = c.get("/health")
    assert r.status_code == 503 and r.json()["backend"]["status"] == "loading"


def test_health_unreachable_is_503(make_client):
    with make_client(unreachable_backend()) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert r.json()["backend"]["reachable"] is False
