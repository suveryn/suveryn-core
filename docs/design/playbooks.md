# Playbooks: deed intake first, hand-built (suveryn-tracker#51)

A design note, October 2026, for the first playbook. The platform note ([platform.md](platform.md))
decided the order: three hand-built notary playbooks, plain and hard-coded, before any runtime, SDK
or registry; the runtime, the manifest and the pack format are extracted afterwards from what the
three needed. This note says what the first one, deed intake, is, what it leaves behind in the
case, and the few things that are settled now because they would be expensive to retrofit. It
replaces the earlier bot-written tickets (#27 facts layer, #28 runner, #29 templates) as the plan:
what they asked for appears here where the first playbook actually needs it, and not before.

## What deed intake does

A notary opens a sale case and uploads what the parties sent: the signed private sale agreement
(compromis), the earlier title deed, the energy and soil certificates, an identity document or two.
Before anyone drafts the deed, someone reads all of it and writes down the facts the deed will need.
Deed intake does that reading and leaves the writing-down to be checked:

1. The contributor starts the playbook in the case, choosing which of the case's uploaded documents
   it reads (all of them by default).
2. Sūveryn asks the model, grounded in those documents exactly as a chat question is, for a fixed
   list of facts: the parties, the property, the price and what was paid, the dates, the
   conditions, the certificates. Every fact must cite the passage it comes from; the server
   checks each cited figure, date and name against that passage with the same rule-based check
   as a chat answer (`suveryn_harness.support`; the table is read by `suveryn_harness.facts`), and a fact the model couldn't find is left empty,
   never guessed.
3. The **checkpoint**: the facts are shown next to their passages, one by one, each with its
   source page and the check's verdict. The notary confirms, corrects or clears each one. Nothing
   is final until a person has looked at every fact.
4. On confirmation, the intake summary is written into the case as a document with origin
   `playbook`, and can be downloaded as a Word file. The run is kept as a record: who started it,
   when, from which documents, which facts, as read and as confirmed, by whom.

The playbook's facts for a Belgian sale (the fields are the playbook's; the vocabulary in three
languages is the chat UI's):

| Id | What | Kind |
|---|---|---|
| `sellers` | The selling party or parties, as named in the agreement | text |
| `buyers` | The buying party or parties | text |
| `property` | The property: address and description | text |
| `cadastral` | The cadastral identification (division, section, number) | text |
| `price` | The sale price | amount |
| `deposit` | The advance or guarantee paid at signing, and to whom | amount |
| `agreement_date` | The date the private agreement was signed | date |
| `deed_deadline` | The date by which the notarial deed must be signed | date |
| `conditions` | Suspensive conditions (financing, permits), with their terms | text |
| `title` | The seller's title: the earlier deed, its date and notary | text |
| `epc` | The energy performance certificate: reference and result | text |
| `soil` | The soil certificate: reference and conclusion | text |
| `occupancy` | Occupancy at delivery: free, let, or occupied, and by whom | text |

Thirteen facts. Not more, because every fact is a line the notary has to check, and the three
playbooks together are supposed to show what a fact is before a facts layer is designed around it.

## What is settled now, and why

**Identity.** Every playbook declares, in its manifest, its **id**, its **pack** and its **version**:
`playbook/be-notary/deed-intake`, `pack/be-notary`, `1.0`. The identifiers are the ones the
platform note and the commercial model chose, because they end up in the registry, the licence
and the invoice; a bundle later is a catalogue entry naming playbook ids with version ranges, which
only works if the ids never change. The version is separate from the id and semantic in the loose
sense: a change to the facts list or the prompt that changes results is a new minor version; a
change that would make an old run unreadable is a new major one.

**Provenance.** The run record and every document a playbook produces carry `playbook_id` and
`playbook_version`. A notary, an insurer or a court will one day ask which version of what read a
given file; that is a liability question before it is a commercial one, and it can't be answered
after the fact.

**Coverage, never a block.** One function, `covered(playbook_id)`, says whether a playbook is
certified and listed in the appliance's manifest (the licensing model, development context §8,
suveryn-tracker#35). The API reports it (`covered` on `GET …/playbooks`) and the UI shows a warning
when it is false; the run starts regardless, because the licensing model warns and never blocks: a
notary's work never stops because of an invoice. Today it always answers yes. It is the single
place the licence check lands, so activation never has to be threaded through the code afterwards.
No manifest, catalogue or pack format is built now: those are extracted from the three playbooks,
as the platform note says. (An earlier draft of this note and of the commercial model said an
uncovered playbook doesn't start; §8 is the decision, and this note follows it.)

**The case is the container.** As cases.md decided (decision 9), the playbook's state lives in its
**run**, keyed by `case_id`; the case itself stays open or closed. A closed case can't start a run
(decision 10). Starting a run is a contributor's right; confirming the checkpoint too; a reader
sees results (cases.md, roles). Every step is in the case's access log.

**Only uploaded documents are sources** (decision 7): a run reads documents with origin `uploaded`,
never an earlier run's summary, so the AI never cites its own output as evidence.

**The result is a document in the case** with origin `playbook`, stored through the same store as
uploads (text, chunks, embeddings, so it is listed, searchable and deleted with the case), but
never a source. Its file name is the playbook's name and the case reference. Deleting a document
that a run read marks the run `out_of_date` (cases.md); the run is not deleted, because the
confirmed facts and who confirmed them are the record.

## The data model

```
playbook_runs   id, case_id, playbook_id, playbook_version, status, documents uuid[],
                started_by, started_at, finished_at, confirmed_by, confirmed_at,
                facts jsonb, model, error, result_document_id, out_of_date bool
```

`status` is `reading` (the model is working), `checkpoint` (waiting for a person), `confirmed`,
or `failed` (with `error`: a kind, never text). `facts` is a list, one entry per field, in the
playbook's order:

```
{ id, value, citations: [{n, document_id, filename, page, location, text}],
  issues: [item, ...],            the check: figures, dates or names not in the cited passage
  confirmed: null | string,       what the person confirmed (the value, a correction, or "")
  found: bool }                   false: the model said the documents don't contain it
```

A run holds everything it needs to be shown later, including the cited passages' text, because a
document can be deleted after the run: the run then shows the passage as it was read, marked as
coming from a deleted document, the same way a saved conversation does (suveryn-tracker#12).

## The API

```
GET    /v1/cases/{id}/playbooks              which playbooks fit this case's type, with covered
POST   /v1/cases/{id}/playbooks/{playbook}/runs    start a run: {document_ids?}  (contributor)
GET    /v1/cases/{id}/playbooks/runs          the case's runs, newest first        (reader)
GET    /v1/cases/{id}/playbooks/runs/{run}    one run with its facts               (reader)
PUT    /v1/cases/{id}/playbooks/runs/{run}/facts    confirm the checkpoint: {facts: [{id, confirmed}]}  (contributor)
```

The playbook path segment is the id's last part (`deed-intake`); the full id is in the response.
Starting a run answers at once with the run in status `reading`; the client polls the run. The
model call is one grounded request, like a chat question but with the playbook's own instructions
and no history: the fields as a Markdown table the model fills, each cell citing [n]. The gateway
parses the table, keeps the citations per fact and runs the check. A row names its fact by id or by
its label in any of the playbook's languages (a small model translates), never by position: a
skipped row would shift every later fact onto the wrong label without anyone noticing. An answer
that isn't the table is asked for once more with a stricter reminder; then the run fails with
`error: unreadable_answer` and can be started again. Starting a run counts against the caller's
chat rate limit (it is a model call). A run still `reading` when the gateway stops is failed as
`interrupted` at the next start, and the hourly sweep fails one that has been reading for over
thirty minutes, so nobody waits on a spinner for a call that no longer exists. A case closed while
a run waits at its checkpoint keeps the run; the UI says to reopen the case to confirm.

**Provenance in the result.** The summary document and its name carry the run's `playbook_id` and
`playbook_version`, never the playbook as installed at confirmation time: a run started under 1.0
and confirmed after an upgrade to 1.1 says 1.0, because 1.0 is what read the documents (outside
review, 17 October 2026).

## The chat UI

Deed intake opens from the composer's **Playbook** chip, in a case whose type has playbooks: the
chip's menu lists them, each with *Covered* or *Not covered*. Every member of the case gets the chip;
a reader sees the runs, and only a contributor or the manager starts or confirms one. The view
takes the conversation's place (`components/DeedIntake.tsx`):
the run's facts in the playbook's order, each a row with the label, the value as read, the source
(file name, page) that opens the passage with the claim marked, the check's warning when there is
one, and a text field to confirm or correct. "Confirm the facts" at the bottom; a fact left empty is
confirmed as empty. After confirmation: the summary, a Word download (made in the browser, as
answers are), and the document appears in the case's list. Earlier runs are listed under the
current one. Every piece of text in three languages; every control from `packages/chat-ui/src/ui/`.

## The manifest (30 October 2026)

A playbook is a **file**, not a Python module: `packages/playbooks/src/suveryn_playbooks/<pack>/<name>.yaml`,
validated against a schema and loaded into the same `Playbook` object the gateway and the harness
always used (`suveryn_playbooks.manifest`). Deed intake 1.0 was rewritten as the first one, field
for field identical to the code it replaced (`tests/test_manifest.py` holds the snapshot), so
nothing a user or a run sees changed. The reason to do it now, ahead of the runtime: a playbook
that is code can only exist compiled into the product. A playbook that is a file can be signed into
a pack bundle, kept in a private repository and distributed to licensees only (the commercial
model), uploaded to an appliance by its administrator, written by an office for itself, and shown
in full to a reviewer. Everything the platform note promised about packs needs the file first.

Format 1 says what deed intake needed and nothing more: `manifest: 1` (the format's own version),
the identity, `case_types`, the `facts` (id, what to ask, kind) and the `instructions` prose. The
table the model fills in is appended by the loader: it is the harness's contract with the model,
not content, and an author never writes it. The wording per language stays in the pack's
`text/<lang>.json` beside the manifest. Unknown keys are errors, and every error names the file
and the field: the people writing these by hand are administrators, not developers, and a misspelt
key silently ignored is a playbook that quietly does something else. The JSON Schema for editors
is generated from the model into `packages/playbooks/schema/` and a test keeps the two in sync.

Format 2 is the step graph: `request`, `read`, `ask`, `check`, `propose`, `checkpoint`, `produce`,
with conditions, gates, products and a model role per step. It arrives with the runtime, and a
format-1 file keeps loading as what it is. Open with it: whether an office's own manifest may carry
its wording inline (one file to upload) rather than in a pack's text files.

## What is deferred, on purpose

- A facts layer shared between playbooks (#27): after the second playbook shows which facts recur.
- A step graph, queued runs, a runtime (#28): the manifest came first (below); the steps join it as
  format 2 when the runtime does.
- The Word document from the office's own template (#22): the summary is sūveryn's own layout now.
- Named subject fields on the case type (#29): the intake's facts are the first candidates.
- Facts validated by form (national register numbers, cadastral patterns): an entities table, later.
- A second model pass that judges meaning: the rule-based check is what a chat answer gets today.
