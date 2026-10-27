"""Source marking on the server (suveryn-tracker#25, step 2): the shared regression set, and the response."""

import json
from pathlib import Path

import pytest

from suveryn_harness.marking import answer_sentences, facts, sentence_ranges, support_spans, word_value
from suveryn_harness.schemas import Citation, SourceRef
from suveryn_harness.support import _claims

CASES = json.loads((Path(__file__).parent / "marking_cases.json").read_text())["cases"]


def _runs(passage: str, ranges, strong) -> tuple[list[str], list[str]]:
    """The marked runs and the strongly marked parts, as the source card shows them."""
    mark = [None] * len(passage)
    for a, z in ranges:
        mark[a:z] = ["sentence"] * (z - a)
    for a, z in strong:
        mark[a:z] = ["term"] * (z - a)
    runs, terms = [], []
    for i, c in enumerate(passage):
        if mark[i] and i > 0 and mark[i - 1]:
            runs[-1] += c
        elif mark[i]:
            runs.append(c)
        if mark[i] == "term" and i > 0 and mark[i - 1] == "term":
            terms[-1] += c
        elif mark[i] == "term":
            terms.append(c)
    return runs, terms


def _citation(text: str) -> Citation:
    return Citation(text=text, source=SourceRef(document_id="doc-1"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_regression_set(case):
    spans = support_spans(case["answer"], [_citation(case["passage"])])
    first = next((s for s in spans if s.marker == 0), None)
    runs, strong = _runs(case["passage"], first.ranges, first.facts) if first else ([], [])
    assert runs == case["marked"]
    assert strong == case["strong"]


def test_sentences():
    assert answer_sentences("See no. 4 and p. 12 of the annex. J. Smith signed it.") == [
        "See no. 4 and p. 12 of the annex.", "J. Smith signed it."]
    table = "Costs\n| Item | Amount |\n| Deposit | 25,000 |"
    assert [table[a:z] for a, z in sentence_ranges(table)] == ["Costs", "| Item | Amount |", "| Deposit | 25,000 |"]


def test_facts():
    values = lambda text: [f.values[0] for f in facts(text)]  # noqa: E731
    assert values("€ 1,2 million, EUR 1.200.000,00, 1.2 mio and two million") == ["n:1200000"] * 3 + ["n:2000000"]
    for text in ["12/03/2021", "12.03.2021", "12/03/21", "2021-03-12", "12 March 2021", "March 12, 2021", "12 maart 2021",
                 "12 mars 2021"]:
        assert values(text)[0] == "d:2021-03-12", text
    assert [word_value(w) for w in ["twaalf", "eenentwintig", "vingt-deux", "quatre-vingt-dix", "twenty-one"]] == [12, 21, 22, 90, 21]
    assert [word_value(w) for w in ["een", "un", "one", "self-employed"]] == [None] * 4
    assert values("vingt et un") == ["n:21"]


def test_offsets_count_as_the_browser_does():
    # a character outside the Basic Multilingual Plane counts as two in JavaScript
    passage = "\U0001d4d0 Heading. The price amounts to EUR 250.000,00."
    [span] = support_spans("The price is 250 000 euro [1].", [_citation(passage)])
    utf16 = passage.encode("utf-16-le")
    a, z = span.ranges[0]
    assert utf16[2 * a:2 * z].decode("utf-16-le") == "The price amounts to EUR 250.000,00."


def test_every_valid_marker_and_its_number():
    answer = "Under art. 3 the seller pays [1][2]. The buyer pays 250 000 euro [9]. Price: 250 000 euro [2]."
    citations = [_citation("Under art. 3 the seller pays the survey."), _citation("The price is 250 000 euro.")]
    spans = support_spans(answer, citations)
    # [9] is no citation and isn't counted; the second marker's claim isn't in passage 2, so nothing to mark there
    assert [(s.marker, s.n) for s in spans] == [(0, 1), (2, 2)]
    # the citation check reads the same claims: "art. 3" doesn't end one
    assert [claim for claim, *_ in _claims(answer, 2)][0] == "Under art. 3 the seller pays "
