# The words the gateway writes itself

One file per language of `suveryn_playbooks.LANGUAGES`, loaded with the harness's `language.load` by
[`playbooks.py`](../playbooks.py) for the summary a playbook run stores in the case, in the run's language. A
playbook's own words (title, labels, questions, what a check says) are its pack's (`text/<lang>.json`); these are the
words every summary shares. No word of a language is in the gateway's code
([docs/translations.md](../../../../../docs/translations.md)); `harness/tests/test_language.py` fails on a missing file,
a missing word, or a Dutch or French word in the code. A native speaker reviews each file.

| Key | For |
|---|---|
| `check_holds`, `check_fails`, `check_open` | A check's result after what it says: "klopt", "klopt niet", "niet nagekeken" |
| `read_in_part` | The line naming the documents read in part, not every page |
| `page` | Before a cited page: "p. 3" |

The chat UI shows a check's result in its own words (`src/i18n`); the two are kept the same by hand.
