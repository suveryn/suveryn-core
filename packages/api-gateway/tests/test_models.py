"""suveryn-tracker#4: choosing which installed model answers.

Against a fake llama-server in router mode (several models, one loaded) and in single-model mode.
"""

import json

import httpx
from fastapi.testclient import TestClient
from model_server import streamed
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator
from suveryn_harness import LlamaServerClient, LLMSettings

from conftest import ask

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
        return streamed("Antwoord.")
    return httpx.MockTransport(handler)


def client(router: bool, sent: list) -> TestClient:
    llm = LlamaServerClient(LLMSettings(base_url="http://llm", default_model=QWEN), transport=backend(router, sent))
    return TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled()))


def test_router_lists_installed_models_with_load_state_and_default():
    with client(True, []) as c:
        assert c.get("/v1/models").json() == [
            {"id": MISTRAL, "loaded": False, "default": False, "thinks": False},
            {"id": QWEN, "loaded": True, "default": True, "thinks": True},  # a Qwen3 can think (chat-ui.md)
        ]


def test_chosen_model_is_sent_and_reported():
    sent = []
    with client(True, sent) as c:
        r = ask(c, {**CHAT, "model": MISTRAL})
        assert r.status_code == 200 and r.json()["model"] == MISTRAL and sent[-1]["model"] == MISTRAL
        r = ask(c, CHAT)  # no choice: the appliance default
        assert r.json()["model"] == QWEN and sent[-1]["model"] == QWEN


def test_unknown_model_is_refused():
    sent = []
    with client(True, sent) as c:
        assert ask(c, {**CHAT, "model": "gpt-9"}).status_code == 422
        assert ask(c, {**CHAT, "model": "../etc/passwd"}).status_code == 422  # pattern
    assert sent == []


def test_single_model_server_lists_its_one_model():
    sent = []
    with client(False, sent) as c:
        assert c.get("/v1/models").json() == [{"id": "Qwen3.8-27B-UD-Q4_K_M.gguf", "loaded": True, "default": True, "thinks": True}]
        assert ask(c, CHAT).json()["model"] == "Qwen3.8-27B-UD-Q4_K_M.gguf"


def test_health_names_the_default_model_in_router_mode():
    """Not the first entry of the router's list (which may be an unloaded model)."""
    with client(True, []) as c:
        assert c.get("/health").json()["backend"]["model"] == QWEN


def stream_events(c: TestClient, body: dict) -> list[tuple[str, dict]]:
    """The answer's events, without the numbers the conversation gives its turns."""
    return [e for e in ask(c, body).events if e[0] != "stored"]


def test_stream_says_when_the_chosen_model_has_to_load_first():
    """suveryn-tracker#6: the status names the real step; loading only when the model isn't loaded."""
    with client(True, []) as c:
        first = stream_events(c, {**CHAT, "model": MISTRAL})[0]
        assert first == ("status", {"step": "loading_model", "passages": None, "complete": None, "model": MISTRAL})
        assert stream_events(c, {**CHAT, "model": QWEN})[0][1]["step"] == "writing"  # already loaded


def test_every_answer_of_models_is_what_the_description_says():
    """The chat UI's code for the models is generated from the description (suveryn-tracker#237)."""
    import httpx
    from described import Checked
    from suveryn_api_gateway.auth import OIDCProvider
    from test_auth import SETTINGS, FakeKeycloak
    from test_usage import BOB, as_user

    kc = FakeKeycloak()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))

    def app(transport):
        return create_app(LlamaServerClient(LLMSettings(base_url="http://llm", default_model=QWEN), transport=transport),
                          load_documents=False, auth=auth)

    with TestClient(app(backend(True, []))) as c:
        check = Checked(c, "models")
        assert check("GET", "/v1/models", 401, keep="signed_out").json()["code"] == "auth.signed_out"
        assert [m["id"] for m in check("GET", "/v1/models", 200, keep="installed", headers=as_user(kc, BOB)).json()] == [MISTRAL, QWEN]

        def away(request):
            raise httpx.ConnectError("refused")
        with TestClient(app(httpx.MockTransport(away))) as down:
            check.client = down
            assert check("GET", "/v1/models", 503, keep="unavailable", headers=as_user(kc, BOB)).json()["code"] == "model.unavailable"
        check.kept.check()
        # not seen: what nobody planned for, and sign-in turned off for another machine
        assert check.not_seen() == {("GET", "/v1/models", 500), ("GET", "/v1/models", 403)}
