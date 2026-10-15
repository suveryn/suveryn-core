"""Serves a chat-ui build the way the appliance's nginx does: the real CSP and security headers from
suveryn-appliance/reverse-proxy, plus stand-ins for the few API calls the pages make on load.

    python3 serve.py <chat-ui dist> <port> <suveryn-appliance/reverse-proxy>
"""
import json
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
PROXY = Path(sys.argv[3])
HEADERS = re.findall(r'add_header\s+([\w-]+)\s+"([^"]*)"', (PROXY / "suveryn-headers.conf").read_text()
                     + (PROXY / "suveryn-csp.conf").read_text())
HEADERS = [(k, v) for k, v in HEADERS if k != "Strict-Transport-Security"]  # plain http here

STATE = {"name": "notary-brussels-01", "address": "192.168.1.50/24", "dhcp": True, "gateway": "192.168.1.1",
         "dns": "192.168.1.1", "language": None}
API = {
    "/setup/v1/state": STATE,
    "/auth/me": {"username": "filip", "name": "Filip Tack", "admin": True},
    "/health": {"status": "ok", "backend": {"reachable": True, "status": "ok", "model": "qwen3.8-27b"},
                "documents": {"status": "ready", "detail": None}, "auth": {"status": "ready", "detail": None},
                "history": {"status": "ready", "detail": None}},
    "/v1/models": [{"id": "qwen3.8-27b-q4_k_m", "loaded": True, "default": True},
                   {"id": "mistral-small-3.2-24b-q4_k_m", "loaded": False, "default": False},
                   {"id": "deepseek-r1-distill-32b", "loaded": False, "default": False}],
    "/v1/documents": {"documents": [], "jobs": []},
    "/v1/conversations": [],
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DIST), **k)

    def end_headers(self):
        for k, v in HEADERS:
            self.send_header(k, v)
        super().end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in API or path.startswith("/v1/usage"):
            body = json.dumps(API.get(path, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                                             "by_kind": [], "days": []})).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"serving {DIST} on :{PORT} with {len(HEADERS)} headers", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
