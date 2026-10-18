"""Sign-in: the OIDC login flow, token validation and the API gate, against a fake Keycloak.

The fake signs real RS256 tokens with a generated key and checks PKCE like Keycloak does, so the
gateway's validation runs exactly as in production. A live test against a real Keycloak is
described in ``keycloak/README.md``.
"""

import asyncio
import base64
import hashlib
import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import (
    LOGIN_COOKIE,
    Authenticator,
    AuthError,
    AuthSettings,
    OIDCProvider,
    safe_return_path,
)
from suveryn_api_gateway.main import check_auth_settings, check_one_process
from suveryn_api_gateway.ratelimit import RateLimits
from suveryn_engine import LlamaServerClient, LLMSettings

ISSUER = "http://keycloak.test/realms/suveryn"
PUBLIC = "http://testserver"
SETTINGS = AuthSettings(issuer=ISSUER, client_id="suveryn-chat", client_secret="s3cret", public_url=PUBLIC)
REALM = Path(__file__).parents[1] / "keycloak" / "suveryn-realm.json"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakeKeycloak:
    """Discovery, JWKS, and a token endpoint that checks client secret and PKCE."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict] = {}   # code -> {nonce, challenge}
        self.expires_in = 300
        self.refresh_allowed = True
        self.token_calls: list[dict] = []

    def sign(self, claims: dict, key=None, alg="RS256", kid="k1") -> str:
        return jwt.encode(claims, key or self.key, algorithm=alg, headers={"kid": kid})

    def tokens(self, nonce: str | None = None, over: dict | None = None, access_over: dict | None = None) -> dict:
        over = over or {}
        now = int(time.time())
        base = {"iss": ISSUER, "sub": "user-1", "iat": now, "exp": now + self.expires_in,
                "preferred_username": "notaris.test", "name": "Test Notaris"}
        id_token = self.sign({**base, "aud": "suveryn-chat", "azp": "suveryn-chat", "typ": "ID", "nonce": nonce, **over})
        access = self.sign({**base, "aud": "account", "azp": "suveryn-chat", "typ": "Bearer", **over, **(access_over or {})})
        return {"id_token": id_token, "access_token": access, "refresh_token": f"r-{uuid.uuid4().hex}",
                "expires_in": self.expires_in, "refresh_expires_in": 1800, "token_type": "Bearer"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            base = f"{ISSUER}/protocol/openid-connect"
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": f"{base}/auth",
                                             "token_endpoint": f"{base}/token", "jwks_uri": f"{base}/certs",
                                             "end_session_endpoint": f"{base}/logout"})
        if path.endswith("/certs"):
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            keys = getattr(self, "keys_override", None) or [{**jwk, "kid": "k1", "alg": "RS256", "use": "sig"}]
            return httpx.Response(200, json={"keys": keys})
        if path.endswith("/token"):
            expected = "Basic " + base64.b64encode(b"suveryn-chat:s3cret").decode()
            if request.headers.get("authorization") != expected:
                return httpx.Response(401, json={"error": "unauthorized_client"})
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_calls.append(form)
            if form["grant_type"] == "authorization_code":
                issued = self.codes.pop(form.get("code"), None)
                if issued is None or b64(hashlib.sha256(form["code_verifier"].encode()).digest()) != issued["challenge"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self.tokens(issued["nonce"], issued.get("over"), issued.get("access_over")))
            if form["grant_type"] == "refresh_token":
                if not self.refresh_allowed:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self.tokens())
        return httpx.Response(404)


class FakeDocuments:
    state, error = "ready", None

    def documents(self, scope):
        return []

    def pending_jobs(self, owner, scope=None):
        return []

    def stop(self):
        pass


def llm_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B-UD-Q4_K_M.gguf"}]})
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": "Een akte."}, "finish_reason": "stop"}]})


@pytest.fixture
def kc():
    return FakeKeycloak()


@pytest.fixture
def client(kc):
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(llm_transport))
    with TestClient(create_app(llm, documents=FakeDocuments(), load_documents=False, auth=auth)) as c:
        yield c


def sign_in(c: TestClient, kc: FakeKeycloak, return_to: str = "/", **token_overrides) -> httpx.Response:
    """Run the browser's side of the login; return the callback response."""
    r = c.get("/auth/login", params={"return_to": return_to}, follow_redirects=False)
    assert r.status_code == 303
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    code = uuid.uuid4().hex
    kc.codes[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "over": token_overrides}
    return c.get("/auth/callback", params={"code": code, "state": q["state"]}, follow_redirects=False)


CHAT = {"messages": [{"role": "user", "content": "Vraag"}]}


def test_api_needs_sign_in_and_health_stays_public(client):
    assert client.get("/v1/documents").status_code == 401
    assert client.post("/v1/chat", json=CHAT).status_code == 401
    health = client.get("/health").json()
    assert health["auth"] == {"status": "ready", "detail": None}
    assert client.get("/auth/me").status_code == 401


def test_login_redirects_to_keycloak_with_pkce_state_and_nonce(client):
    r = client.get("/auth/login", follow_redirects=False)
    url = urlsplit(r.headers["location"])
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/protocol/openid-connect/auth"
    assert q["response_type"] == ["code"] and q["client_id"] == ["suveryn-chat"]
    assert q["code_challenge_method"] == ["S256"] and len(q["code_challenge"][0]) == 43
    assert q["redirect_uri"] == [f"{PUBLIC}/auth/callback"] and q["scope"] == ["openid profile"]
    assert q["state"][0] and q["nonce"][0] and q["state"] != q["nonce"]
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{LOGIN_COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_dev_realm_client_has_a_base_url_for_back_to_application():
    """Keycloak's error pages ("cookie not found", expired links) only show "Back to application"
    when the client has a base URL; without it the user is stuck on the error page."""
    [chat, _directory] = json.loads(REALM.read_text())["clients"]
    assert chat["baseUrl"] == "http://localhost:5173/" == chat["attributes"]["post.logout.redirect.uris"]


def test_login_page_language_follows_the_ui(client):
    """suveryn-tracker#8: the chat UI's language is passed to Keycloak as ui_locales; nothing else is."""
    def ui_locales(query):
        r = client.get(f"/auth/login{query}", follow_redirects=False)
        return parse_qs(urlsplit(r.headers["location"]).query).get("ui_locales")
    assert ui_locales("?lang=nl") == ["nl"] and ui_locales("?lang=fr") == ["fr"]
    assert ui_locales("") is None and ui_locales("?lang=de") is None
    assert ui_locales("?lang=nl%26prompt%3Dnone") is None  # no parameter injection


def test_full_sign_in_gives_an_httponly_session_and_opens_the_api(client, kc):
    r = sign_in(client, kc, return_to="/?x=1")
    assert r.status_code == 303 and r.headers["location"] == "/?x=1"
    session_cookie = [c for c in r.headers.get_list("set-cookie") if c.startswith("suveryn_session=")][0]
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert kc.token_calls[0]["code_verifier"]  # PKCE verifier sent, and checked by the fake
    assert client.get("/v1/documents").status_code == 200
    assert client.get("/auth/me").json() == {"username": "notaris.test", "name": "Test Notaris", "sub": "user-1", "admin": False, "office_wide": False, "cases_keep": "manual", "avatar": None}
    assert "token" not in client.get("/auth/me").text  # no token ever reaches the browser


def test_open_redirect_after_login_is_refused(client, kc):
    assert sign_in(client, kc, return_to="//evil.example/").headers["location"] == "/"
    assert safe_return_path("https://evil.example") == "/" and safe_return_path("/\\evil") == "/"


def test_callback_without_the_login_cookie_is_refused(client, kc):
    r = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    client.cookies.clear()  # e.g. a link to a callback crafted by someone else (login CSRF)
    assert client.get("/auth/callback", params={"code": "x", "state": state}).status_code == 400


def test_state_can_be_used_only_once(client, kc):
    r = client.get("/auth/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    kc.codes["c1"] = {"nonce": q["nonce"], "challenge": q["code_challenge"]}
    assert client.get("/auth/callback", params={"code": "c1", "state": q["state"]}, follow_redirects=False).status_code == 303
    assert client.get("/auth/callback", params={"code": "c1", "state": q["state"]}).status_code == 400


@pytest.mark.parametrize("override", [{"nonce": "other"}, {"aud": "another-client"}, {"iss": "http://evil/realms/x"},
                                      {"exp": int(time.time()) - 3600}])
def test_bad_id_token_is_refused(client, kc, override):
    assert sign_in(client, kc, **override).status_code == 400
    assert client.get("/v1/documents").status_code == 401


def bearer(c: TestClient, token: str) -> int:
    return c.get("/v1/documents", headers={"Authorization": f"Bearer {token}"}).status_code


def test_bearer_access_token_works_for_api_clients(client, kc):
    assert bearer(client, kc.tokens()["access_token"]) == 200


def test_forged_and_wrong_tokens_are_refused(client, kc):
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "u", "iat": now, "exp": now + 300, "azp": "suveryn-chat", "typ": "Bearer"}
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert bearer(client, kc.sign(claims, key=other_key)) == 401                     # wrong signature
    assert bearer(client, jwt.encode(claims, "s3cret", algorithm="HS256", headers={"kid": "k1"})) == 401  # HMAC
    unsigned = b64(json.dumps({"alg": "none", "kid": "k1"}).encode()) + "." + b64(json.dumps(claims).encode()) + "."
    assert bearer(client, unsigned) == 401                                            # alg none
    assert bearer(client, kc.sign({**claims, "azp": "other-client"})) == 401          # another client's token
    assert bearer(client, kc.sign({**claims, "iss": "http://evil/realms/suveryn"})) == 401
    assert bearer(client, kc.sign({**claims, "exp": now - 3600})) == 401              # expired
    assert bearer(client, kc.sign(claims, kid="unknown")) == 401
    assert bearer(client, "not-a-token") == 401


def test_changes_need_the_uis_own_origin(client, kc):
    sign_in(client, kc)
    assert client.post("/v1/chat", json=CHAT, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/v1/chat", json=CHAT).status_code == 403  # no Origin header with a cookie
    assert client.post("/v1/chat", json=CHAT, headers={"Origin": PUBLIC}).status_code == 200
    assert client.get("/v1/documents", headers={"Origin": "http://evil.example"}).status_code == 200  # reads: SameSite


def test_tokens_are_refreshed_and_revocation_signs_out(client, kc):
    kc.expires_in = 10  # within the refresh margin: every request refreshes
    sign_in(client, kc)
    assert client.get("/v1/documents").status_code == 200
    assert kc.token_calls[-1]["grant_type"] == "refresh_token"
    kc.refresh_allowed = False  # an admin disabled the user or ended the session in Keycloak
    assert client.get("/v1/documents").status_code == 401
    kc.refresh_allowed = True
    assert client.get("/v1/documents").status_code == 401  # the session is gone for good


def test_logout_ends_the_session_and_returns_keycloaks_logout_url(client, kc):
    sign_in(client, kc)
    r = client.post("/auth/logout", headers={"Origin": PUBLIC})
    url = urlsplit(r.json()["logout_url"])
    q = parse_qs(url.query)
    assert url.path.endswith("/protocol/openid-connect/logout")
    assert q["post_logout_redirect_uri"] == [f"{PUBLIC}/"] and q["id_token_hint"][0]
    assert client.get("/v1/documents").status_code == 401


def test_without_configuration_the_api_is_closed():
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(llm_transport))
    app = create_app(llm, documents=FakeDocuments(), load_documents=False, auth=Authenticator(AuthSettings()))
    with TestClient(app) as c:
        assert c.get("/v1/documents").status_code == 401
        assert c.get("/auth/login").status_code == 503
        assert c.get("/health").json()["auth"]["status"] == "not_configured"


def test_sign_in_can_be_off_only_on_loopback(monkeypatch):
    monkeypatch.setenv("SUVERYN_AUTH", "off")
    check_auth_settings("127.0.0.1")
    with pytest.raises(SystemExit):
        check_auth_settings("0.0.0.0")


def test_the_gateway_refuses_to_start_as_several_workers(monkeypatch):
    """Sessions and rate limits are in memory: two workers would each know half (review finding)."""
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    check_one_process()
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    check_one_process()
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(SystemExit):
        check_one_process()


def test_dev_realm_allows_only_local_accounts_and_the_safe_flow():
    realm = json.loads(REALM.read_text())
    assert realm["displayName"] == "sūveryn"  # used mid-sentence ("Sign in to sūveryn"): lower case
    assert realm["identityProviders"] == [] and realm["identityProviderMappers"] == []  # no social/online IdPs
    assert realm["registrationAllowed"] is False and realm["bruteForceProtected"] is True
    assert realm["otpPolicyType"] == "totp" and "requiredActions" not in realm  # TOTP available, not forced
    assert "components" not in realm  # no LDAP hard-coded
    [chat, directory] = realm["clients"]
    assert chat["publicClient"] is False and "secret" not in chat
    assert chat["standardFlowEnabled"] and not chat["implicitFlowEnabled"] and not chat["directAccessGrantsEnabled"]
    assert not chat["serviceAccountsEnabled"] and chat["attributes"]["pkce.code.challenge.method"] == "S256"
    # suveryn-tracker#10: the directory client reads the office's accounts and nothing else: a service
    # account with view-users and view-realm only (read-only), no sign-in flow of its own, and no secret in the file. The only
    # account in the realm file is that service account: no human accounts hard-coded.
    assert directory["clientId"] == "suveryn-directory" and "secret" not in directory
    assert directory["serviceAccountsEnabled"] and not directory["standardFlowEnabled"]
    assert not directory["implicitFlowEnabled"] and not directory["directAccessGrantsEnabled"] and not directory["publicClient"]
    assert directory["redirectUris"] == []
    [service_account] = realm["users"]
    assert service_account["serviceAccountClientId"] == "suveryn-directory"
    assert service_account["clientRoles"] == {"realm-management": ["view-users", "view-realm"]}  # both read-only (avatars.md)
    # suveryn-tracker#7: the administrator role exists, nobody has it by default, and it reaches the
    # chat client's access token (the client has fullScopeAllowed false, so it must be mapped).
    from suveryn_api_gateway.app import ADMIN_ROLE
    assert [r["name"] for r in realm["roles"]["realm"]] == [ADMIN_ROLE]
    assert chat["fullScopeAllowed"] is False
    assert realm["scopeMappings"] == [{"client": "suveryn-chat", "roles": [ADMIN_ROLE]}]


def test_a_flood_of_unfinished_sign_ins_never_blocks_a_real_one(kc):
    """suveryn-tracker#14: unfinished sign-ins were kept in the gateway's memory (at most 1000), so a
    flood of /auth/login could refuse, and later evict, a real user's. Now the server keeps nothing:
    the sign-in travels in its own browser's encrypted cookie."""
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(llm_transport))
    app = create_app(llm, documents=FakeDocuments(), load_documents=False, auth=auth, rate_limits=RateLimits(sign_in=0))
    with TestClient(app) as user, TestClient(app) as flood:
        r = user.get("/auth/login", follow_redirects=False)  # a real user is on the Keycloak page...
        q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
        for _ in range(2000):  # ...while someone else floods the sign-in
            assert flood.get("/auth/login", follow_redirects=False).status_code == 303
        kc.codes["real"] = {"nonce": q["nonce"], "challenge": q["code_challenge"]}
        assert user.get("/auth/callback", params={"code": "real", "state": q["state"]}, follow_redirects=False).status_code == 303
        assert user.get("/v1/documents").status_code == 200
    assert not hasattr(auth, "_pending")


def test_the_login_cookie_is_encrypted_and_cant_be_altered(client, kc):
    r = client.get("/auth/login", params={"return_to": "/private-path"}, follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    cookie = client.cookies[LOGIN_COOKIE]
    assert q["nonce"] not in cookie and "private-path" not in cookie  # not readable, not even base64
    raw = bytearray(base64.urlsafe_b64decode(cookie + "=" * (-len(cookie) % 4)))
    raw[20] ^= 1  # one bit changed
    client.cookies.set(LOGIN_COOKIE, base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode())
    kc.codes["c"] = {"nonce": q["nonce"], "challenge": q["code_challenge"]}
    assert client.get("/auth/callback", params={"code": "c", "state": q["state"]}).status_code == 400
    assert kc.token_calls == []  # refused before the code was even exchanged


def test_a_login_cookie_from_another_server_or_too_old_is_refused(monkeypatch):
    from suveryn_api_gateway.auth import LoginSealer, PendingLogin

    login = PendingLogin("st", "verifier", "nonce", "/", time.time())
    assert LoginSealer("s3cret").open(LoginSealer("s3cret").seal(login)) == login
    assert LoginSealer("another-secret").open(LoginSealer("s3cret").seal(login)) is None  # key rotated
    for junk in (None, "", "x", "!!!", "a" * 5000):
        assert LoginSealer("s3cret").open(junk) is None

    import asyncio

    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(FakeKeycloak().handler)))
    _, cookie = asyncio.run(auth.start_login("/"))
    state = LoginSealer("s3cret").open(cookie).state
    monkeypatch.setattr(time, "time", lambda real=time.time: real() + 11 * 60)
    with pytest.raises(AuthError, match="expired"):
        asyncio.run(auth.finish_login("code", state, cookie))


def test_sign_in_is_rate_limited_per_client_address(kc):
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(llm_transport))
    app = create_app(llm, documents=FakeDocuments(), load_documents=False, auth=auth, rate_limits=RateLimits(sign_in=3))
    with TestClient(app, client=("10.0.0.9", 1)) as flood, TestClient(app, client=("10.0.0.7", 1)) as other:
        assert [flood.get("/auth/login", follow_redirects=False).status_code for _ in range(4)] == [303, 303, 303, 429]
        r = flood.get("/auth/callback", params={"code": "x", "state": "y"})
        assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= 60
        assert other.get("/auth/login", follow_redirects=False).status_code == 303  # someone else isn't affected
        assert flood.get("/health").status_code in (200, 503)  # only sign-in is limited


def test_questions_and_uploads_are_rate_limited_per_user(kc):
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(llm_transport))
    class Uploads(FakeDocuments):
        def accept_upload(self, src, filename, owner, case_id=None):
            return SimpleNamespace(id="job", public=lambda: {"id": "job"})

    app = create_app(llm, documents=Uploads(), load_documents=False, auth=auth,
                     rate_limits=RateLimits(chat=2, uploads=1))
    alice = {"Authorization": f"Bearer {kc.tokens(over={'sub': 'alice'})['access_token']}"}
    bob = {"Authorization": f"Bearer {kc.tokens(over={'sub': 'bob'})['access_token']}"}
    with TestClient(app) as c:
        assert [c.post("/v1/chat", json=CHAT, headers=alice).status_code for _ in range(3)] == [200, 200, 429]
        assert c.post("/v1/chat", json=CHAT, headers=bob).status_code == 200  # per user
        assert c.get("/v1/documents", headers=alice).status_code == 200  # reading isn't limited
        assert c.post("/v1/chat", json=CHAT).status_code == 401  # not signed in: 401, not counted
        pdf = {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}
        assert [c.post("/v1/documents", files=pdf, headers=alice).status_code for _ in range(2)] == [202, 429]


def test_rate_limiter_window_and_memory_bound():
    from suveryn_api_gateway.ratelimit import RateLimiter

    lim = RateLimiter(2, window_s=60, max_keys=3)
    assert [lim.hit("a", now=t) for t in (0, 1, 2)] == [None, None, 58]
    assert lim.hit("a", now=60.5) is None  # the first one left the window
    for i in range(10):
        lim.hit(f"k{i}", now=100)
    assert len(lim._events) <= 3
    assert RateLimiter(0).hit("x") is None  # 0 = no limit


def test_sessions_do_not_keep_the_access_token():
    """Only its expiry is needed after verification; holding it would just be one more secret in memory."""
    from suveryn_api_gateway.auth import Session

    assert "access_token" not in Session.__dataclass_fields__


@pytest.mark.parametrize("host, status", [("127.0.0.1", 200), ("::1", 200), ("10.0.0.5", 403), ("192.168.1.20", 403)])
def test_sign_in_off_serves_only_this_machine(host, status):
    """SUVERYN_AUTH=off is refused on a network address by main.py, but bare uvicorn skips that check:
    the app itself now refuses clients that aren't on this machine."""
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(llm_transport))
    with TestClient(create_app(llm, documents=FakeDocuments(), load_documents=False, auth=Authenticator.disabled()),
                    client=(host, 50000)) as c:
        assert c.get("/v1/documents").status_code == status
        assert c.get("/health").status_code in (200, 503)  # public endpoints stay public


def test_access_log_never_contains_the_sign_in_code():
    """Code review 2026-10: uvicorn logged /auth/callback?code=...&state=... in full."""
    import logging

    from suveryn_api_gateway.app import StripQueryString

    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', (
        "127.0.0.1:5000", "GET", "/auth/callback?state=abc&code=SECRET-CODE", "1.1", 303), None)
    assert StripQueryString().filter(record)
    assert "SECRET-CODE" not in record.getMessage() and "/auth/callback" in record.getMessage()
    assert any(isinstance(f, StripQueryString) for f in logging.getLogger("uvicorn.access").filters)


def test_the_session_cap_holds_even_while_every_session_is_valid(monkeypatch):
    """Review finding: pruning only the expired sessions let the map grow past MAX_SESSIONS as long
    as every session was still valid. Now the least recently seen go."""
    import suveryn_api_gateway.auth as auth_module
    from suveryn_api_gateway.auth import User

    monkeypatch.setattr(auth_module, "MAX_SESSIONS", 3)
    a = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(FakeKeycloak().handler)))
    tokens = {"id_token": "", "expires_in": 300, "refresh_token": "r", "refresh_expires_in": 1800}
    first = a._new_session(User(sub="u1", username="u1", name="U1"), tokens)
    later = [a._new_session(User(sub=f"u{i}", username=f"u{i}", name=f"U{i}"), tokens) for i in (2, 3)]
    assert len(a._sessions) == 3
    asyncio.run(a.session_user(first.id))  # seen again: it isn't the one to go
    fourth = a._new_session(User(sub="u4", username="u4", name="U4"), tokens)
    assert len(a._sessions) == 3 and first.id in a._sessions and fourth.id in a._sessions
    assert later[0].id not in a._sessions  # the least recently seen went


def test_a_jwks_key_without_a_kid_is_ignored(client, kc):
    """A key with no kid can't be matched by one, and must not sit under None, where a token
    without a kid header would find it."""
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "u", "iat": now, "exp": now + 300, "azp": "suveryn-chat", "typ": "Bearer"}
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(kc.key.public_key()))
    kc.keys_override = [{**jwk, "alg": "RS256", "use": "sig"}]  # no kid at all
    no_kid = jwt.encode(claims, kc.key, algorithm="RS256")        # no kid header either
    assert bearer(client, no_kid) == 401
