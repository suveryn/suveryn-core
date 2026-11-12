"""The registry of messages (the handbook's decision of 12 November 2026, *Messages are codes*): every code keeps the
registry's rules, the server can only use a listed code with its own parameters, and client data stays out of logs."""
import ast
import json
from pathlib import Path

import pytest
from suveryn_harness import messages
from suveryn_harness.messages import AREAS, CODES, Problem, loggable, message, problem, reference

PACKAGES = Path(__file__).resolve().parents[2]


def test_every_code_keeps_the_rules():
    assert len(CODES) >= 30 and {c.kind for c in CODES.values()} == set(messages.KINDS)
    for code in CODES.values():
        assert code.area in AREAS and code.title and code.since, code.name
    assert CODES["system.internal"].kind == "internal" and CODES["system.internal"].status == 500


@pytest.mark.parametrize("change", [
    {"kind": "error"},                                   # not one of the four kinds
    {"kind": "refused", "status": 503},                  # a refusal is a 4xx
    {"kind": "warning", "status": 409},                  # a warning travels inside an answer
    {"params": {"n": {"type": "text"}}},                 # not a parameter type
    {"title": ""},
])
def test_a_line_that_breaks_a_rule_stops_the_load(tmp_path, change):
    line = {"kind": "refused", "status": 409, "title": "x", "since": "0.2.0", **change}
    path = tmp_path / "messages.json"
    path.write_text(json.dumps({"areas": ["run"], "codes": {"run.paused": line}}), encoding="utf-8")
    with pytest.raises(ValueError):
        messages.load(path)
    for name in ("Run.paused", "run", "other.paused"):   # the name's shape, and its area
        path.write_text(json.dumps({"areas": ["run"], "codes": {name: {"kind": "refused", "status": 409, "title": "x", "since": "1"}}}))
        with pytest.raises(ValueError):
            messages.load(path)


def test_a_message_is_a_listed_code_with_its_own_parameters():
    assert message("upload.too_large", max_mb=100) == {"kind": "refused", "code": "upload.too_large", "params": {"max_mb": 100}}
    for wrong in (lambda: message("upload.too_big"), lambda: message("upload.too_large", size=1),
                  lambda: message("upload.too_large", max_mb="100"), lambda: Problem("calc.syntax")):  # a warning is no Problem
        with pytest.raises(ValueError):
            wrong()


def test_a_problem_is_problem_details_with_the_code():
    body = Problem("request.too_many", "Too many requests.", seconds=12).body()
    assert body == {"type": "urn:suveryn:problem:request.too_many", "title": CODES["request.too_many"].title, "status": 429,
                    "detail": "Too many requests.", "kind": "refused", "code": "request.too_many", "params": {"seconds": 12}}
    assert problem("request.invalid", status=400)["status"] == 400  # a general code stands for several statuses


def test_client_data_stays_out_of_the_log(monkeypatch):
    private = messages.Code("upload.empty", "refused", "x", 415, params={"name": {"type": "string", "private": True}, "n": {"type": "number"}})
    monkeypatch.setitem(messages.CODES, "upload.empty", private)
    assert loggable(message("upload.empty", name="Echtscheiding Peeters.pdf", n=2))["params"] == {"n": 2}


def test_a_reference_reads_aloud():
    ref = reference()
    assert len(ref) == 9 and ref[4] == "-" and not set(ref) & set("01IO") and ref != reference()


def test_the_server_uses_only_listed_codes():
    """Every code written where a message is made, in any package, is in the registry."""
    makers = {"Problem", "UploadRejected", "CalcError", "AmbiguousSeparator", "answer", "message", "msg", "problem"}
    used = set()
    for path in PACKAGES.glob("*/src/**/*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = getattr(getattr(node, "func", None), "attr", None) or getattr(getattr(node, "func", None), "id", None)
            if isinstance(node, ast.Call) and name in makers:
                used |= {a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
                         and messages.NAME.fullmatch(a.value) and a.value.split(".")[0] in AREAS}
    assert len(used) >= 25 and used <= set(CODES), used - set(CODES)
