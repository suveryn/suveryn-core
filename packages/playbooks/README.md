# playbooks

The official playbooks as **manifest files**, and the loader that reads them. A playbook says what
it asks for and tells the model, and carries its identity (id, pack, version). No runtime lives
here: the gateway runs them (`suveryn_api_gateway.playbooks`). Design:
[docs/design/playbooks.md](../../docs/design/playbooks.md); the format: [Writing a playbook](https://github.com/suveryn/suveryn-docs/blob/main/playbooks/writing-a-playbook.md).

| Playbook | Id | Pack |
|---|---|---|
| Deed intake (sale): asks for the agreement, reads the documents (the parties and the conditions as lists), asks about what it couldn't find, five checks, a person confirms, the summary. Its version and steps: [`deed-intake.yaml`](src/suveryn_playbooks/be_notary/deed-intake.yaml) | `playbook/be-notary/deed-intake` | `pack/be-notary` |

Deed intake is the one public reference playbook. The certified content (`pack/be-notary`: company
formation, the deed of incorporation of a BV, first) lives in the private `suveryn-packs` repository
and is loaded from the packs directory an appliance has installed (`packs.py`, `SUVERYN_PACKS_DIR`),
with the same loader and the same validation; `python -m suveryn_playbooks <dir>` checks a directory.
Core's tests run on a fictional test pack (`tests/fixtures/packs/be-test`, installed by the
repository's `conftest.py`) that uses what company formation uses of the format.

The identifiers are the ones the platform note chose; they end up in the registry, the licence and
the invoice, so they never change. `covered(playbook_id)` is the one place the licence check will
land: whether a playbook is certified and listed in the appliance's manifest. An uncovered playbook
still runs, with a warning to everyone (the licensing model warns, never blocks); today every
official playbook is covered.

Editors can validate against `schema/playbook-manifest.schema.json`
(regenerate it with `python -m suveryn_playbooks.manifest` after changing `manifest.py`; a test
checks they agree).

What is here:

| Path | Contents |
|---|---|
| `src/suveryn_playbooks/__init__.py` | `PLAYBOOKS`, every manifest in the official packs and the installed packs directory, loaded at import; `covered`, `find`, `by_slug` and `for_case_type`; `LANGUAGES`, the interface languages |
| `src/suveryn_playbooks/packs.py`, `__main__.py` | Packs from a directory (`SUVERYN_PACKS_DIR`): the certified content an appliance has installed; `python -m suveryn_playbooks <dir>` checks one |
| `src/suveryn_playbooks/_model.py` | `Playbook`, `Fact`, `Step` and `Wording`: a playbook as the product sees it |
| `src/suveryn_playbooks/manifest.py` | The manifest format (`Manifest`, validated strictly; `validate_steps` for the graph), `parse`, `load`, the table scaffold and the JSON Schema |
| `src/suveryn_playbooks/paths.py` | Paths into a list's values (`founders[2].name`): split, root, entry |
| `src/suveryn_playbooks/be_notary/deed-intake.yaml` | Deed intake: its facts (three of them lists; two dates that count from the agreement's date when written as a term), the instructions the model gets, the case type it fits, its steps and its version |
| `src/suveryn_playbooks/record.py` | A playbook as a record and back: what a run keeps (``playbook_runs.manifest``) |
| `src/suveryn_playbooks/rules.py` | A check's rule: one comparison, parsed and checked against the facts; the harness evaluates it |
| `src/suveryn_playbooks/conditions.py` | A step's `when`: one condition on a choice fact; the runtime evaluates it when the step is reached |
| `src/suveryn_playbooks/be_notary/text/<lang>.json` | Each playbook's title, summary, fact labels and questions in English, Dutch and French |
| `schema/playbook-manifest.schema.json` | The format as JSON Schema, generated from `manifest.py` |
| `tests/fixtures/packs/be-test/` | The fictional test pack: a formation playbook with fewer facts, for the tests of lists, choices, documents by name, checks and the manager's checkpoint |
| `tests/test_content.py` | The identities, the case types, and that every playbook has its words and its questions in each language |
| `tests/test_manifest.py` | The loader: deed intake today reads what 1.0 did (`fixtures/`), the steps and their graph, format 3's lists, numbers and paths, what is refused and how it says so, the schema in sync |
