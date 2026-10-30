"""The appliance's clock, kept right by the browsers of the people signed in (Filip, 30 October 2026).

Two-step sign-in accepts a code from one 30-second step either side of the appliance's clock. Without a time
server (air-gapped, none on the office's network) that clock drifts a few seconds a day, and after weeks or
months every code is refused, the administrators' included. The office's PCs keep their time; someone signed in
is there most days.

Each browser measures the difference as NTP does (``GET /v1/clock`` a few times, the quickest round trip, the
appliance's time against the middle of it) and reports it (``POST /v1/clock``). Kept in memory, the newest per
account, for a day. When the reports agree, the gateway asks the appliance to nudge its clock (``nudge``): at
least two accounts, or one administrator; every report within two seconds of the middle one; half a second to a
minute off; at most once an hour. A larger difference only shows on Status, where an administrator may set the
clock to their PC's time (``set``), after a confirmation that shows both times.

Moving the clock is not harmless: forward, the hourly sweep deletes closed cases whose keep period has passed;
back, an old two-step code is valid again. So only people signed in report, one person alone moves nothing
unless they administer the office, a nudge is small and slow (the appliance's ``suveryn-clock`` slews it, at most
about 43 seconds a day), and anything larger is an administrator's choice. Nothing is asked while a time server
keeps the clock: the appliance refuses then, and Status says the time server keeps it.

The gateway runs as its own user and can't change the clock: it leaves a request in a folder in memory the
appliance watches (``suveryn-clock request``, suveryn-appliance ``clock/``), which deletes it, acts within its own
bounds and answers in ``result.json``. On a machine without that folder (development), nothing is asked."""

import json
import logging
import os
import secrets
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("suveryn.gateway")

REQUESTS = Path(os.environ.get("SUVERYN_CLOCK_REQUESTS", "/run/suveryn/clock-requests"))
RESULT = Path(os.environ.get("SUVERYN_CLOCK_RESULT", "/var/lib/suveryn/clock/result.json"))
MAX_RTT_MS = 1000         # a slower round trip says too little about the difference
KEPT_S = 24 * 3600        # a report counts for a day
AGREE_MS = 2000           # every report within this of the middle one
NUDGE_MIN_MS = 500        # less is not worth moving the clock for
NUDGE_MAX_MS = 60_000     # more is an administrator's choice (Status)
NUDGE_EVERY_S = 3600
WARN_MS = 10_000          # Status warns from here: codes fail from about 30 seconds
SYNCED_CACHE_S = 60


@dataclass(frozen=True)
class Report:
    offset_ms: int  # the appliance's clock minus the browser's: positive, the appliance is ahead
    rtt_ms: int
    admin: bool
    at: float


def time_server_keeps_it() -> bool | None:
    """Whether a time server keeps the clock (systemd-timesyncd); None where that can't be asked."""
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True,
                           text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    value = r.stdout.strip()
    return True if value == "yes" else False if value == "no" else None


def leave_request(body: dict) -> str | None:
    """request.json into the appliance's clock folder, whole (written beside it, then renamed); its id. None when
    there is no such folder (not an appliance) or the last request is still there."""
    if not REQUESTS.is_dir() or (REQUESTS / "request.json").exists():
        return None
    rid = secrets.token_hex(8)
    tmp = REQUESTS / f".request-{rid}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"id": rid, **body}, f)
    os.replace(tmp, REQUESTS / "request.json")
    return rid


def result_of(rid: str) -> dict | None:
    """The appliance's answer to request ``rid``, or None while it is still acting on it."""
    try:
        raw = json.loads(RESULT.read_text())
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and raw.get("id") == rid else None


class Clock:
    """The browsers' reports, and the nudges asked."""

    def __init__(self) -> None:
        self.reports: dict[str, Report] = {}
        self.last_nudge = 0.0
        # Reports arrive on the threadpool: two at once could both find the reports agreeing and both leave a
        # request (external review, pass 8). One at a time; each is quick.
        self._lock = threading.Lock()
        self._synced: tuple[float, bool | None] = (0.0, None)

    def synced(self, now: float | None = None) -> bool | None:
        now = time.time() if now is None else now
        if now - self._synced[0] > SYNCED_CACHE_S:
            self._synced = (now, time_server_keeps_it())
        return self._synced[1]

    def fresh(self, now: float) -> list[Report]:
        self.reports = {k: r for k, r in self.reports.items() if now - r.at < KEPT_S}
        return list(self.reports.values())

    def estimate_ms(self, now: float | None = None) -> int | None:
        """How far off the clock is, by the middle of the day's reports; None without any."""
        reports = self.fresh(time.time() if now is None else now)
        return round(statistics.median(r.offset_ms for r in reports)) if reports else None

    def report(self, who: str, admin: bool, offset_ms: int, rtt_ms: int, now: float | None = None) -> int | None:
        """One browser's measurement. Returns the nudge asked of the appliance, if this one made the reports agree."""
        now = time.time() if now is None else now
        if not 0 <= rtt_ms <= MAX_RTT_MS:
            return None
        with self._lock:
            return self._report(who, admin, offset_ms, rtt_ms, now)

    def _report(self, who: str, admin: bool, offset_ms: int, rtt_ms: int, now: float) -> int | None:
        self.reports[who] = Report(offset_ms, rtt_ms, admin, now)
        reports = self.fresh(now)
        if len(reports) < 2 and not any(r.admin for r in reports):
            return None  # one person alone moves nothing, unless they administer the office
        middle = round(statistics.median(r.offset_ms for r in reports))
        if any(abs(r.offset_ms - middle) > AGREE_MS for r in reports):
            return None
        if not NUDGE_MIN_MS <= abs(middle) <= NUDGE_MAX_MS or now - self.last_nudge < NUDGE_EVERY_S:
            return None
        if self.synced(now):
            return None
        if leave_request({"kind": "nudge", "offset_ms": middle}) is None:
            return None
        self.last_nudge = now
        self.reports.clear()  # the next reports measure the clock as it is being moved
        log.info("clock: asked the appliance to nudge its clock by %+.1f s (%d reports)", -middle / 1000, len(reports))
        return middle
