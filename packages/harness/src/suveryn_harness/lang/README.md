# The words of each language the harness reads in documents

One file per language of `suveryn_playbooks.LANGUAGES`, loaded by [`language.py`](../language.py). No word of a
language is in the harness's code ([docs/translations.md](../../../../../docs/translations.md)).

| File | What | Written by |
|---|---|---|
| `<lang>.numbers.json` | Every number under a thousand as written, the words a number is written with, the words for a hundred, a thousand, a million and a milliard, the months' names full and short | [`tools/number_words.py`](../../../tools/number_words.py); never by hand |

Keys are folded as the reader folds a word (lower case, no accents), without spaces and hyphens. The languages are
read together, because one file mixes them; a word that means two different numbers in two languages stops the
harness from loading. A test fails when a language has no file (`tests/test_language.py`).
