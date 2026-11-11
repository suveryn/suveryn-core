"""Each language sūveryn speaks has its files of words the harness reads in documents (docs/translations.md:
one list of languages, one file per language per place, a test that fails when one is missing)."""
from suveryn_playbooks import LANGUAGES

from suveryn_harness import language


def test_every_language_has_its_number_words():
    assert set(language.NUMBER_WORDS) == set(LANGUAGES)
    for lang, table in language.NUMBER_WORDS.items():
        assert {"numbers", "parts", "scales", "months"} <= set(table), lang
        assert len(table["numbers"]) >= 1000 and len(set(table["months"].values())) == 12, lang
        assert {100, 1000, 10**6, 10**9} <= set(table["scales"].values()), lang


def test_a_word_that_means_two_numbers_stops_the_load():
    import pytest
    with pytest.raises(ValueError):
        language.together({"a": {"n": {"elf": 11}}, "b": {"n": {"elf": 12}}}, "n")
