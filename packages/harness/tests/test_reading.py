"""How sūveryn reads amounts and dates (``values.read``), held to ``reading_cases.json``: each written form with
the one thing it means. The citation check, the source marking, a playbook's facts and its checks read through
this one reader, so they can't disagree about the same text."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from suveryn_harness.values import read

CASES = json.loads((Path(__file__).parent / "reading_cases.json").read_text(encoding="utf-8"))["cases"]


def _shown(found) -> tuple[str, object]:
    if found.kind == "number":
        return "number", str(found.value.normalize()) if found.value != found.value.to_integral() else str(int(found.value))
    return found.kind, list(found.value)


@pytest.mark.parametrize("case", CASES, ids=[f"{c['written']}{' (' + c['style'] + ')' if c.get('style') else ''}" for c in CASES])
def test_a_written_form_reads_as_what_it_means(case):
    got = [_shown(f) for f in read(case["written"], case.get("style"))]
    if case.get("nothing"):
        assert got == []
    elif "numbers" in case:
        assert got == [("number", n) for n in case["numbers"]]
    elif case.get("no_date"):
        assert not any(k in ("date", "month") for k, _ in got)
    else:
        kind = next(k for k in ("number", "date", "month") if k in case)
        want = case[kind]
        assert got == [(kind, str(Decimal(want).normalize()) if kind == "number" and "." in want else want)]
        [found] = read(case["written"], case.get("style"))
        assert (found.percent, found.approximate) == (case.get("percent", False), case.get("approximate", False))
        if "measure" in case:
            assert found.measure == case["measure"]


def test_numbers_as_the_standard_spells_them_are_read():
    """The reader's number words come from the standard spelling rules (``tools/number_words.py``); here it reads a
    sample of numbers back as that standard writes them, per language: every number from 2 to 199 and three hundred
    up to two million. (10 November 2026: read by the hand-written tables, French "cent quatre-vingt" was 2 080.)"""
    cases = json.loads((Path(__file__).parent / "spelled_numbers.json").read_text(encoding="utf-8"))["cases"]
    wrong = []
    for c in cases:
        got = [int(f.value) for f in read(c["written"] + " euro") if f.kind == "number"]
        if got != [c["number"]]:
            wrong.append((c["language"], c["written"], got))
    assert len(cases) > 2000 and wrong == []


def test_positions_point_at_the_written_form():
    text = "De prijs is 1,2 miljoen euro, te betalen op 12 maart 2021."
    found = read(text)
    assert [text[f.start:f.end] for f in found] == ["1,2 miljoen", "12 maart 2021"]
