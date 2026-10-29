# playbooks

The official playbooks, hand-built: what each one asks for and says to the model, and its identity
(id, pack, version). No runtime lives here: the gateway runs them (`suveryn_api_gateway.playbooks`),
and the runtime, manifest and pack format are extracted later from what the first three playbooks
needed (docs/design/platform.md, "Sequencing"). Design: [docs/design/playbooks.md](../../docs/design/playbooks.md).

| Playbook | Id | Pack | Version |
|---|---|---|---|
| Deed intake (sale): the facts a deed needs, read from the case's documents and checked by a person | `playbook/be-notary/deed-intake` | `pack/be-notary` | 1.0 |

The identifiers are the ones the platform note chose; they end up in the registry, the licence and
the invoice, so they never change. `covered(playbook_id)` is the one place the licence check will
land: whether a playbook is certified and listed in the appliance's manifest. An uncovered playbook
still runs, with a warning to everyone (the licensing model warns, never blocks); today every
official playbook is covered.

What is here:

| Path | Contents |
|---|---|
| `src/suveryn_playbooks/__init__.py` | `Playbook`, `Fact` and `Wording`; `covered`, `find`, `by_slug` and `for_case_type`; `LANGUAGES`, the interface languages |
| `src/suveryn_playbooks/be_notary/deed_intake.py` | Deed intake: its thirteen facts, the instructions the model gets and the case type it fits |
| `src/suveryn_playbooks/be_notary/text/<lang>.json` | Each playbook's title, summary and fact labels in English, Dutch and French |
| `tests/test_content.py` | The identities, the case types, and that every playbook has its words in each language |
| `schema/` | Empty: the manifest schema joins when the runtime is extracted |
