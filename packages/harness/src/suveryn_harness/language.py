"""The words of each language the harness reads in documents: one file per language in ``lang/``, none in the code
(docs/translations.md). The languages are those sūveryn speaks (``suveryn_playbooks.LANGUAGES``), read together:
a deed in Dutch can quote a clause in French, and a question in English can be about either.

``<lang>.numbers.json`` is generated from the standard spelling rules (``tools/number_words.py``), never edited.
"""
from __future__ import annotations

import json
from pathlib import Path

from suveryn_playbooks import LANGUAGES

DIR = Path(__file__).parent / "lang"


def _load(suffix: str) -> dict[str, dict]:
    return {lang: json.loads((DIR / f"{lang}{suffix}").read_text(encoding="utf-8")) for lang in LANGUAGES}


def together(tables: dict[str, dict], name: str) -> dict[str, int]:
    """One table of every language's entries under ``name``. A word that means two things stops the load: the
    languages are read together, so it would be read as either."""
    out: dict[str, int] = {}
    for lang, table in tables.items():
        for word, value in table[name].items():
            if out.setdefault(word, value) != value:
                raise ValueError(f"{word!r} ({lang}, {name}) means {value} and {out[word]}")
    return out


NUMBER_WORDS = _load(".numbers.json")
