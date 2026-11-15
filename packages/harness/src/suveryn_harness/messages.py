"""Messages are codes (the handbook's decision of 12 November 2026; docs/design/messages.md).

Everything the server says about what went wrong, or what to check, is a code of ``messages.json`` with parameters,
never a sentence: sent, stored and logged as ``{kind, code, params}`` and worded where it is read, in the reader's
language. Four kinds, by what the person can do: ``refused`` (nothing was done: fix it, wait, or ask), ``unavailable``
(a known part is down), ``internal`` (nobody planned for it: report the reference) and ``warning`` (done, check
something). This module is the one way to use a code on the server: ``message`` for one that travels inside an
answer or is stored, ``Problem`` for one that takes the answer's place (answered as RFC 9457 Problem Details by the
gateway). English here (``title``, ``detail``) is for developers and never shown to a person.

Standard library only, and nothing imported from the rest of the package: the appliance's web setup loads this
file by its path, before any of sūveryn's services exist (suveryn-tracker#141). A test keeps it so.
"""
from __future__ import annotations

import json
import re
import secrets
import traceback
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
    status: int | None = None      # the HTTP status when it takes the answer's place; none for one that never does
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
              # A kind fixes the status range: refused 4xx, unavailable 5xx, internal 500. A refusal or a part that
              # is down can also be an upload's or a run's stored error, never an HTTP answer: then it has no status,
              # as a warning never has (it travels inside an answer). The kind says what the person can do, the
              # status only how it travels.
              and {"refused": code.status is None or 400 <= code.status < 500,
                   "unavailable": code.status is None or 500 <= code.status < 600,
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


def stored(raw) -> dict | None:
    """A message read back from where it was kept, or from the answer of one of the appliance's helpers (the backup
    service, the clock): ``{kind, code, params}`` as the registry has it today, the kind from the registry and only
    the parameters the code has. None where there is none. What isn't a message of the registry (a row from before
    failures were codes, a helper's answer that went wrong) says that it failed and no more: ``system.internal``
    without a reference, which a screen words by its kind. The one place this is decided."""
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    known = CODES.get(raw.get("code")) if isinstance(raw, dict) and isinstance(raw.get("code"), str) else None
    if known is None:
        return {"kind": "internal", "code": "system.internal", "params": {}}
    given = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    params = {k: v for k, v in given.items() if k in known.params and not isinstance(v, bool) and isinstance(v, PARAM_TYPES[known.params[k]["type"]])}
    return {"kind": known.kind, "code": known.name, "params": params}


def why(raw) -> dict:
    """Why something failed, read back (``stored``): its message, or, when none was kept, that it failed."""
    return stored(raw) or {"kind": "internal", "code": "system.internal", "params": {}}


def loggable(msg: dict) -> dict:
    """A message for the log: without the parameters that are client data (a file name, a case reference)."""
    spec = CODES[msg["code"]].params
    return {**msg, "params": {k: v for k, v in msg["params"].items() if not spec[k].get("private")}}


def reference() -> str:
    """A short id for an unplanned failure ("7F3K-92QD"): shown to the person, found in the log."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I: it is read aloud to support
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def unplanned(exc: BaseException) -> tuple[str, str]:
    """For a failure nobody planned for: a new reference, and where it was raised, for the log line that carries the
    reference ("documents.py:137 delete_document < routing.py:360 run"). The exception's type is the caller's to
    add; never its message, which may quote a document or name a file. The one place this is worked out: an HTTP
    answer, a stream, a playbook run and a reading all log an unplanned failure alike."""
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    return reference(), " < ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno} {f.name}" for f in reversed(frames)) or "?"


class Problem(Exception):
    """A code that takes the answer's place. ``detail`` is English, for developers; ``headers`` go on the HTTP
    answer (``Retry-After``). The gateway answers it as Problem Details (``body``)."""

    def __init__(self, code: str, detail: str = "", headers: dict[str, str] | None = None, **params):
        self.message = message(code, **params)
        if CODES[code].status is None:
            raise ValueError(f"{code} has no status: it travels inside an answer or is stored, never instead of an answer")
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
