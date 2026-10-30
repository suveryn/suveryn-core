# playbooks

The official playbooks as **manifest files**, and the loader that reads them. A playbook says what
it asks for and tells the model, and carries its identity (id, pack, version). No runtime lives
here: the gateway runs them (`suveryn_api_gateway.playbooks`). Design:
[docs/design/playbooks.md](../../docs/design/playbooks.md), "The manifest".

| Playbook | Id | Pack | Version |
|---|---|---|---|
| Deed intake (sale): asks for the agreement, reads the documents, asks about what it couldn't find, a person confirms, the summary | `playbook/be-notary/deed-intake` | `pack/be-notary` | 1.1 |

The identifiers are the ones the platform note chose; they end up in the registry, the licence and
the invoice, so they never change. `covered(playbook_id)` is the one place the licence check will
land: whether a playbook is certified and listed in the appliance's manifest. An uncovered playbook
still runs, with a warning to everyone (the licensing model warns, never blocks); today every
official playbook is covered.

A manifest is a YAML file with the identity, the case types it fits, its facts (id, what to ask,
kind: text, amount or date), the instructions the model gets and the routine's
`steps` (`request`, `read`, `ask`, `checkpoint`, `produce`, each with `needs`); `manifest: 2`, the one
format the loader reads. The table the model fills in is the runtime's,
appended by the loader; the wording per language is the pack's, in `text/<lang>.json` beside the
file: title, summary, a label per fact, and the questions the routine puts to people (by step id,
with `{label}` in an ask's template, or by `step.fact`). Unknown keys, malformed values and a wrong
graph (a circle, a produce before any checkpoint, an ask about a fact no read reads) are refused
with the file and the step or field named. The runtime that walks the steps is the gateway's
(`suveryn_api_gateway.playbook_runtime`). Editors can validate against `schema/playbook-manifest.schema.json`
(regenerate it with `python -m suveryn_playbooks.manifest` after changing `manifest.py`; a test
checks they agree).

What is here:

| Path | Contents |
|---|---|
| `src/suveryn_playbooks/__init__.py` | `PLAYBOOKS`, every manifest in the official packs, loaded at import; `covered`, `find`, `by_slug` and `for_case_type`; `LANGUAGES`, the interface languages |
| `src/suveryn_playbooks/_model.py` | `Playbook`, `Fact`, `Step` and `Wording`: a playbook as the product sees it |
| `src/suveryn_playbooks/manifest.py` | The manifest formats 1 and 2 (`Manifest`, validated strictly; `validate_steps` for the graph), `parse`, `load`, the table scaffold and the JSON Schema |
| `src/suveryn_playbooks/be_notary/deed-intake.yaml` | Deed intake 1.1: its thirteen facts, the instructions the model gets, the case type it fits and its five steps |
| `src/suveryn_playbooks/be_notary/text/<lang>.json` | Each playbook's title, summary, fact labels and questions in English, Dutch and French |
| `schema/playbook-manifest.schema.json` | The format as JSON Schema, generated from `manifest.py` |
| `tests/test_content.py` | The identities, the case types, and that every playbook has its words and its questions in each language |
| `tests/test_manifest.py` | The loader: deed intake 1.1 reads and asks what 1.0 did (`fixtures/`), the steps and their graph, what is refused and how it says so, the schema in sync |
