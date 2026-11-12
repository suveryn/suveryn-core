"""Messages are codes (the handbook's decision of 12 November 2026; docs/design/messages.md).

Everything the server says about what went wrong, or what to check, is a code of ``messages.json`` with parameters,
never a sentence: sent, stored and logged as ``{kind, code, params}`` and worded where it is read, in the reader's
language. Four kinds, by what the person can do: ``refused`` (nothing was done: fix it, wait, or ask), ``unavailable``
(a known part is down), ``internal`` (nobody planned for it: report the reference) and ``warning`` (done, check
something). This module is the one way to use a code on the server: ``message`` for one that travels inside an
answer or is stored, ``Problem`` for one that takes the answer's place (answered as RFC 9457 Problem Details by the
gateway). English here (``title``, ``detail``) is for developers and never shown to a person.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("refused", "unavailable", "internal", "warning")
PARAM_TYPES = {"number": (int, float), "string": (str,), "id": (str,)}
NAME = re.compile(r"[a-z]+\.[a-z][a-z0-9_]*")
URN = "urn:suveryn:problem:"  # a Problem's ``type``: a name, not an address (an appliance is offline)


@dataclass(frozen=True)
class Code:
    """One line of the registry."""

    name: str
    kind: str
    title: str                     # English, for developers
    status: int | None = None      # the HTTP status when it takes the answer's place
    retry: bool = False            # whether trying again can help
    params: dict[str, dict] = field(default_factory=dict)  # name -> {"type", "private"?}
    since: str = ""

    @property
    def area(self) -> str:
        return self.name.split(".", 1)[0]


def load(path: Path = Path(__file__).parent / "messages.json") -> tuple[tuple[str, ...], dict[str, Code]]:
    """The registry: its areas and its codes. A line that breaks a rule stops the load."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    areas = tuple(raw["areas"])
    codes = {}
    for name, e in raw["codes"].items():
        code = Code(name=name, kind=e["kind"], title=e["title"], status=e.get("status"), retry=e.get("retry", False),
                    params=e.get("params", {}), since=e.get("since", ""))
        ok = (NAME.fullmatch(name) and code.area in areas and code.kind in KINDS and code.title and code.since
              and all(p.get("type") in PARAM_TYPES for p in code.params.values())
              # a kind fixes the status range: refused 4xx, unavailable and internal 5xx, a warning travels in an answer
              and {"refused": code.status is not None and 400 <= code.status < 500,
                   "unavailable": code.status is not None and 500 <= code.status < 600,
                   "internal": code.status == 500, "warning": code.status is None}[code.kind])
        if not ok:
            raise ValueError(f"messages.json: {name!r} breaks the registry's rules")
        codes[name] = code
    return areas, codes


AREAS, CODES = load()


def message(code: str, **params) -> dict:
    """``{kind, code, params}`` for a listed code: what travels inside an answer, is stored, or is logged. A code
    that isn't listed, or a parameter it doesn't have or of another type, is a programming error."""
    known = CODES.get(code)
    if known is None:
        raise ValueError(f"{code!r} is not a code of messages.json")
    for name, value in params.items():
        spec = known.params.get(name)
        if spec is None or (value is not None and (isinstance(value, bool) or not isinstance(value, PARAM_TYPES[spec["type"]]))):
            raise ValueError(f"{code}: parameter {name!r} is not one of its parameters, or not a {spec and spec['type']}")
    return {"kind": known.kind, "code": code, "params": params}


def loggable(msg: dict) -> dict:
    """A message for the log: without the parameters that are client data (a file name, a case reference)."""
    spec = CODES[msg["code"]].params
    return {**msg, "params": {k: v for k, v in msg["params"].items() if not spec[k].get("private")}}


def reference() -> str:
    """A short id for an unplanned failure ("7F3K-92QD"): shown to the person, found in the log."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I: it is read aloud to support
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


class Problem(Exception):
    """A code that takes the answer's place. ``detail`` is English, for developers; ``headers`` go on the HTTP
    answer (``Retry-After``). The gateway answers it as Problem Details (``body``)."""

    def __init__(self, code: str, detail: str = "", headers: dict[str, str] | None = None, **params):
        self.message = message(code, **params)
        if CODES[code].status is None:
            raise ValueError(f"{code} is a {CODES[code].kind}: it travels inside an answer, not instead of one")
        super().__init__(detail or CODES[code].title)
        self.code, self.kind, self.params = code, CODES[code].kind, params
        self.status, self.detail, self.headers = CODES[code].status, detail or CODES[code].title, headers

    def body(self) -> dict:
        return problem(self.code, self.detail, **self.params)


def problem(code: str, detail: str = "", status: int | None = None, **params) -> dict:
    """An RFC 9457 Problem Details object for a code: the standard members, and ``code``, ``kind``, ``params``
    (an internal one's reference is its ``params.ref``). ``status`` only for a general code that stands for several statuses."""
    msg, known = message(code, **params), CODES[code]
    return {"type": URN + code, "title": known.title, "status": status or known.status, "detail": detail or known.title, **msg}
