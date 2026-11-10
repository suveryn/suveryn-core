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
    elif case.get("no_date"):
        assert not any(k in ("date", "month") for k, _ in got)
    else:
        kind = next(k for k in ("number", "date", "month") if k in case)
        want = case[kind]
        assert got == [(kind, str(Decimal(want).normalize()) if kind == "number" and "." in want else want)]


def test_positions_point_at_the_written_form():
    text = "De prijs is 1,2 miljoen euro, te betalen op 12 maart 2021."
    found = read(text)
    assert [text[f.start:f.end] for f in found] == ["1,2 miljoen", "12 maart 2021"]
