"""Rate limits: sign-in per client address, questions and uploads per user (suveryn-tracker#14).

Before the 2026-10 code review nothing limited how often anyone could call the gateway. The limits
are generous for people (a notary doesn't ask 20 questions a minute) and stop scripts and floods:

======================  ==============================  ======================  ===============
What                    Counted per                     Default (per minute)    Variable
======================  ==============================  ======================  ===============
``/auth/...``           client address                  30                      SUVERYN_RATE_SIGN_IN
``POST /v1/chat``       signed-in user                  20                      SUVERYN_RATE_CHAT
``POST /v1/documents``  signed-in user                  30                      SUVERYN_RATE_UPLOADS
======================  ==============================  ======================  ===============

``0`` turns a limit off. Behind the appliance's reverse proxy on the same machine, uvicorn takes the
client address from ``X-Forwarded-For`` (it trusts proxy headers from 127.0.0.1 only); behind a
proxy elsewhere every request seems to come from the proxy, so the sign-in limit then counts for
the whole office together and should be raised or left to the proxy.

Counts live in this process's memory (a sliding window per key), bounded to ``MAX_KEYS`` keys.
"""

import math
import os
import time
from collections import deque
from dataclasses import dataclass

WINDOW_S = 60.0
MAX_KEYS = 10_000


class RateLimiter:
    """At most ``limit`` events per ``window_s`` per key (sliding window). ``limit=0``: no limit."""

    def __init__(self, limit: int, window_s: float = WINDOW_S, max_keys: int = MAX_KEYS):
        self.limit, self.window_s, self.max_keys = limit, window_s, max_keys
        self._events: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float | None = None) -> int | None:
        """Count one event for ``key``: None if allowed, else the seconds to wait before trying again."""
        if self.limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        events = self._events.get(key)
        if events is None:
            if len(self._events) >= self.max_keys:
                self._forget_idle(now)
            events = self._events[key] = deque()
        while events and events[0] <= now - self.window_s:
            events.popleft()
        if len(events) >= self.limit:
            return max(1, math.ceil(events[0] + self.window_s - now))
        events.append(now)
        return None

    def _forget_idle(self, now: float) -> None:
        """Make room: drop keys with no recent events, then (still full) the oldest keys."""
        for key in [k for k, ev in self._events.items() if not ev or ev[-1] <= now - self.window_s]:
            del self._events[key]
        while len(self._events) >= self.max_keys:
            del self._events[next(iter(self._events))]


@dataclass(frozen=True)
class RateLimits:
    sign_in: int = 30
    chat: int = 20
    uploads: int = 30

    @classmethod
    def from_env(cls) -> "RateLimits":
        d = cls()
        return cls(sign_in=int(os.environ.get("SUVERYN_RATE_SIGN_IN", d.sign_in)),
                   chat=int(os.environ.get("SUVERYN_RATE_CHAT", d.chat)),
                   uploads=int(os.environ.get("SUVERYN_RATE_UPLOADS", d.uploads)))
