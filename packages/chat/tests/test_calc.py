import pytest
from suveryn_chat.calc import (
    CalcError,
    CalcRewriter,
    evaluate,
    rewrite,
    unverified_figures,
)

SOURCE = "Nettobedrag: + 6.507,11 EUR\nNettobedrag: + 6.417,42 EUR\n3.000 stukken aan 2,15 EUR"


@pytest.mark.parametrize("expression, result", [
    ("6.507,11 + 6.417,42", "12.924,53"),          # Belgian style, grouping kept
    ("6,507.11 + 6,417.42", "12,924.53"),          # English style
    ("6 507,11 + 6 417,42", "12 924,53"),          # space grouping
    ("6507.11 - 6417.42", "89.69"),
    ("3.000 * 2,15", "6.450,00"),                  # "3.000" is read as thousands because 2,15 shows the style
    ("-(10,00 + 22,89)", "-32,89"),
    ("100 / 3", "33.33"),                          # division: at least 2 decimals, rounded half up
    ("0,25 * 0,25", "0,0625"),                     # products keep their exact decimals
    ("2,5 * 2,5", "6,25"),
    ("99999999999999.99 * 99999999999999.99", "9999999999999998000000000000.0001"),
    ("6.507,11 EUR + 6.417,42 €", "12.924,53"),    # currencies are ignored
    ("1 + 2 × 3", "7"),
])
def test_evaluate(expression, result):
    assert evaluate(expression)[0] == result


@pytest.mark.parametrize("expression", [
    "1.250 + 3.000", "1 / 0", "2 +", "(1 + 2", "import os", "",
    "1.5 + 2,25", "12.5 + 1.000,00", "1.250,50 + 2,500.00", "1.250,50 + 3,000,000",  # mixed styles
])
def test_refuses_rather_than_guesses(expression):
    with pytest.raises(CalcError):
        evaluate(expression)


def test_rewrite_replaces_marker_and_checks_figures_against_sources():
    text, calcs = rewrite("Totaal: [[calc: 6.507,11 + 6.417,42]] EUR [1][2].", SOURCE)
    assert text == "Totaal: 6.507,11 + 6.417,42 = 12.924,53 EUR [1][2]."
    assert calcs[0].result == "12.924,53" and calcs[0].figures_not_in_sources == []
    _, calcs = rewrite("[[calc: 6.507,11 + 999,99]]", SOURCE)
    assert calcs[0].figures_not_in_sources == ["999,99"]
    _, calcs = rewrite("[[calc: 2.500,00 + 1]]", "Prijs: 12.500,00 EUR, 1 perceel")
    assert calcs[0].figures_not_in_sources == ["2.500,00"]  # part of a longer number is not a match
    _, calcs = rewrite("[[calc: 6.507,11 + 6.417,42]]", SOURCE, cited_sources=["Nettobedrag: + 6.507,11 EUR"])
    assert calcs[0].figures_not_in_sources == ["6.417,42"]  # only the cited passages count


def test_share_as_percentage_is_exact_and_100_is_not_a_missing_figure():
    text, calcs = rewrite("Aandeel: [[calc: 6.507,11 / (6.507,11 + 6.417,42) * 100]] % [1][2].", SOURCE)
    assert calcs[0].result == "50,35" and calcs[0].error is None
    assert calcs[0].figures_not_in_sources == []
    _, calcs = rewrite("[[calc: 6.507,11 / 200]]", SOURCE)
    assert calcs[0].figures_not_in_sources == ["200"]  # only the percentage factor is exempt


def test_whole_number_division_uses_the_sources_decimal_separator():
    assert rewrite("[[calc: 1250 / 3]]", SOURCE)[0] == "1250 / 3 = 416,67"


def test_failed_calculation_is_visible_not_silent():
    text, calcs = rewrite("[[calc: 1.250 + 3.000]]", SOURCE)
    assert text == "[calculation not possible: 1.250 + 3.000]"
    assert calcs[0].result is None and calcs[0].error


def test_streaming_marker_split_across_chunks_and_citations_untouched():
    r = CalcRewriter(SOURCE)
    pieces = ["Totaal [1", "] is [", "[cal", "c: 6.507,11 + 6.", "417,42]", "] EUR [2]."]
    out = "".join(r.feed(p) for p in pieces) + r.flush()
    assert out == "Totaal [1] is 6.507,11 + 6.417,42 = 12.924,53 EUR [2]."


def test_brackets_closed_far_away_are_not_a_marker():
    text = "a [[ " + "x" * 400 + " ]] b"
    assert rewrite(text, SOURCE)[0] == text


def test_unclosed_brackets_are_released():
    r = CalcRewriter(SOURCE)
    out = r.feed("a [[ b " + "x" * 400) + r.flush()
    assert out == "a [[ b " + "x" * 400 and r.calculations == []


DEED = "Kavel 1: 200.000,00 EUR. Kavel 2: 150.000,00 EUR. Verleden op 21.01.2026, artikel 3.2."


@pytest.mark.parametrize("answer, flagged", [
    ("Samen 350.000,00 EUR.", ["350.000,00"]),                       # worked out by the model itself
    ("Kavel 1 is 200.000 EUR [1].", []),                             # same value as the passage's 200.000,00
    ("Verleden op 21.01.2026, kavel 2, pagina 57, 3 kavels.", []),   # dates and small plain numbers aren't amounts
    ("Artikel 3.2 [1].", []),                                        # as written in the passage
    ("Ongeveer 12,5 % en 1.234.567 EUR.", ["12,5", "1.234.567"]),
    ("Twee keer 350.000,00 en nog eens 350.000,00.", ["350.000,00"]),  # once each
    ("Referentie 4182957.", ["4182957"]),                            # five digits or more are checked
])
def test_unverified_figures_in_the_answer_text(answer, flagged):
    assert unverified_figures(answer, [], DEED) == flagged


def test_system_calculations_and_the_users_own_figures_are_not_flagged():
    r = CalcRewriter(DEED)
    text = r.feed("Samen [[calc: 200.000,00 + 150.000,00]] EUR; dus 350.000,00 EUR in totaal.") + r.flush()
    assert unverified_figures(text, r.calculations, DEED) == []
    assert unverified_figures("Nee, 410.000 staat niet in de akte.", [], DEED, asked="Is het 410.000?") == []
