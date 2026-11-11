# The words of each language the harness reads in documents

One pair of files per language of `suveryn_playbooks.LANGUAGES`, loaded by [`language.py`](../language.py). No word
of a language is in the harness's code ([docs/translations.md](../../../../../docs/translations.md));
`tests/test_language.py` fails on a language without its files, a file without one of the lists, or a Dutch or
French word in the code.

| File | What | Written by |
|---|---|---|
| `<lang>.numbers.json` | Every number under a thousand as written, the words a number is written with, the words for a hundred, a thousand, a million and a milliard, the months' names full and short, and as a date is written out | [`tools/number_words.py`](../../../tools/number_words.py); never by hand |
| `<lang>.json` | What no standard holds, below | By hand; a native speaker reviews it |

Words are lower case. A phrase's space matches any white space. Lists hold words and phrases, never patterns: the
code makes its patterns from them. Where the reader folds text before comparing (number and term words), a word is
written without accents.

## The lists of `<lang>.json`

| List | For |
|---|---|
| `joins` | The word between the parts of a number: "vingt et un" |
| `one` | "One" before a unit, which alone is an article and no count |
| `articles` | The articles: a capitalised word after one is a contract's defined term, not a name |
| `ordinals`, `ordinal_endings`, `ordinal_word_endings` | A day written as an ordinal: the word, the ending after a figure, the ending of a number word |
| `no_number_after` | A number word that is no number after another word |
| `number_only_near` | A number word that is another language's ordinary word: a number only near these words of its own language |
| `figure_scales` | A scale word or its short form after a figure: "1,2 million" |
| `currencies`, `areas`, `percent`, `approximately` | What a number measures, and that it isn't exact, in words (signs and codes are in the code: they are no language's) |
| `time_units` | The unit of a term, also what a number of days, weeks, months or years measures |
| `term_before`, `term_after`, `term_after_right_behind` | What makes a period a term before or after an event |
| `working_after`, `working_before` | The word that makes days working days |
| `abbreviations` | Abbreviations whose full stop ends no sentence |
| `stop_words` | Words that say nothing about which sentence a claim rests on |
| `name_particles` | Lower-case words inside a name |
| `not_found`, `not_known_yet` | How the model or a person says a value is absent, or not known yet |
| `ai_*` | Text in a document that addresses an AI (`guard.py`): the words of "ignore the previous instructions", a change of role, an address, a role header |
| `formal_address` | The line of the prompt that says how this language addresses a person formally |

The languages are read together, because one file mixes them; a word that means two different things in two
languages stops the harness from loading.
