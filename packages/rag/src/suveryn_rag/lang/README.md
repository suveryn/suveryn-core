# The words of each language the rag reads

One file per language of `suveryn_playbooks.LANGUAGES`, loaded with the harness's `language.load` by
[`naming.py`](../naming.py) and [`integrity.py`](../integrity.py), read together: a question in Dutch can name a French
document. No word of a language is in the rag's code ([docs/translations.md](../../../../../docs/translations.md));
`harness/tests/test_language.py` fails on a language without its file, a file without one of the lists, or a Dutch
or French word in the code. Words are lower case and without accents (the code folds what it compares). A native
speaker reviews each file.

| List | For |
|---|---|
| `document_kinds` | Kind of document -> how a question names it ("de Franstalige *volmacht*"): nouns for the document itself only |
| `file_words` | Kind of document -> a topic word that names such a file ("Uitgifte_2150512.pdf") |
| `language_names` | Language -> how this language calls it in a question ("Franstalige", "en français") |
| `file_markers` | The codes that mark a file name as this language's ("Akte (FR).pdf", "Akte-ned.pdf"); codes, not words |
| `common_words` | Short words common in this language's text, to tell which language a document is in |
| `search_stop_words` | Words of a question that are no search term |
| `page_words`, `page_of` | A page number standing alone: "blz. 4 van 9", "page 2 sur 5" |

Which kinds of document there are is the notarial practice's, for now; when a second profession needs its own, the
kinds may move to the packs.
