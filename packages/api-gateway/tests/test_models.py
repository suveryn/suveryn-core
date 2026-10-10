"""suveryn-tracker#4: choosing which installed model answers.

Against a fake llama-server in router mode (several models, one loaded) and in single-model mode.
"""

import json

import httpx
from fastapi.testclient import TestClient

from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator
from suveryn_engine import LLMSettings, LlamaServerClient

QWEN, MISTRAL = "qwen3.8-27b", "mistral-small-3.2-24b"
CHAT = {"messages": [{"role": "user", "content": "Vraag"}]}


def backend(router: bool, sent: list):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            if not router:
                return httpx.Response(404)
            return httpx.Response(200, json={"data": [{"id": MISTRAL, "status": {"value": "unloaded"}},
                                                      {"id": QWEN, "status": {"value": "loaded"}}]})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "/models/Qwen3.8-27B-UD-Q4_K_M.gguf"}]})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": "Antwoord."}, "finish_reason": "stop"}]})
    return httpx.MockTransport(handler)


def client(router: bool, sent: list) -> TestClient:
    llm = LlamaServerClient(LLMSettings(base_url="http://llm", default_model=QWEN), transport=backend(router, sent))
    return TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled()))


def test_router_lists_installed_models_with_load_state_and_default():
    with client(True, []) as c:
        assert c.get("/v1/models").json() == [
            {"id": MISTRAL, "loaded": False, "default": False},
            {"id": QWEN, "loaded": True, "default": True},
        ]


def test_chosen_model_is_sent_and_reported():
    sent = []
    with client(True, sent) as c:
        r = c.post("/v1/chat", json={**CHAT, "model": MISTRAL})
        assert r.status_code == 200 and r.json()["model"] == MISTRAL and sent[-1]["model"] == MISTRAL
        r = c.post("/v1/chat", json=CHAT)  # no choice: the appliance default
        assert r.json()["model"] == QWEN and sent[-1]["model"] == QWEN


def test_unknown_model_is_refused():
    sent = []
    with client(True, sent) as c:
        assert c.post("/v1/chat", json={**CHAT, "model": "gpt-9"}).status_code == 422
        assert c.post("/v1/chat", json={**CHAT, "model": "../etc/passwd"}).status_code == 422  # pattern
    assert sent == []


def test_single_model_server_lists_its_one_model():
    sent = []
    with client(False, sent) as c:
        assert c.get("/v1/models").json() == [{"id": "Qwen3.8-27B-UD-Q4_K_M.gguf", "loaded": True, "default": True}]
        assert c.post("/v1/chat", json=CHAT).json()["model"] == "Qwen3.8-27B-UD-Q4_K_M.gguf"


def test_health_names_the_default_model_in_router_mode():
    """Not the first entry of the router's list (which may be an unloaded model)."""
    with client(True, []) as c:
        assert c.get("/health").json()["backend"]["model"] == QWEN
