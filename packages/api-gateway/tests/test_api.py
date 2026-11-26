"""Gateway tests against a fake llama-server (no GPU needed)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from model_server import garbled as model_garbled
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator
from suveryn_harness import LlamaServerClient, LLMSettings

from conftest import ask

MODEL = "Qwen3.8-27B-UD-Q4_K_M.gguf"


def fake_backend(health_status: int = 200, chat_status: int = 200, garbled: bool | str = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(health_status, json={"status": "ok" if health_status == 200 else "loading"})
        if request.url.path == "/models" and garbled == "models":  # a router's list of models, not one
            return httpx.Response(200, json={"data": "not a list"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": f"/workspace/models/{MODEL}"}]})
        if request.url.path == "/v1/chat/completions":
            if chat_status != 200:
                return httpx.Response(chat_status, text="boom")
            if garbled is True:  # answered, and not what an answer looks like
                return model_garbled()
            chunks = [{"choices": [{"delta": {"content": t}, "finish_reason": None}]} for t in ("Een ", "akte.")]
            chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            chunks.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
            sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
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


def test_an_answer_is_its_done_event(make_client):
    with make_client(fake_backend()) as c:
        r = ask(c, REQ)
    assert r.status_code == 200
    d = r.json()
    assert d["answer"] == "Een akte."
    assert d["citations"] == []
    assert d["model"] == MODEL
    assert d["usage"] == {"prompt_tokens": 12, "completion_tokens": 3}


def test_an_answer_streams_its_events(make_client):
    with make_client(fake_backend()) as c:
        r = ask(c, REQ)
    assert r.headers["content-type"].startswith("text/event-stream")
    events = r.events
    assert [e for e, _ in events] == ["stored", "status", "delta", "delta", "stored", "done"]
    events = [e for e in events if e[0] != "stored"]
    assert events[0][1]["step"] == "writing"  # a plain answer: no document search
    assert "".join(p["text"] for e, p in events if e == "delta") == "Een akte."
    done = events[-1][1]
    assert done["answer"] == "Een akte." and done["citations"] == [] and done["finish_reason"] == "stop"
    assert done["usage"]["completion_tokens"] == 3


def test_a_model_that_cant_be_reached_is_a_part_that_is_down(make_client):
    # one code wherever the model fails (asking, a stream, a playbook's reading), and so one status: 503, as the
    # decision of 12 November says of a part that is down (it was 502 here and 503 in a playbook)
    with make_client(fake_backend(chat_status=500)) as c:
        r = ask(c, REQ)
        assert (r.status_code, r.json()["kind"], r.json()["code"]) == (503, "unavailable", "model.unavailable")


def test_a_model_that_answers_something_unreadable_is_an_unplanned_failure_not_a_part_that_is_down(make_client):
    """suveryn-tracker#164: model.unavailable was said for it too; now a reference the log has, asked or streamed."""
    with make_client(fake_backend(garbled=True)) as c:
        r = ask(c, REQ)
    assert r.events[-1][0] == "error"  # streamed: the answer's last event
    assert (r.status_code, r.json()["kind"], r.json()["code"]) == (500, "internal", "system.internal") and r.json()["params"]["ref"]
    with make_client(fake_backend(garbled="models")) as c:  # the list of models, too
        r = c.get("/v1/models")
        assert (r.status_code, r.json()["code"]) == (500, "system.internal")
        r = ask(c, {**REQ, "model": MODEL})
        assert (r.status_code, r.json()["code"]) == (500, "system.internal")
        assert ask(c, REQ).events[-1][0] == "done"  # not asked for by name: the answer goes ahead


def test_stream_backend_error_event(make_client, caplog):
    with make_client(unreachable_backend()) as c:
        r = ask(c, REQ)
    assert [e for e, _ in r.events][1] == "status" and r.events[-1][0] == "error"
    # the event says it as every message is said: a code with its kind, for the page to word
    said = r.events[-1][1]
    assert (said["kind"], said["code"], said["params"]) == ("unavailable", "model.unavailable", {})
    # the log says what failed (round 4, finding 3), never what the model server said back
    assert any(r.getMessage().startswith("chat stream failed: model backend unreachable (") for r in caplog.records)


def test_a_model_servers_answer_stays_out_of_the_log(make_client, caplog):
    with make_client(fake_backend(chat_status=500)) as c:
        ask(c, REQ)
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("chat stream failed")]
    assert line.startswith("chat stream failed: model backend returned HTTP 500, model ") and "{" not in line


def test_an_empty_question_is_refused(make_client):
    with make_client(fake_backend()) as c:
        assert ask(c, {"text": ""}).status_code == 422


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
    """A llama-server that writes ``words`` words and then keeps generating until the connection closes (*Stop*:
    test_questions.py)."""
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
