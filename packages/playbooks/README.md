# playbooks

The official playbooks as **manifest files**, and the loader that reads them. A playbook says what
it asks for and tells the model, and carries its identity (id, pack, version). No runtime lives
here: the gateway runs them (`suveryn_api_gateway.playbooks`). Design:
[docs/design/playbooks.md](../../docs/design/playbooks.md), "The manifest".

| Playbook | Id | Pack | Version |
|---|---|---|---|
| Deed intake (sale): the facts a deed needs, read from the case's documents and checked by a person | `playbook/be-notary/deed-intake` | `pack/be-notary` | 1.0 |

The identifiers are the ones the platform note chose; they end up in the registry, the licence and
the invoice, so they never change. `covered(playbook_id)` is the one place the licence check will
land: whether a playbook is certified and listed in the appliance's manifest. An uncovered playbook
still runs, with a warning to everyone (the licensing model warns, never blocks); today every
official playbook is covered.

A manifest (format 1) is a YAML file with the identity, the case types it fits, its facts (id,
what to ask, kind: text, amount or date) and the instructions the model gets. The table the model
fills in is the runtime's, appended by the loader; the wording per language is the pack's, in
`text/<lang>.json` beside the file. Unknown keys and malformed values are refused with the file
and field named. Editors can validate against `schema/playbook-manifest.schema.json`
(regenerate it with `python -m suveryn_playbooks.manifest` after changing `manifest.py`; a test
checks they agree).

What is here:

| Path | Contents |
|---|---|
| `src/suveryn_playbooks/__init__.py` | `PLAYBOOKS`, every manifest in the official packs, loaded at import; `covered`, `find`, `by_slug` and `for_case_type`; `LANGUAGES`, the interface languages |
| `src/suveryn_playbooks/_model.py` | `Playbook`, `Fact` and `Wording`: a playbook as the product sees it |
| `src/suveryn_playbooks/manifest.py` | The manifest format (`Manifest`, validated strictly), `parse`, `load`, the table scaffold and the JSON Schema |
| `src/suveryn_playbooks/be_notary/deed-intake.yaml` | Deed intake: its thirteen facts, the instructions the model gets and the case type it fits |
| `src/suveryn_playbooks/be_notary/text/<lang>.json` | Each playbook's title, summary and fact labels in English, Dutch and French |
| `schema/playbook-manifest.schema.json` | Format 1 as JSON Schema, generated from `manifest.py` |
| `tests/test_content.py` | The identities, the case types, and that every playbook has its words in each language |
| `tests/test_manifest.py` | The loader: deed intake as a manifest equals the code it replaced (`fixtures/`), what is refused and how it says so, the schema in sync |
