"""Each language sūveryn speaks has its files of words the harness reads in documents (docs/translations.md:
one list of languages, one file per language per place, a test that fails when one is missing)."""
from pathlib import Path

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


def test_every_language_has_the_same_lists():
    """The words by hand: every language's file has every list, so a new language's file can't miss one."""
    assert set(language.WORDS) == set(LANGUAGES)
    keys = {lang: set(t) for lang, t in language.WORDS.items()}
    assert all(k == keys["en"] for k in keys.values()), keys
    for name in ("joins", "one", "percent", "approximately", "time_units", "term_before", "term_after", "stop_words",
                 "abbreviations", "not_found", "not_known_yet", "ai_ignore", "ai_previous", "ai_instructions"):
        assert all(t[name] for t in language.WORDS.values()), name


def _tokens(text: str) -> set[str]:
    import re

    from suveryn_harness.values import fold
    return {fold(w) for w in re.findall(r"[^\W\d_]{3,}", text)}


# Every package that holds words of a language keeps them in ``lang/<lang>.json`` of its own (docs/translations.md):
# the harness, the rag, the gateway. The chat UI's words are its tables (src/i18n), checked by its own tests.
PACKAGES = Path(__file__).resolve().parents[2]
LANG_DIRS = sorted(PACKAGES.glob("*/src/*/lang"))
# Lists that are not a language's words: an English instruction quoting them, a file name's language codes.
NOT_WORDS = {"formal_address", "file_markers"}


def test_every_package_has_every_language_with_the_same_lists():
    """A package's word files: one per language, each with the lists of the others, so a new language can't miss
    one."""
    assert {d.parent.name for d in LANG_DIRS} >= {"suveryn_harness", "suveryn_rag", "suveryn_api_gateway"}
    for directory in LANG_DIRS:
        tables = language.load(directory)
        keys = {lang: set(t) for lang, t in tables.items()}
        assert all(k == keys["en"] for k in keys.values()), (directory, keys)


def _words_of(lang: str) -> set[str]:
    out: set[str] = set()

    def take(value):
        if isinstance(value, str):
            out.update(_tokens(value))
        elif isinstance(value, dict):
            for k, v in value.items():
                take(k)
                take(v)
        elif isinstance(value, list):
            for v in value:
                take(v)
    for directory in LANG_DIRS:
        table = language.load(directory)[lang]
        take({k: v for k, v in table.items() if not k.startswith("_") and k not in NOT_WORDS})
    numbers = language.NUMBER_WORDS[lang]
    take([numbers["months_written"], list(numbers["months"]), list(numbers["scales"]), list(numbers["parts"])])
    out.update(w for w in numbers["numbers"] if len(w) >= 3)
    return out


# Words of Dutch or French that are also English, or the code's own: what a word list can't tell apart.
ALSO_CODE = {"day", "week", "month", "year", "workday", "eur", "usd", "gbp", "later", "exact"}


def test_no_word_of_a_language_is_in_the_code():
    """Code is English; a language's words are in its files only (docs/translations.md, principles 5 and 6). Every
    text the code of every Python package holds (not its comments or docstrings, which may quote an example) is read
    for a Dutch or French word of the languages' files that isn't English too. The chat UI has the same test
    (src/i18n/words-in-code.test.ts)."""
    import ast

    foreign = (_words_of("nl") | _words_of("fr")) - _words_of("en") - ALSO_CODE
    found = {}
    for path in sorted(PACKAGES.glob("*/src/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        hits = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                hits |= _tokens(node.value) & foreign
        if hits:
            found[str(path.relative_to(PACKAGES))] = sorted(hits)
    assert found == {}
