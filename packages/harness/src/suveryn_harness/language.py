"""The words of each language the harness reads in documents: one file per language in ``lang/``, none in the code
(docs/translations.md). The languages are those sūveryn speaks (``suveryn_playbooks.LANGUAGES``), read together:
a deed in Dutch can quote a clause in French, and a question in English can be about either.

``<lang>.numbers.json`` is generated from the standard spelling rules (``tools/number_words.py``), never edited.
``<lang>.json`` is written by hand, lists of words and phrases a translator can read: no patterns. The code above
this module makes its patterns from them (``any_of``). ``lang/README.md`` says what each list is for.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from suveryn_playbooks import LANGUAGES

DIR = Path(__file__).parent / "lang"


def _load(suffix: str) -> dict[str, dict]:
    return {lang: json.loads((DIR / f"{lang}{suffix}").read_text(encoding="utf-8")) for lang in LANGUAGES}


def together(tables: dict[str, dict], name: str) -> dict:
    """One table of every language's entries under ``name``. A word that means two things stops the load: the
    languages are read together, so it would be read as either."""
    out: dict = {}
    for lang, table in tables.items():
        for word, value in table[name].items():
            if out.setdefault(word, value) != value:
                raise ValueError(f"{word!r} ({lang}, {name}) means {value} and {out[word]}")
    return out


NUMBER_WORDS = _load(".numbers.json")
WORDS = _load(".json")


def words(name: str) -> list[str]:
    """Every language's words or phrases under ``name``, each once."""
    return list(dict.fromkeys(w for table in WORDS.values() for w in table[name]))


def table(name: str) -> dict:
    """Every language's entries under ``name`` as one table."""
    return together(WORDS, name)


def languages_of(name: str, word: str) -> list[str]:
    """The languages whose list or table ``name`` holds ``word``."""
    return [lang for lang, t in WORDS.items() if word in t[name]]


def any_of(phrases, space: str = r"\s+") -> str:
    """A pattern that matches any of the phrases, the longest first; a space in a phrase matches ``space``."""
    longest_first = sorted(dict.fromkeys(phrases), key=len, reverse=True)
    return "(?:" + "|".join(space.join(re.escape(part) for part in p.split(" ")) for p in longest_first) + ")"
