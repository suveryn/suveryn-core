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


STEPS = [(3_600, "5 minutes", 300), (86_400, "1 hour", 3_600), (7 * 86_400, "1 day", 86_400), (None, "1 day", 86_400)]
USERS = [("u1", "a.peeters", "An Peeters", 1.0), ("u2", "b.janssens", "Bart Janssens", 0.55),
         ("u3", "c.dubois", "Claire Dubois", 0.3), ("u4", "d.maes", None, 0.08)]


def usage(url, admin):
    """A fictional usage report (suveryn-core api: UsageReport, OfficeUsageReport) for the charts
    (suveryn-tracker#46): office hours busier, input tokens about eight times the output."""
    from datetime import datetime, timedelta, timezone
    from urllib.parse import parse_qs, urlsplit
    q = parse_qs(urlsplit(url).query)
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(q["start"][0].replace("Z", "+00:00"))
    end = datetime.fromisoformat(q["end"][0].replace("Z", "+00:00")) if "end" in q else now
    span = (end - start).total_seconds()
    step, seconds = next((n, s) for limit, n, s in STEPS if limit is None or span <= limit * 1.01)
    # Buckets on whole steps of local time, as the gateway's date_bin does (usage.py).
    local = start.astimezone()
    t = local.replace(second=0, microsecond=0) - timedelta(minutes=local.minute % 5)
    if seconds >= 3_600:
        t = t.replace(minute=0)
    if seconds >= 86_400:
        t = t.replace(hour=0)
    series, i = [], 0
    while t < end:
        busy = 1.0 if 8 <= t.astimezone().hour < 18 or seconds >= 86_400 else 0.15
        prompt = int((9_000 + (i * 7_919) % 23_000) * busy * seconds / 3_600) if seconds < 86_400 else 150_000 + (i * 37_013) % 260_000
        if i % 9 == 4:
            prompt = 0
        completion = prompt // 8
        series.append({"start": t.isoformat(), "requests": -(-prompt // 4_000), "prompt_tokens": prompt,
                       "completion_tokens": completion, "total_tokens": prompt + completion})
        t, i = t + timedelta(seconds=seconds), i + 1
    total = {k: sum(b[k] for b in series) for k in ("requests", "prompt_tokens", "completion_tokens", "total_tokens")}
    report = {"start": start.isoformat(), "end": end.isoformat(), "step": step, "totals": total, "series": series,
              "by_kind": {"chat": total, "summary": {k: v // 5 for k, v in total.items()}}}
    if not admin:
        return report
    weight = sum(u[3] for u in USERS)
    per_user = [{"user_id": uid, "username": name, "name": full,
                 "totals": {k: int(v * w / weight) for k, v in total.items()}, "cost": None} for uid, name, full, w in USERS]
    return {**report, "per_user": per_user, "cost": "12.34",
            "rates": {"input_per_million": "3.0000", "output_per_million": "15.0000", "currency": "EUR"}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DIST), **k)

    def end_headers(self):
        for k, v in HEADERS:
            self.send_header(k, v)
        super().end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in API or path in ("/v1/usage", "/v1/admin/usage"):
            body = json.dumps(API[path] if path in API else usage(self.path, admin=path.startswith("/v1/admin"))).encode()
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
