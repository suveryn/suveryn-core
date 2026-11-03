"""A check step's rule evaluated on the run's values (suveryn_harness.checks): by the server, by kind,
holding, failing or open."""

from suveryn_harness.checks import evaluate
from suveryn_playbooks import Wording
from suveryn_playbooks.manifest import parse
from suveryn_playbooks.rules import parse_rule

MANIFEST = """
manifest: 3
id: playbook/be-notary/formation-test
pack: pack/be-notary
version: "1.0"
name: Formation test
case_types: [company-formation]
facts:
  - {id: contribution, ask: the total, kind: amount}
  - {id: shares, ask: the shares issued, kind: number}
  - {id: plan_date, ask: the plan's date, kind: date}
  - {id: deed_date, ask: the deed's date, kind: date}
  - id: founders
    ask: the founders
    kind: list
    of:
      - {id: name, ask: the name}
      - {id: shares, ask: the shares, kind: number}
      - {id: contribution, ask: the contribution, kind: amount}
  - id: conditions
    ask: the conditions
    kind: list
    of:
      - {id: condition, ask: the condition}
      - {id: term, ask: the term, kind: date}
instructions: Read.
steps:
  - {id: read, kind: read, facts: all}
  - {id: confirm, kind: checkpoint}
"""
WORDS = {lang: Wording("F", "f", {}) for lang in ("en", "nl", "fr")}
P = parse(MANIFEST).to_playbook(WORDS)
VALUES = {"contribution": "50.000,00 euro", "shares": "1.000 aandelen", "plan_date": "28 oktober 2026", "deed_date": "15/11/2026",
          "founders[1].name": "Filip Tack", "founders[1].shares": "600", "founders[1].contribution": "30.000 euro",
          "founders[2].name": "Anna Peeters", "founders[2].shares": "400", "founders[2].contribution": "twintigduizend euro"}


def check(rule: str, values=VALUES):
    return evaluate(parse_rule(rule, P), values)


def test_sums_counts_and_comparisons_by_kind():
    assert check("sum(founders.shares) == shares").status == "holds"
    r = check("sum(founders.contribution) == contribution")
    assert (r.status, r.left, r.right) == ("holds", "50000", "50000")   # twenty thousand in words counts
    assert check("count(founders) >= 1").status == "holds" and check("count(founders) == 3").status == "fails"
    assert check("plan_date <= deed_date").status == "holds" and check("plan_date > deed_date").status == "fails"
    r = check("sum(founders.shares) == shares", {**VALUES, "founders[2].shares": "350"})
    assert (r.status, r.left, r.right) == ("fails", "950", "1000")
    assert check("shares != 1000").status == "fails" and check("shares >= 0.5").status == "holds"


def test_a_missing_or_unreadable_value_leaves_the_check_open_and_names_what_is_needed():
    r = check("sum(founders.contribution) == contribution", {**VALUES, "founders[2].contribution": ""})
    assert r.status == "open" and r.missing == ("founders[2].contribution",) and r.right == "50000"
    r = check("plan_date <= deed_date", {**VALUES, "deed_date": "na de ondertekening"})
    assert r.status == "open" and r.missing == ("deed_date",) and r.left == "2026-10-28"
    assert check("count(founders) >= 1", {"contribution": "1"}).status == "fails"   # no entries: a count of 0, not open
    assert check("shares == 1000", {}).status == "open"


def test_the_decimal_style_is_read_from_the_values():
    english = {"contribution": "EUR 50,000.00", "founders[1].contribution": "EUR 30,000.00", "founders[2].contribution": "EUR 20,000.00"}
    r = check("sum(founders.contribution) == contribution", english)
    assert (r.status, r.left) == ("holds", "50000")


def test_the_latest_and_the_earliest_of_a_lists_dates():
    """Deed intake 1.3: every condition's term before the deed, in one line."""
    terms = {**VALUES, "conditions[1].condition": "financiering", "conditions[1].term": "2 november 2026",
             "conditions[2].condition": "vergunning", "conditions[2].term": "10/11/2026"}
    r = check("latest(conditions.term) <= deed_date", terms)
    assert (r.status, r.left, r.right) == ("holds", "2026-11-10", "2026-11-15")
    assert check("earliest(conditions.term) > plan_date", terms).status == "holds"
    assert check("latest(conditions.term) <= plan_date", terms).status == "fails"
    # a term that isn't a date yet: open, naming it
    r = check("latest(conditions.term) <= deed_date", {**terms, "conditions[2].term": "30 dagen na ondertekening"})
    assert r.status == "open" and r.missing == ("conditions[2].term",)
    # no conditions at all: nothing can fall after the deed, the check holds
    r = check("latest(conditions.term) <= deed_date", VALUES)
    assert (r.status, r.left, r.right) == ("holds", "", "2026-11-15")
