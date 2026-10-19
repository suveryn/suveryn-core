"""Gateway tests against a fake llama-server (no GPU needed)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator
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
        # Sign-in is covered in test_auth.py; these tests exercise the API behind it.
        return TestClient(create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=transport),
                                     load_documents=False, auth=Authenticator.disabled()))
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
    assert [e for e, _ in events] == ["status", "delta", "delta", "done"]
    assert events[0][1]["step"] == "writing"  # a plain answer: no document search
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
    assert body.startswith("event: status") and body.rstrip().split("\n\n")[-1].startswith("event: error")


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
    # public: states only, no internal address or error text
    assert r.json()["backend"] == {"reachable": True, "status": "ok", "url": None, "model": MODEL, "detail": None}
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


def endless_backend(state: dict, words: int):
    """A llama-server that writes ``words`` words and then keeps generating until the connection closes."""
    import asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": f"/workspace/models/{MODEL}"}]})
        if request.url.path != "/v1/chat/completions":
            return httpx.Response(404)

        async def body():
            try:
                for i in range(words):
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': f'word{i} '}, 'finish_reason': None}]})}\n\n".encode()
                await asyncio.sleep(3600)
                yield b"data: [DONE]\n\n"
            finally:
                state["closed"] = True

        return httpx.Response(200, content=body(), headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("words, stop_after", [(0, "status"), (2, "delta")])
def test_closing_the_connection_stops_the_model(words, stop_after):
    """*Stop* (docs/design/sidebar.md §5): the browser closes the request. The gateway notices at once, also
    before the first word while the model reads, and closes its own connection to llama-server."""
    import anyio

    state: dict = {}
    app = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=endless_backend(state, words)),
                     load_documents=False, auth=Authenticator.disabled())

    async def ask() -> list[str]:
        gone = anyio.Event()
        events: list[str] = []
        body = json.dumps({**REQ, "stream": True}).encode()
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                events.extend(line[7:] for line in message["body"].decode().split("\n") if line.startswith("event: "))
                if stop_after in events and events.count("delta") >= (2 if stop_after == "delta" else 0):
                    gone.set()  # the person pressed Stop

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/v1/chat", "raw_path": b"/v1/chat", "query_string": b"",
                 "root_path": "", "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
                 "client": ("127.0.0.1", 1), "server": ("test", 80)}
        with anyio.fail_after(10):  # without the stop, the fake model would write for an hour
            await app(scope, receive, send)
        return events

    with TestClient(app) as c:  # runs the app's start-up, then the request on the same event loop
        events = c.portal.call(ask)
    assert state.get("closed")  # llama-server's connection was closed: it stops generating
    assert "done" not in events and "error" not in events
