# Playbooks: deed intake first, as a routine (suveryn-tracker#51)

A design note, October 2026, for the first playbook. The platform note ([platform.md](platform.md))
first decided on three hand-built notary playbooks before any runtime; on 30 October the product
definition changed (the project's orchestration note): a playbook is a conversation with a routine,
written as a manifest, and the manifest and the runtime came first, proven on deed intake. This
note says what deed intake is, what it leaves behind in the case, how the routine, the facts'
record and the thread work ("The routine"), and the few things that were settled early because
they would be expensive to retrofit. It replaces the earlier bot-written tickets (#27 facts layer,
#28 runner, #29 templates) as the plan.

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

## The routine (30 October 2026)

A playbook is a **conversation with a routine** (the project's orchestration note). When it is
active in a case it holds the chair: it asks for documents, reads them, asks about what it couldn't
find, waits for a person at the checkpoint, writes the summary. Everyone who contributes to the
case takes part through that routine, and it ends in a product. The model is asked only inside a
``read`` and never decides what comes next; a person's answer never becomes a confirmed fact except
at the checkpoint, by that person.

The routine is in the manifest (format 2, below): steps of five kinds, each saying what it needs.

| Kind | What the runtime does | Waits for |
|---|---|---|
| `request` | Puts the pack's question for documents in the thread | `min` uploaded documents in the case, or a person saying there is none (`allow_none`) |
| `read` | The grounded model call over the case's uploaded documents for the step's facts, as before | The model |
| `ask` | One question per fact the documents didn't contain, in the pack's words | A person's answers (empty: not known yet) |
| `checkpoint` | Shows every fact with its evidence | A person confirming, correcting or clearing each |
| `produce` | Writes the summary into the case, origin `playbook` | Nothing |

The runtime (`suveryn_api_gateway/playbook_runtime.py`) walks the graph: `next_step` is the first
step, in the manifest's order, that isn't done and whose needs all are; `advance` does what needs
nobody (a request already satisfied, an ask with nothing to ask, the summary) and stops where the
run waits. It takes its stores as arguments and is tested without a request. Deed intake 1.1 is
the first routine: agreement (request), read, missing (ask), confirm, summary.

**Facts have a record of their own**: `case_facts`, one row per **version**, never rewritten.
The model's reading is `proposed` (or `not_established` when the documents don't contain it); a
person's answer to an ask is `proposed` from a person; the checkpoint writes `confirmed`, or
`not_established` when the person clears it. A version that replaces another points at it
(`replaces`) and the older one becomes `superseded`. So a fact's history is readable in plain SQL:
read as X by the model, answered Y by a person, confirmed Z by another. `Run.facts` keeps the shape
the UI always had (as read, confirmed, citations), assembled from the current versions; runs made
before this table keep their facts in `playbook_runs.facts` and can be viewed but not continued.
The shared facts layer the record deferred (#27) is this table; what recurs between playbooks is
to be seen from the second one.

**The thread is a conversation** (Filip, 30 October 2026). Starting a run makes a conversation in the
case (`conversations.run_id`; `playbook_runs.conversation_id` points back), titled with the playbook in
the run's language, its starter its owner, shared with the case from the start: it is listed, opened
and named like any other conversation, with the route icon. It goes with its case, not with the
conversations' keep period, "Delete history" or its owner's account, and it can't be unshared, moved,
saved over or deleted on its own (stop or cancel the run). Every conversation's turns, ordinary chat
included, are rows in `turns` (`conversations.py`, `TurnStore`): one per turn, stamped with who and
when. A playbook's thread is appended by the server and never rewritten; the chat UI still saves its
own conversation whole, and the rows are brought in line with it (a changed turn rewritten in place,
new ones appended, dropped ones deleted). No upgrade from the earlier blob: there are no appliances in
production (Filip, 31 October 2026). Event-sourcing the run (deriving steps, facts and turns from one
event log) was considered and rejected: tables a notary can read beat a log only a developer can.

**A run is visible, and it can be paused, stopped or cancelled.** The case lists show a chip
("Deed intake · waiting for documents"; the gateway puts the playbook's title per language and the
step's kind on every run it answers, so a list that spans cases needs no playbook lookup); the run's
view has a banner with the status, the step, what it waits for and from whom, and the model while it
reads; an ended run's banner names no step. Statuses: `reading` (the model),
`waiting` (a person), `paused`, `done`, `stopped`, `cancelled`, `failed` (by kind; `busy` when no
place to read was free, start again). Three acts, three states: **pause** keeps everything and
waits (anyone who contributes; a run that is reading is paused when it next waits); **stop** ends
early and keeps what was achieved: confirmed facts stay the case's, proposed ones are dropped
(superseded), a product so far stays; **cancel** says the run should not have happened: every
version the run established, read, answered or confirmed, becomes `superseded` (kept in the record,
no longer the case's), and the product is marked `withdrawn` in its provenance, never deleted (the
Pod check of d0f680e asked whether cancel should also drop what was only read, as stop does: yes). Stop and cancel are the starter's (by id,
never by the shown name) or the case manager's. In every case the run record stays; nothing is
deleted except with the case. **One live run per playbook per case**: a second start answers 409
with the live run's id.

The upload hook is a person's act: the documents come into the case through the composer's paperclip
and with the person's turn (a line and its documents are one turn), and the runtime counts the case's
uploaded documents. **A request always asks first**, even when the case already holds documents: it is met
once a person has answered it, with documents or with *Use the documents already in the case*, and the
case has what it needs; documents that came with the turn are what the read reads (VM regression e0f2e26: a
deed left in the case was read as the agreement without a word; Filip, 1 November 2026). The playbook never
writes the same line twice in a row (two answers at the same moment wrote its question twice). Nothing
advances on a GET.

**People answer in words** (handover of 30 October 2026; Filip, 31 October). At an `ask`, the answer is
mapped to the facts asked by one plain model call (`suveryn_harness.facts.map_answer`: the facts' ids and
labels, the person's words, `id: value` lines back, anything else ignored); each value is a proposed
fact from that person, and the quick reply "Not known yet" leaves them unknown. At the checkpoint, a
correction in words is mapped the same way over every fact and becomes a new version from that person
(`source: person`; the value as read is kept and shown as "read as"); the playbook says what changed.
When nothing can be placed, the playbook says so and asks again in words; the facts panel's fields stay
the precise way in. Pausing, resuming, stopping, cancelling and confirming are lines in the thread too.

## The API

```
GET    /v1/cases/{id}/playbooks              which playbooks fit this case's type, with covered and steps
POST   /v1/cases/{id}/playbooks/{playbook}/runs    start: {document_ids?, language?}; no language: the caller's Accept-Language; 409 while one is live  (contributor)
GET    /v1/playbooks/runs/active              the live run per case the caller may read: the chip (reader)
GET    /v1/cases/{id}/playbooks/runs          the case's runs, newest first        (reader)
GET    /v1/cases/{id}/playbooks/runs/{run}    one run: step, steps, facts, turns  (reader)
POST   /v1/cases/{id}/playbooks/runs/{run}/say      {text?, documents?, unknown?}: a turn in the run's conversation  (contributor)
POST   /v1/cases/{id}/playbooks/runs/{run}/answer   {step_id, text?, facts?, none?}: an ask's facts, or a request  (contributor)
PUT    /v1/cases/{id}/playbooks/runs/{run}/facts    the checkpoint: {facts: [{id, confirmed}]}  (contributor)
PUT    /v1/cases/{id}/playbooks/runs/{run}/facts/{fact}   a card's value {value}: a new version; the same value: checked  (contributor)
POST   …/runs/{run}/pause | /resume           anyone who contributes
POST   …/runs/{run}/stop | /cancel {reason}   the starter or the case manager
```

The playbook path segment is the id's last part (`deed-intake`); the full id is in the response.
A start walks the run to its first wait and answers with it; a run in status `reading` is polled.
The model call is one grounded request, like a chat question but with the playbook's own
instructions and no history: the facts as a Markdown table the model fills, each cell citing [n].
The gateway parses the table, keeps the citations per fact and runs the check. A row names its
fact by id or by its label in any of the playbook's languages (a small model translates), never by
position: a skipped row would shift every later fact onto the wrong label without anyone noticing.
An answer that isn't the table is asked for once more with a stricter reminder; then the run fails
with `error: unreadable_answer` and can be started again. Starting a run, or answering the request
its read waits on, counts against the caller's chat rate limit (it is a model call). A run still
`reading` when the gateway stops is failed as `interrupted` at the next start, and the hourly
sweep fails one that has been reading for over thirty minutes, so nobody waits on a spinner for a
call that no longer exists. A case closed while a run waits keeps the run; the UI says to reopen
the case to go on. Every act is in the case's access log: `playbook_started`, `playbook_answered`,
`playbook_confirmed`, `playbook_paused`, `playbook_resumed`, `playbook_stopped`, `playbook_cancelled`.

**Provenance in the result.** The summary document is named with the playbook's title in the run's
language, the case's reference and the run's version ("Akte-intake 2026/0417 (1.1)"). It and its name carry the run's `playbook_id` and
`playbook_version`, never the playbook as installed at confirmation time: a run started under 1.0
and confirmed after an upgrade to 1.1 says 1.0, because 1.0 is what read the documents (outside
review, 17 October 2026).

## The chat UI

A playbook is a conversation (handovers of 30 and 31 October 2026; the canvas "Sūveryn · gesprek en
playbook, één taal"; `components/RunConversation.tsx`). The composer's *Playbook* menu starts a run,
always as a new conversation in the case, listed under the case, in *Recent* and in the Conversations
overview with the route icon; earlier runs are earlier conversations. The playbook speaks as sūveryn:
the brand mark with the route badge (teal: the system speaking) and its title as speaker above each
series of its turns. Its messages are short and name the problem, never a place on the screen. A quick
reply (*Not known yet*) goes once the question is answered. Pausing, resuming, stopping, cancelling and
confirming are centred lines; done is "Confirmed by …" in teal and the summary as a document card with
its Word download.

**Review is in the playbook's message.** At the checkpoint its message says how many facts were found
and how many need attention, then one card per fact that needs the person, in two groups: *Check*, a
value the check couldn't find literally in its passage (the passage quoted with a teal rule, what isn't
in it said in words with the triangle, and the source), and *Missing*, a fact without a value. *Adjust*
and *Fill in* turn the value into a field in the card (Enter keeps it, Esc cancels; `PUT
…/runs/{run}/facts/{fact}`): a changed value is a new version from that person and a line in the thread;
the same value says the person checked it. *Confirm the facts*, the one primary button, is held back
while anything is under *Check*, focusable, with its reason; *Missing* may stay open (Filip, 31 October:
confirming then records it as not established and the run finishes, as before). Found and quoted facts
get no card. *See all 13 facts* opens the list.

**Check by meaning** (VM regression 03c8f74, decision 1). An amount or a date is compared with its passage by
what it means, not letter for letter: "412.500" against "412 500", "EUR 26.800" against "zesentwintigduizend
achthonderd euro", "12/05/2014" against "le douze mai deux mille quatorze" (`suveryn_harness.values`, nl, fr
and en). A fact of kind amount or date whose value is neither, as written ("uiterlijk vier maanden na de
opschortende voorwaarde"), goes under *Check* with its own reason: "Not a date as written: work it out and
check it" (`needs: not_a_date` / `not_an_amount` on the fact's source). At the checkpoint, "Bodemattest: nog
niet bekend." in words of a fact that is unknown already is answered "Bodemattest staat al als nog niet bekend."
(`already_unknown`), not "That couldn't be placed"; in an *ask* it leaves the facts unknown, as the quick reply
does. A value isn't emptied in words, as it isn't on a card.

**Every fact, in a list beside the conversation** (the source panel's place, a sheet on a phone): "All
facts for the deed" (the pack's `factsTitle`), every fact in the pack's order with its source, "From the
conversation, 10:06" for a value given there, "Not known yet", or the check's warning; nothing is edited
there. A source opens in the same place with a way back to the list (at the same scroll position); from a
card it opens on its own. The header carries the conversation's state ("Deed intake · to check": the one
place it is said) and, while the run is live, a toggle "Facts · 12 of 13" that opens and closes the list.
The composer carries the run's chip: teal with the playbook's title only, ink "… · paused" when paused,
with pause, cancel (with a reason) and stop. No hint line under the composer while a run is live. A reader
sees the thread and "Read only". Every piece of text in three languages; every control from
`packages/chat-ui/src/ui/`.

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

The manifest says the identity, `case_types`, the `facts` (id, what to ask, kind), the `instructions`
prose and, since format 2, the routine (below); `manifest:` names the format's own version. The
table the model fills in is appended by the loader: it is the harness's contract with the model,
not content, and an author never writes it. The wording per language stays in the pack's
`text/<lang>.json` beside the manifest. Unknown keys are errors, and every error names the file
and the field: the people writing these by hand are administrators, not developers, and a misspelt
key silently ignored is a playbook that quietly does something else. The JSON Schema for editors
is generated from the model into `packages/playbooks/schema/` and a test keeps the two in sync.

Format 2 (30 October 2026) adds `steps`: `request`, `read`, `ask`, `checkpoint`, `produce`, each
with `needs` (default: the step before). The graph is validated: ids once, needs resolve, no circle,
a checkpoint before any produce, an ask only about facts a read before it reads, the fields of one
kind refused on another; every error names the step. Format 1, the same without `steps` (read as the
implicit routine read, checkpoint, produce), was retired before any was published: one format to
document and test, as nothing written in it exists (external review, pass 8). The questions a `request` or `ask` step puts to people are the pack's
wording (`text/<lang>.json`, `questions`: by step id, with `{label}` in an ask's template, or by
`step.fact` for one fact's own words), reviewed and translated like the labels; the model never
words them. Later formats bring `check`, `propose`, conditions, products beyond the summary and a
model role per step. Open: whether an office's own manifest may carry its wording inline (one file
to upload) rather than in a pack's text files.

## What is deferred, on purpose

- Which facts recur between playbooks (#27): `case_facts` is the record; its shared vocabulary is
  to be seen from the second playbook.
- Conditions, `check`, `propose`, model roles, products beyond the summary, products marked out of
  date by changed facts (#28, the rest): the next formats.
- Ordinary chat on the `turns` table: its own step, with the conversion of the saved blobs.
- The Word document from the office's own template (#22): the summary is sūveryn's own layout now.
- Named subject fields on the case type (#29): the intake's facts are the first candidates.
- Facts validated by form (national register numbers, cadastral patterns): an entities table, later.
- A second model pass that judges meaning: the rule-based check is what a chat answer gets today.
