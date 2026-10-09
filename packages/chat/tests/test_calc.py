import pytest
from suveryn_chat.calc import CalcError, CalcRewriter, evaluate, rewrite

SOURCE = "Nettobedrag: + 6.507,11 EUR\nNettobedrag: + 6.417,42 EUR\n3.000 stukken aan 2,15 EUR"


@pytest.mark.parametrize("expression, result", [
    ("6.507,11 + 6.417,42", "12.924,53"),          # Belgian style, grouping kept
    ("6,507.11 + 6,417.42", "12,924.53"),          # English style
    ("6 507,11 + 6 417,42", "12 924,53"),          # space grouping
    ("6507.11 - 6417.42", "89.69"),
    ("3.000 * 2,15", "6.450,00"),                  # "3.000" is read as thousands because 2,15 shows the style
    ("-(10,00 + 22,89)", "-32,89"),
    ("100 / 3", "33.33"),                          # division: at least 2 decimals, rounded half up
    ("6.507,11 EUR + 6.417,42 €", "12.924,53"),    # currencies are ignored
    ("1 + 2 × 3", "7"),
])
def test_evaluate(expression, result):
    assert evaluate(expression)[0] == result


@pytest.mark.parametrize("expression", ["1.250 + 3.000", "1 / 0", "2 +", "(1 + 2", "import os", ""])
def test_refuses_rather_than_guesses(expression):
    with pytest.raises(CalcError):
        evaluate(expression)


def test_rewrite_replaces_marker_and_checks_figures_against_sources():
    text, calcs = rewrite("Totaal: [[calc: 6.507,11 + 6.417,42]] EUR [1][2].", SOURCE)
    assert text == "Totaal: 6.507,11 + 6.417,42 = 12.924,53 EUR [1][2]."
    assert calcs[0].result == "12.924,53" and calcs[0].figures_not_in_sources == []
    _, calcs = rewrite("[[calc: 6.507,11 + 999,99]]", SOURCE)
    assert calcs[0].figures_not_in_sources == ["999,99"]


def test_failed_calculation_is_visible_not_silent():
    text, calcs = rewrite("[[calc: 1.250 + 3.000]]", SOURCE)
    assert text == "[calculation not possible: 1.250 + 3.000]"
    assert calcs[0].result is None and calcs[0].error


def test_streaming_marker_split_across_chunks_and_citations_untouched():
    r = CalcRewriter(SOURCE)
    pieces = ["Totaal [1", "] is [", "[cal", "c: 6.507,11 + 6.", "417,42]", "] EUR [2]."]
    out = "".join(r.feed(p) for p in pieces) + r.flush()
    assert out == "Totaal [1] is 6.507,11 + 6.417,42 = 12.924,53 EUR [2]."


def test_unclosed_brackets_are_released():
    r = CalcRewriter(SOURCE)
    out = r.feed("a [[ b " + "x" * 400) + r.flush()
    assert out == "a [[ b " + "x" * 400 and r.calculations == []
