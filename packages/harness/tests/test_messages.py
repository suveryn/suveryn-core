"""The registry of messages (the handbook's decision of 12 November 2026, *Messages are codes*): every code keeps the
registry's rules, the server can only use a listed code with its own parameters, and client data stays out of logs."""
import ast
import json
import re
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
    {"kind": "unavailable", "status": 409},              # a part that is down is a 5xx
    {"kind": "internal", "status": None},                # something unplanned always takes the answer's place
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
                  lambda: message("upload.too_large", max_mb="100"), lambda: Problem("calc.unreadable")):  # a warning is no Problem
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
    makers = {"Problem", "UploadRejected", "CalcError", "AmbiguousSeparator", "answer", "message", "msg", "problem",
              "Unreadable", "ExtractionFailed", "IntegrityWarning"}
    used = set()
    for path in PACKAGES.glob("*/src/**/*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = getattr(getattr(node, "func", None), "attr", None) or getattr(getattr(node, "func", None), "id", None)
            if isinstance(node, ast.Call) and name in makers:
                used |= {a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
                         and messages.NAME.fullmatch(a.value) and a.value.split(".")[0] in AREAS}
    assert len(used) >= 25 and used <= set(CODES), used - set(CODES)


def test_the_module_loads_by_its_path_alone_as_the_appliances_web_setup_loads_it():
    """suveryn-tracker#141: one list. The setup service runs before sūveryn's services exist, with the system's
    Python in isolated mode, and loads this file by its path: standard library only, nothing from the package."""
    import subprocess
    import sys
    from pathlib import Path
    path = Path(messages.__file__)
    code = ("import importlib.machinery, importlib.util, sys\n"
            f"l = importlib.machinery.SourceFileLoader('m', {str(path)!r})\n"
            "m = importlib.util.module_from_spec(importlib.util.spec_from_loader('m', l)); sys.modules['m'] = m; l.exec_module(m)\n"
            "assert 'suveryn_harness' not in sys.modules\n"
            "print(m.problem('setup.password_too_short', min=15)['status'], 'setup' in m.AREAS)\n")
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
    assert r.stdout.split() == ["422", "True"], r.stderr


def test_the_kind_says_what_the_person_can_do_and_the_status_only_how_it_travels():
    # The decision of 12 November: refused and unavailable also travel as an upload's or a run's stored error. Such
    # a code has no status and keeps its kind: a document that can't be read is refused (nothing was done), never
    # a warning (done, check something) because it happens to travel inside a job.
    stored = CODES["document.password_protected"]
    assert (stored.kind, stored.status) == ("refused", None)
    assert message("document.pages_too_many", pages=900, max=500) == {
        "kind": "refused", "code": "document.pages_too_many", "params": {"pages": 900, "max": 500}}
    with pytest.raises(ValueError, match="never instead of an answer"):
        Problem("document.password_protected")
    # what was done and needs checking is a warning, with the page it is about
    assert message("document.page_coverage_low", page=4) == {"kind": "warning", "code": "document.page_coverage_low", "params": {"page": 4}}
    for code in CODES.values():
        if code.kind == "warning":
            assert code.status is None, code.name


def test_an_unplanned_failure_gets_a_reference_and_its_place_never_its_message():
    def read():
        raise RuntimeError("Peeters, Echtscheiding.pdf")  # a message may name a file or quote a document
    try:
        read()
    except RuntimeError as e:
        ref, where = messages.unplanned(e)
    assert re.fullmatch(r"[2-9A-Z]{4}-[2-9A-Z]{4}", ref)
    assert where.startswith("test_messages.py:") and " read" in where and "Peeters" not in where


def test_a_message_read_back_is_what_the_registry_has_today_and_nothing_else():
    # from a store, or from one of the appliance's helpers, which read the same registry: nothing is translated
    assert messages.stored({"code": "backup.key_mismatch"}) == {"kind": "refused", "code": "backup.key_mismatch", "params": {}}
    assert messages.stored('{"kind": "warning", "code": "clock.synced", "params": {"x": 1}}') == {"kind": "refused", "code": "clock.synced", "params": {}}
    assert messages.stored({"code": "system.internal", "params": {"ref": "7F3K-92QD", "more": "x"}})["params"] == {"ref": "7F3K-92QD"}
    assert messages.stored(None) is None and messages.stored("") is None
    # what isn't a message of the registry says that it failed and no more
    internal = {"kind": "internal", "code": "system.internal", "params": {}}
    assert messages.stored("interrupted") == internal and messages.stored({"code": "backup.made_up"}) == internal
    assert messages.why(None) == internal and messages.why({"code": "backup.disk_full"})["kind"] == "unavailable"


# ---------------------------------------------------------------------------- names (docs/design/names.md)
# What a code's condition may end in, each with one meaning (names.md has the meanings). A new ending is added here
# on purpose, in the change that needs it, with its meaning in names.md.
ENDINGS = (
    "unavailable", "unreachable", "not_found", "missing", "gone", "invalid", "mismatch", "unsupported", "out_of_range",
    "unreadable", "damaged", "empty", "expired", "changed", "full", "busy", "exists", "protected", "removed", "unsafe",
    "outside", "unclear", "mixed", "low", "recovered", "refused", "failed", "unfinished",
    r"too_(?:large|many|long|short|slow|new)", r"not_a_[a-z]+", r"no_[a-z]+", r"already_[a-z]+", r"[a-z_]+_only",
    r"not_(?:allowed|local|writable|switched_off|checked|asked)",
    "paused", "ended", "closed", "synced", "started", "signed_out", "interrupted", "moved_on")
# The codes that state a fact in words of their own.
OWN_WORDS = {"case.single_manager", "case.strictly_confidential", "conversation.in_case", "account.last_administrator",
             "account.own_account", "account.manages_cases", "calc.division_by_zero", "document.instruction_like_text",
             "setup.password_common", "setup.password_personal", "setup.manifest_other_appliance"}
# Words a condition no longer uses: each has one word of the list instead, or names the cure and not the fact.
BANNED = re.compile(r"too_big|none_found|_first$|^wrong_|^unknown$|_unknown$|timeout|^not_zip$")
# The general codes keep the names of the web's own statuses; `system.internal` is the one for what nobody planned.
GENERAL = {"request.forbidden", "request.conflict", "system.internal"}


def test_a_code_is_named_by_the_convention():
    ends = re.compile(r"(?:.*_)?(?:%s)" % "|".join(ENDINGS))
    assert OWN_WORDS <= set(CODES) and GENERAL <= set(CODES)
    for name in CODES:
        condition = name.split(".", 1)[1]
        assert not BANNED.search(condition), f"{name}: a word the convention no longer uses (docs/design/names.md)"
        assert name in OWN_WORDS | GENERAL or ends.fullmatch(condition), (
            f"{name}: its condition ends in none of the listed endings (docs/design/names.md); "
            "a new ending is added to ENDINGS on purpose, with its meaning in names.md")
    # the test stops a banned word and an unlisted ending; whether a name is true is read from the code that says it


def test_an_area_that_is_down_says_so_under_its_own_name():
    # `system` is for what has no area of its own: the model and document handling have one
    assert {name for name in CODES if name.startswith("system.")} == {"system.internal", "system.unavailable", "system.database_unavailable"}
    assert {"model.unavailable", "document.unavailable"} <= set(CODES)
    assert all(CODES[name].area != "user" or "picture" in name for name in CODES)  # the rest of a person's codes are their account's


def test_a_released_code_is_never_renamed_or_removed():
    from suveryn_harness import released

    listed = released.released()
    assert listed == sorted(set(listed))
    gone = sorted(set(listed) - set(CODES))
    assert not gone, f"released codes that are no longer in the registry: {gone} (a stored code must still be read)"


def test_releasing_adds_the_registrys_codes_and_takes_none_away(tmp_path, monkeypatch):
    from suveryn_harness import released

    listed = tmp_path / "messages-released.json"
    listed.write_text(json.dumps({"_about": "x", "codes": ["zz.kept_from_before"]}), encoding="utf-8")
    monkeypatch.setattr(released, "FILE", listed)
    assert released.release() == len(CODES) + 1
    after = json.loads(listed.read_text(encoding="utf-8"))
    assert set(after["codes"]) == set(CODES) | {"zz.kept_from_before"} and after["codes"] == sorted(after["codes"]) and after["_about"] == "x"
    monkeypatch.setattr(released, "released", lambda: ["zz.kept_from_before"])
    with pytest.raises(AssertionError, match="zz.kept_from_before"):
        test_a_released_code_is_never_renamed_or_removed()

