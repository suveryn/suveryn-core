"""The runtime's order of steps (``playbook_runtime.next_step``), without a database: which step
comes next from a given state. The walk itself, with its stores, is in test_playbooks.py."""

from suveryn_api_gateway.playbook_runtime import next_step
from suveryn_api_gateway.playbooks import StepState
from suveryn_playbooks import DEED_INTAKE, Wording
from suveryn_playbooks.manifest import parse

MINIMAL = """\
manifest: 2
id: playbook/be-notary/example
pack: pack/be-notary
version: "1.0"
name: Example
case_types: [sale]
facts:
  - {id: price, ask: the price, kind: amount}
  - {id: sellers, ask: who sells}
instructions: Read.
steps:
  - {id: agreement, kind: request}
  - {id: read, kind: read, facts: all}
  - {id: missing, kind: ask, facts: all}
  - {id: confirm, kind: checkpoint}
  - {id: summary, kind: produce}
"""
WORDS = {lang: Wording("Example", "An example", {"price": "Price", "sellers": "Sellers"}, {"agreement": "Upload.", "missing": "{label}?"})
         for lang in ("en", "nl", "fr")}
PB = parse(MINIMAL).to_playbook(WORDS)


def done(*ids: str) -> dict[str, StepState]:
    return {i: StepState(status="done") for i in ids}


def test_nothing_done_the_first_step_is_next():
    assert next_step(PB, {}).id == "agreement"
    assert next_step(DEED_INTAKE, {}).id == "agreement"


def test_each_step_waits_for_what_it_needs():
    assert next_step(PB, done("agreement")).id == "read"
    assert next_step(PB, done("agreement", "read")).id == "missing"
    assert next_step(PB, done("agreement", "read", "missing")).id == "confirm"
    assert next_step(PB, done("agreement", "read", "missing", "confirm")).id == "summary"
    assert next_step(PB, done("agreement", "read", "missing", "confirm", "summary")) is None


def test_a_skipped_step_counts_as_done_for_what_follows():
    states = {**done("agreement", "read"), "missing": StepState(status="skipped")}
    assert next_step(PB, states).id == "confirm"


def test_an_active_step_is_still_the_next_one():
    """A step that is active (the run is waiting on it) is what the run is on; nothing jumps past it."""
    states = {**done("agreement"), "read": StepState(status="active")}
    assert next_step(PB, states).id == "read"


def test_a_graph_that_is_not_a_line_follows_needs_not_order():
    text = MINIMAL.replace("  - {id: missing, kind: ask, facts: all}\n", "  - {id: missing, kind: ask, facts: all, needs: [read]}\n") \
                  .replace("  - {id: confirm, kind: checkpoint}\n", "  - {id: confirm, kind: checkpoint, needs: [read, missing]}\n")
    pb = parse(text).to_playbook(WORDS)
    assert next_step(pb, done("agreement", "read")).id == "missing"
    assert next_step(pb, {**done("agreement", "read"), "missing": StepState(status="skipped")}).id == "confirm"
    assert next_step(pb, done("agreement")).id == "read"


def test_a_run_from_before_the_routine_has_no_steps_to_walk():
    """``Runtime.advance`` returns at once for such a run (its ``steps`` are empty); the routes answer 409."""
    from suveryn_api_gateway.playbook_runtime import Runtime
    from suveryn_api_gateway.playbooks import Run

    run = Run(id="00000000-0000-0000-0000-000000000001", case_id="00000000-0000-0000-0000-000000000002", playbook_id=PB.id,
              playbook_version="1.0", status="waiting", documents=[], started_by="x", started_at="2026-10-30T10:00:00Z")
    assert Runtime(None, None, lambda _c: {}).advance(run, PB, "2026/1") is None
