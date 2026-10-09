"""Sign in through a running gateway and Keycloak the way a browser does, and check the API gate.

Development check, not a unit test: it needs a running Keycloak with the ``suveryn`` realm and a
gateway configured for it (see README.md in this folder). Credentials come from environment
variables and are never printed.

    SUVERYN_CHECK_USER=notaris.test SUVERYN_CHECK_PASSWORD=... \\
      uv run python packages/api-gateway/keycloak/live_login_check.py [--gateway http://127.0.0.1:8000]

If the user has the "Configure OTP" required action, the check also enrols a TOTP authenticator
(computing the codes itself, like an authenticator app) and signs in again with a code; pass
``--totp-secret-file`` to keep the enrolled secret for later runs.

What it checks:
1. without a session, ``/v1/documents`` answers 401;
2. ``/auth/login`` redirects to Keycloak with PKCE (S256), and the Keycloak login form works;
3. the callback creates a session and ``/v1/documents`` answers 200; ``/auth/me`` names the user;
4. a POST from another origin is refused (403) and one from the UI's origin is accepted;
5. logout ends the session (401 again) and returns Keycloak's end-session URL.
"""

import argparse
import hashlib
import hmac
import html
import os
import re
import struct
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx


def totp(secret: bytes, at: float | None = None, digits: int = 6, period: int = 30) -> str:
    """RFC 6238 TOTP with HMAC-SHA1, as Keycloak's default OTP policy and authenticator apps use."""
    counter = struct.pack(">Q", int((at or time.time()) // period))
    mac = hmac.new(secret, counter, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 10**digits
    return str(code).zfill(digits)


def form(page: str, form_id: str | None = None) -> tuple[str, dict]:
    """(action URL, hidden inputs) of a Keycloak page's form."""
    m = re.search(rf'<form[^>]*id="{form_id}"[^>]*>' if form_id else r"<form[^>]*>", page)
    if not m:
        raise SystemExit(f"FAIL: no form {form_id or ''} on the Keycloak page")
    action = html.unescape(re.search(r'action="([^"]+)"', m.group(0)).group(1))
    hidden = {}
    for tag in re.findall(r"<input[^>]*>", page):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag))
        if attrs.get("type") == "hidden" and "name" in attrs:
            hidden[html.unescape(attrs["name"])] = html.unescape(attrs.get("value", ""))
    return action, hidden


class Browser:
    """Keycloak's side of a browser: keeps its cookies.

    Keycloak marks its cookies ``Secure``. Browsers treat ``http://localhost`` as a secure context
    and send them; httpx doesn't, so the cookies are carried here explicitly.
    """

    def __init__(self):
        self.http = httpx.Client(timeout=30, follow_redirects=False)
        self.cookies: dict[str, str] = {}

    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())} if self.cookies else {}
        r = self.http.request(method, url, headers=headers, **kw)
        self.cookies.update(r.cookies)
        return r

    def get(self, url: str) -> httpx.Response:
        return self._send("GET", url)

    def post(self, url: str, data: dict) -> httpx.Response:
        return self._send("POST", url, data=data)


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Live sign-in check against Keycloak and the gateway.")
    ap.add_argument("--gateway", default="http://127.0.0.1:8000")
    ap.add_argument("--origin", default=os.environ.get("SUVERYN_PUBLIC_URL", "http://localhost:5173"))
    ap.add_argument("--totp-secret-file", type=Path)
    a = ap.parse_args()
    user, password = os.environ["SUVERYN_CHECK_USER"], os.environ["SUVERYN_CHECK_PASSWORD"]
    gw = httpx.Client(base_url=a.gateway, timeout=30)   # the browser's view of the gateway
    kc = Browser()  # the browser's view of Keycloak

    check(gw.get("/v1/documents").status_code == 401, "API refuses requests without a session (401)")

    r = gw.get("/auth/login")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    check(r.status_code == 303 and q.get("code_challenge_method") == ["S256"], "login redirects to Keycloak with PKCE S256")

    page = kc.get(r.headers["location"])
    action, _ = form(page.text, "kc-form-login")
    r = kc.post(action, data={"username": user, "password": password, "credentialId": ""})
    while r.status_code == 302 and "/login-actions/" in r.headers.get("location", ""):
        r = kc.get(r.headers["location"])  # a Keycloak step such as a required action
    secret = a.totp_secret_file.read_bytes().strip() if a.totp_secret_file and a.totp_secret_file.exists() else None
    if r.status_code == 200 and 'name="totpSecret"' in r.text:  # Keycloak asks to set up an authenticator
        action, hidden = form(r.text, "kc-totp-settings-form")
        secret = hidden["totpSecret"].encode()
        r = kc.post(action, data={**hidden, "totp": totp(secret), "userLabel": "live check"})
        check(r.status_code == 302 and "/auth/callback" in r.headers.get("location", ""),
              "TOTP authenticator enrolled with a computed code")
        if a.totp_secret_file:
            a.totp_secret_file.write_bytes(secret)
            a.totp_secret_file.chmod(0o600)
    elif r.status_code == 200 and 'name="otp"' in r.text:  # Keycloak asks for the one-time code
        check(secret is not None, "TOTP secret available for a user with TOTP (--totp-secret-file)")
        action, _ = form(r.text, "kc-otp-login-form")
        r = kc.post(action, data={"otp": totp(secret)})
        check(r.status_code == 302, "signed in with password and TOTP code")
    check(r.status_code == 302 and "/auth/callback" in r.headers.get("location", ""),
          "Keycloak accepted the credentials and redirects to the gateway callback")

    callback = urlsplit(r.headers["location"])  # http://localhost:5173/auth/callback?...: same gateway behind Vite
    r = gw.get(f"/auth/callback?{callback.query}")
    check(r.status_code == 303, "callback exchanged the code and created a session")
    check(gw.get("/v1/documents").status_code == 200, "API answers with a session (200)")
    me = gw.get("/auth/me").json()
    check(me.get("username") == user, "/auth/me names the signed-in user")

    chat = {"messages": [{"role": "user", "content": "Zeg alleen: ok"}], "max_tokens": 5}
    check(gw.post("/v1/chat", json=chat, headers={"Origin": "http://evil.example"}).status_code == 403,
          "POST from another origin refused (403)")
    check(gw.post("/v1/chat", json=chat, headers={"Origin": a.origin}).status_code == 200,
          "POST from the UI's origin accepted (200)")

    r = gw.post("/auth/logout", headers={"Origin": a.origin})
    check("/protocol/openid-connect/logout" in (r.json().get("logout_url") or ""), "logout returns Keycloak's end-session URL")
    check(gw.get("/v1/documents").status_code == 401, "API refuses requests after logout (401)")

    if secret is not None and a.totp_secret_file is None:
        print("note: TOTP was enrolled for this user; without --totp-secret-file the secret is not kept")


if __name__ == "__main__":
    main()
