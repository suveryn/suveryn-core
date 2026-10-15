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
    # One fictional deed and one conversation citing it, for the sidebar and its dialogs.
    "/v1/documents": {"documents": [{"id": "d1", "filename": "akte-voorbeeld.pdf", "pages": 8, "ocr_pages": 0,
                                     "status": "ok", "warnings": []}], "jobs": []},
    "/v1/conversations": [{"id": "c1", "title": "Wie zijn de verkopers?", "created_at": "2026-10-15T09:00:00Z",
                           "updated_at": "2026-10-15T09:05:00Z"}],
    "/v1/documents/d1/conversations": [{"id": "c1", "title": "Wie zijn de verkopers?", "created_at": "2026-10-15T09:00:00Z",
                                        "updated_at": "2026-10-15T09:05:00Z"}],
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
    per_user = []
    for uid, name, full, w in USERS:
        totals = {k: int(v * w / weight) for k, v in total.items()}
        per_user.append({"user_id": uid, "username": name, "name": full, "totals": totals, "cost": cost(totals)})
    return {**report, "per_user": per_user, "cost": cost(total), "rates": RATES}


RATES = {"input_per_million": "3.0000", "output_per_million": "15.0000", "currency": "USD", "updated_at": None, "updated_by": None}


def cost(t):
    """As the gateway's usage.cost: per million input and output tokens, to the cent."""
    from decimal import Decimal
    raw = (Decimal(t["prompt_tokens"]) * Decimal(RATES["input_per_million"])
           + Decimal(t["completion_tokens"]) * Decimal(RATES["output_per_million"])) / 1_000_000
    return str(raw.quantize(Decimal("0.01")))


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

    def do_POST(self):
        """A fixed, fictional answer with one source for /v1/chat (the gateway streams Server-Sent Events)."""
        if self.path.split("?")[0] != "/v1/chat":
            self.send_error(404)
            return
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        answer = "De verkopers zijn Jan Peeters en Marie Claes [1]."
        done = {"id": "a1", "model": "qwen3.8-27b-q4_k_m", "answer": answer, "calculations": [], "finish_reason": "stop",
                "citations": [{"text": "Verkopers: de heer Jan Peeters en mevrouw Marie Claes, wonende te Gent.",
                               "source": {"document_id": "d1", "page": 2, "location": None}}]}
        events = [("delta", {"text": answer}), ("done", done)]
        body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        """The administrator's rates, kept in memory (the gateway: PUT /v1/admin/usage/rates)."""
        if self.path.split("?")[0] != "/v1/admin/usage/rates":
            self.send_error(404)
            return
        from datetime import datetime, timezone
        new = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        RATES.update({k: str(new[k]) for k in ("input_per_million", "output_per_million", "currency") if k in new},
                     updated_at=datetime.now(timezone.utc).isoformat(), updated_by="filip")
        body = json.dumps(RATES).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"serving {DIST} on :{PORT} with {len(HEADERS)} headers", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
