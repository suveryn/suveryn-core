"""The runtime's order of steps (``playbook_runtime.next_step``), without a database: which step
comes next from a given state. The walk itself, with its stores, is in test_playbooks.py."""

from suveryn_api_gateway.playbook_runtime import next_step
from suveryn_api_gateway.playbooks import StepState
from suveryn_playbooks import DEED_INTAKE, Wording
from suveryn_playbooks.manifest import parse

MINIMAL = """\
manifest: 3
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


def test_a_reading_again_keeps_what_stands_and_never_replaces_a_confirmed_value():
    """A document that came later (decision of 10 November 2026): read again, a fact not found or found as it stands
    keeps its version; one only read, or left empty, takes the new reading; one a person confirmed or answered keeps
    its value and the new reading waits beside it. Amounts by meaning; text never by a figure in it."""
    from suveryn_api_gateway.playbook_runtime import Runtime, same_value
    from suveryn_harness.facts import RunFact
    from suveryn_playbooks import DEED_INTAKE
    step = next(s for s in DEED_INTAKE.steps if s.id == "agreement_read")

    def version(value, status="proposed", kind="document"):
        return {"id": f"v-{value}-{status}", "value": value, "status": status, "source": {"kind": kind}}
    current = {"price": version("EUR 412.500,00", "confirmed", "person"), "deposit": version("EUR 40.000,00"),
               "property": version("", "not_established", "person"), "occupancy": version("Vrij", "proposed", "person"),
               "agreement_date": version("3 oktober 2026")}
    read = [RunFact(id="price", value="EUR 415.000,00"), RunFact(id="deposit", value="EUR 41.000,00"),
            RunFact(id="property", value="Havenlaan 2"), RunFact(id="occupancy", value="Verhuurd"),
            RunFact(id="agreement_date", value="03/10/2026"), RunFact(id="cadastral", value="", found=False),
            RunFact(id="title", value="Akte 1998")]  # not this read's fact
    rows = {r["fact_id"]: r for r in Runtime.read_rows(DEED_INTAKE, step, read, current)}
    assert rows["price"]["source"]["competes"] == "v-EUR 412.500,00-confirmed" and "replaces" not in rows["price"]
    assert rows["occupancy"]["source"]["competes"]          # a person's answer competes too
    assert rows["deposit"]["replaces"] == "v-EUR 40.000,00-proposed" and "competes" not in rows["deposit"]["source"]
    assert rows["property"]["replaces"] == "v--not_established"  # left empty: the new reading fills it
    assert rows["cadastral"]["status"] == "not_established"  # never read before: as a first read
    assert "agreement_date" not in rows and "title" not in rows  # the same date by meaning; another read's fact
    assert same_value("EUR 18.000,00", "18.000 euro", "amount") and not same_value("Havenlaan 2", "Havenlaan 2, 9999 Testdorp")
