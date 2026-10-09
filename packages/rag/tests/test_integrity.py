"""Integrity rules (pure functions, no GPU or database)."""

import pytest

pytest.importorskip("suveryn_rag")
from suveryn_rag.integrity import (
    is_page_number,
    lines_with,
    missing_words,
    page_coverage,
    query_terms,
    split_furniture,
    words,
)


@pytest.mark.parametrize("text", ["3", " 12 ", "Pagina 3", "pagina 3 van 8", "Page 2 of 5", "p. 4", "- 7 -", "3/8"])
def test_page_numbers(text):
    assert is_page_number(text)


@pytest.mark.parametrize("text", ["49.118 12.095 54.107 89.016 100%", "Voor eensluidend afschrift", "Artikel 3"])
def test_not_page_numbers(text):
    assert not is_page_number(text)


def test_furniture_drops_only_what_repeats():
    furniture = [(p, "AKTE VAN LEVERING · Kenmerk TST/2026/001") for p in range(1, 7)]
    furniture += [(p, f"Pagina {p} van 6") for p in range(1, 7)]
    furniture += [(4, "Totaal ten laste van koper: EUR 425.986,35")]  # content mislabelled as a footer
    dropped, restored = split_furniture(furniture, n_pages=6)
    assert restored == [(4, "Totaal ten laste van koper: EUR 425.986,35")]
    assert len(dropped) == 12


def test_furniture_single_page_keeps_non_numbers():
    dropped, restored = split_furniture([(1, "1"), (1, "Kantoor Notaris X")], n_pages=1)
    assert dropped == [(1, "1")] and restored == [(1, "Kantoor Notaris X")]


def test_words_joins_hyphenation_and_normalises():
    assert words("eigendoms-\noverdracht — Sectie K‚ nummer 4182") == {"eigendomsoverdracht", "sectie", "nummer", "4182"}


def test_page_coverage_flags_missing_text_only():
    pages = ["Artikel 1 De koopprijs bedraagt EUR 412.500,00 voor het woonhuis.",
             "Artikel 2 Voor eensluidend afschrift getekend door de notaris te Gent op heden.\n2"]
    chunks = [(1, 1, "De koopprijs bedraagt EUR 412.500,00 voor het woonhuis. Artikel 1")]
    w = page_coverage(pages, chunks, dropped=[(2, "2")])
    assert [(x.page, x.kind, x.needs_review) for x in w] == [(2, "page_coverage_low", True)]
    chunks.append((2, 2, "Artikel 2 Voor eensluidend afschrift getekend door de notaris te Gent op heden."))
    assert page_coverage(pages, chunks, dropped=[(2, "2")]) == []


def test_query_terms_drop_stopwords_keep_numbers():
    assert query_terms("Welke huurder heeft een huurachterstand?") == ["huurder", "huurachterstand"]
    assert query_terms("Van welk artikel wordt afgeweken, 1563?") == ["artikel", "afgeweken", "1563"]
    assert query_terms("What is the maximum pre-money valuation?") == ["maximum", "pre", "money", "valuation"]


def test_lines_with_recovers_only_lines_holding_missing_words():
    page = "Rekeningoverzicht\nRekeninghouder  Jansens Pieter\nPeriode 01/09 - 30/09\nSaldo EUR 1.234,56\nPeriode 01/09 - 30/09"
    missing = {"jansens", "pieter", "periode"}
    assert lines_with(page, missing) == "Rekeninghouder  Jansens Pieter\nPeriode 01/09 - 30/09"


def test_missing_words_feeds_recovery_and_coverage():
    pages = ["Tabel Rekeninghouder Jansens Pieter Periode september Saldo positief"]
    stored = [(1, 1, "Tabel Saldo positief")]
    ref, missing = missing_words(pages, stored, dropped=[])[1]
    assert missing == {"rekeninghouder", "jansens", "pieter", "periode", "september"}
    recovered = lines_with(pages[0], missing)
    assert page_coverage(pages, stored + [(1, 1, recovered)], dropped=[]) == []
