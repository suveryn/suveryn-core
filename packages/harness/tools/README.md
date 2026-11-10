# Tools for a developer

Nothing here runs on an appliance or is imported by the harness.

| Tool | What it does |
|---|---|
| `number_words.py` | Writes the number words and month names the reader knows, one file per language (`src/suveryn_harness/lang/<lang>.numbers.json`), from the standard spelling rules (num2words, Unicode CLDR), and the numbers the reader is tested on (`tests/spelled_numbers.json`). Run it when a language is added or a notarial spelling must be read: `uvx --with-requirements packages/harness/tools/requirements.txt python packages/harness/tools/number_words.py`. `--check` fails when the files differ from what it would write. |

`requirements.txt` pins the libraries to exact versions. Why the words are generated and not typed:
[docs/harness.md](../../../docs/harness.md), *The languages the reader knows*.
