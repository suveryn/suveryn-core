# Playbooks: deed intake first, as a routine (suveryn-tracker#51)

A design note, October 2026, for the first playbook. The platform note ([platform.md](platform.md))
first decided on three hand-built notary playbooks before any runtime; on 30 October the product
definition changed (the project's orchestration note): a playbook is a conversation with a routine,
written as a manifest, and the manifest and the runtime came first, proven on deed intake. This
note says what deed intake is, what it leaves behind in the case, how the routine, the facts'
record and the thread work ("The routine"), and the few things that were settled early because
they would be expensive to retrofit. It replaces the earlier bot-written tickets (#27 facts layer, #28
runner, #29 templates) as the plan.

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
   as a chat answer (`suveryn_harness.support`; the answer is read by `suveryn_harness.facts`), and a fact the model couldn't find is left empty,
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

```text
playbook_runs   id, case_id, playbook_id, playbook_version, status, documents uuid[],
                started_by, started_at, finished_at, confirmed_by, confirmed_at,
                facts jsonb, model, error, result_document_id, out_of_date bool
```

`status` is `reading` (the model is working), `checkpoint` (waiting for a person), `confirmed`,
or `failed` (with `error`: a kind, never text). `facts` is a list, one entry per field, in the
playbook's order:

```text
{ id, value, citations: [{n, document_id, filename, page, location, text}],
  issues: [item, ...],            the check: figures, dates or names not in the cited passage
  confirmed: null | string,       what the person confirmed (the value, a correction, or "")
  found: bool }                   false: the model said the documents don't contain it
```

A run holds everything it needs to be shown later, including the cited passages' text, because a
document can be deleted after the run: the run then shows the passage as it was read, marked as
coming from a deleted document, the same way a saved conversation does (suveryn-tracker#12).

**A run keeps the manifest it started under** (3 November 2026, `playbook_runs.manifest`). At the
start the loaded playbook is written into the run as a record (`suveryn_playbooks.record`: facts,
steps, instructions, words), and from then on everything about that run reads its own record: the
runtime's steps, the harness's read, the labels in the thread and the summary, `Run.playbook` for the
UI. An upgrade of the installed manifest changes nothing in a run that is under way, and a run
finished under 1.0 is still shown with 1.0's words after 1.2 is installed: with format 3 a new
version can add or rename a list's fields, and a run's paths must mean what they meant. A run made
before this column (`manifest` NULL) reads the installed manifest, as before. The installed one still
supplies what a chip needs across many runs (titles, the kind of a step), where a query per run would
be too much for too little.

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
| `request` | Puts the pack's question for documents in the thread; named (`expects`), it records which documents answered it | `min` uploaded documents in the case (for a named request: documents that answered it), or a person saying there is none (`allow_none`) |
| `read` | The grounded model call for the step's facts over the case's uploaded documents, or, aimed at named requests (`documents`), over the documents that answered those | The model; nothing, when every request it is aimed at was skipped: its facts are then not established without a call |
| `ask` | One question per fact the documents didn't contain, in the pack's words | A person's answers (empty: not known yet) |
| `checkpoint` | Shows every fact with its evidence | A person confirming, correcting or clearing each |
| `check` | Evaluates one rule on the values as they stand (`suveryn_harness.checks`); the result is shown at the checkpoint and in the summary, never a block | Nothing |

Any step may carry `when` (a condition on a choice fact, "Choices" below): a step whose condition doesn't hold is skipped, and the thread says why.
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

**The thread is a conversation** (decision, 30 October 2026). Starting a run makes a conversation in the
case (`conversations.run_id`; `playbook_runs.conversation_id` points back), titled with the playbook in
the run's language, its starter its owner, shared with the case from the start: it is listed, opened
and named like any other conversation, with the route icon. It goes with its case, not with the
conversations' keep period, "Delete history" or its owner's account, and it can't be unshared, moved,
saved over or deleted on its own (stop or cancel the run). Every conversation's turns, ordinary chat
included, are rows in `turns` (`conversations.py`, `TurnStore`): one per turn, stamped with who and
when. A playbook's thread is appended by the server and never rewritten; the chat UI still saves its
own conversation whole, and the rows are brought in line with it (a changed turn rewritten in place,
new ones appended, dropped ones deleted). No upgrade from the earlier blob: there are no appliances in
production (decision, 31 October 2026). Event-sourcing the run (deriving steps, facts and turns from one
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
no longer the case's), and the product is marked `withdrawn` in its provenance, never deleted; cancel, unlike stop, also supersedes what was only read. Stop and cancel are the starter's (by id,
never by the shown name) or the case manager's. In every case the run record stays; nothing is
deleted except with the case. **One live run per playbook per case**: a second start answers 409
with the live run's id.

The upload hook is a person's act: the documents come into the case through the composer's paperclip
and with the person's turn (a line and its documents are one turn), and the runtime counts the case's
uploaded documents. **A request always asks first**, even when the case already holds documents: it is met
once a person has answered it, with documents or with *Use the documents already in the case*, and the
case has what it needs; documents that came with the turn are what the read reads, so a deed already in the case is never read as the agreement without a word. The playbook never
writes the same line twice in a row (two answers at the same moment wrote its question twice). Nothing
advances on a GET.

**People answer in words** (handover of 30 October 2026; decision, 31 October). At an `ask`, the answer is
mapped to the facts asked by one plain model call (`suveryn_harness.facts.map_answer`: the facts' ids and
labels, the person's words, `id: value` lines back, anything else ignored); each value is a proposed
fact from that person, and the quick reply "Not known yet" leaves them unknown. At the checkpoint, a
correction in words is mapped the same way over every fact and becomes a new version from that person
(`source: person`; the value as read is kept and shown as "read as"); the playbook says what changed.
When nothing can be placed, the playbook says so and asks again in words; the facts panel's fields stay
the precise way in. Pausing, resuming, stopping, cancelling and confirming are lines in the thread too.

## The API

```text
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
instructions and no history: the facts as a JSON object of the facts' shape (format 3, below), each
value with the excerpt numbers it comes from. The request carries that shape as a JSON Schema and
llama-server holds the model to it by grammar, so the answer has every fact as a key by
construction; a fact is never taken by position. The harness reads the object, keeps the citations
per value and runs the check. An answer that still isn't the object (a server without grammar
support, a model that ignored it) is asked for once more with a stricter reminder; then the run
fails with `error: unreadable_answer` and can be started again. Starting a run, or answering the request
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
value the check couldn't find literally in its passage (the sentence of the passage the value comes from quoted with a teal rule, "…" where the passage goes on, the whole passage behind the source link; what isn't
in it said in words with the triangle, and the source), and *Missing*, a fact without a value. *Adjust*
and *Fill in* turn the value into a field in the card (Enter keeps it, Esc cancels; `PUT
…/runs/{run}/facts/{fact}`): a changed value is a new version from that person and a line in the thread;
the same value says the person checked it. *Confirm the facts*, the one primary button, is held back
while anything is under *Check*, focusable, with its reason; *Missing* may stay open (decision, 31 October:
confirming then records it as not established and the run finishes, as before). Found and quoted facts
get no card. *See all 13 facts* opens the list.

**Check by meaning**. An amount or a date is compared with its passage by
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
shape of the answer the model gives is appended to the instructions by the loader, and the JSON
Schema the server enforces is derived from the facts (`read_schema`): both are the harness's
contract with the model, not content, and an author never writes them. The wording per language stays in the pack's
`text/<lang>.json` beside the manifest. Unknown keys are errors, and every error names the file
and the field: the people writing these by hand are administrators, not developers, and a misspelt
key silently ignored is a playbook that quietly does something else. The JSON Schema for editors
is generated from the model into `packages/playbooks/schema/` and a test keeps the two in sync.

Format 2 (30 October 2026) adds `steps`: `request`, `read`, `ask`, `checkpoint`, `produce`, each
with `needs` (default: the step before). The graph is validated: ids once, needs resolve, no circle,
a checkpoint before any produce, an ask only about facts a read before it reads, the fields of one
kind refused on another; every error names the step. Format 1, the same without `steps` (read as the
implicit routine read, checkpoint, produce), was retired before any was published: one format to
document and test, as nothing written in it exists. The questions a `request` or `ask` step puts to people are the pack's
wording (`text/<lang>.json`, `questions`: by step id, with `{label}` in an ask's template, or by
`step.fact` for one fact's own words), reviewed and translated like the labels; the model never
words them. Later formats bring `check`, `propose`, conditions, products beyond the summary and a
model role per step. Open: whether an office's own manifest may carry its wording inline (one file
to upload) rather than in a pack's text files.

### Format 3: lists and numbers (3 November 2026)

A fact was one line. A deed's parties are not: three founders, each with a name, a number of shares
and a contribution, don't fit a line, and the first company-formation playbook had to cram them
into one fact "as written". The founder asked for the generic fix rather than a second parser, and
format 3 is it: **a playbook's facts describe a shape, and the whole pipeline works on that shape.**

- **Two kinds more.** `number`: a figure without currency (a count, a share, a percentage), checked
  by meaning against its passage like an amount, short figures included ("3 aandelen"), which the
  chat's figure check skips as ambiguous and a playbook asked for on purpose. `list`: several
  entries, each a record of plain-valued fields (`of:` a list of facts) or one plain value (`of:` a
  kind). A list holds records or values, never lists: a deed has "several parties, each with a few
  details" and no deeper, and a file an office can still write by hand stays one level deep. A
  format-2 file loads unchanged; a format-2 file that uses either kind is refused with the fact named.
- **One mould for the model.** The loader derives a JSON Schema from the facts (`read_schema`): per
  value `{"value": "as written" | null, "sources": [n, …]}`, a list an array of entries. The request
  carries it (`ChatRequest.json_schema`) and llama-server compiles it to a grammar
  (`response_format`), so the answer parses by construction: no row-name folding, no table retry
  path; the one retry left is for a server without grammar support. Values are always strings copied
  from the documents; the harness reads them by kind, so "copied as written" and the check by meaning
  survive unchanged. Thinking is off for a read (the request's default), so the grammar binds the
  answer, not reasoning. **To verify on the pod before the pin moves:** Qwen3.8 under a grammar on a
  real deed, and the time a grammar adds per read.
- **Paths, so nothing downstream changes shape.** A list's values are named by path:
  `founders[1].name`, `founders[2].contribution`, `conditions[1]` (`suveryn_playbooks.paths`). A path
  is a string, so `case_facts.fact_id`, a person's answer, a correction, the confirm body, the summary's
  line, the UI's label all take it as they took `price`; only what a path means is new. One row per
  version, superseded pointers, the record: as before. The list's own id names the list as a whole:
  the read writes it as one not-found fact when the documents name no entries, so an `ask` step can
  ask about the list; the first entry a person gives supersedes that "none" (`_settle_lists`). A list
  with entries is shown by its entries, never by its id (`shown_facts`).
- **People add entries.** At an `ask`, an answer in words is mapped onto the first entry's values
  (`askable`); at the checkpoint, onto every value the run has plus one entry beyond the last
  (`_checkpoint_labels`), so "a third founder, Anna Peeters" adds one. On a card: a list the documents
  named none of shows *Add* instead of *Fill in*, with one field per value of the entry; a list with
  entries offers one more under *More*. Each value given is a version from that person, as a
  correction is; `PUT …/facts/{fact}` takes a new path into a list as new ground. Removing an entry
  is clearing its values. The labels: the list's, the entry's number, the field's
  (`labels["founders.name"]`): "Oprichter(s) 2 · Aandelen".
- **Deed intake 1.2** is deed intake with the JSON answer: the facts and the words are 1.0's, the
  instructions say "the object" where they said "the table". **Company formation 1.0** is the first
  playbook with a list: the founders, each with name, shares (number) and contribution (amount).
- `check` steps on these typed values: below, "Checks".

### Documents by name (3 November 2026)

One request for "what the founders sent" and one read over everything is an intake; a routine a
clerk recognises asks for the bank certificate, reads it, asks for the financial plan, reads that.
Item 3 of the foundation brief, still format 3 (two optional keys; a file without them reads as
before):

- A `request` may say what it asks for: `expects: bank_certificate`, a name unique among the
  routine's requests. When a person answers it, the run records which documents answered: those that
  came with the turn (`SayIn.documents`, `AnswerIn.documents`), or, when none did, the case's uploaded
  documents no other request has yet (`playbook_runs.requested`, request step id → document ids).
  `min` counts those, as long as they are still in the case.
- A `read` may be aimed: `documents: [bank_certificate, financial_plan]`, names of requests among the
  steps it needs; it reads the documents that answered them and nothing else, with its own
  `json_schema` over its own facts. Unaimed, it reads as before. A read aimed only at requests that
  were skipped (there is no such document) makes no model call: its facts are written not
  established, the step is done, and an `ask` step asks about them. A fact is read by one read step;
  the loader refuses a second.
- `Run.documents` becomes the union of what the run's reads read, for the out-of-date mark; a run
  keeps `requested` with its record.

Company formation 1.1 is the first routine written this way: identity documents, then the financial
plan, then the bank certificate (`allow_none`, for a contribution in kind), each with its read. Until
`when` exists (item 5), the ask step still asks for the bank certificate's facts after a person said
there is none; that is the next version's job. The founders now carry their identity (register
number, date and place of birth, address), read and kept like any fact, decided 3 November; the data
lifecycle page says so.

### Checks (3 November 2026)

What a notary adds up by hand: the founders' shares against the shares issued, their contributions
against the contribution in money, the bank's certificate against that amount. Item 4 of the
foundation brief, on the typed values format 3 laid down.

- A `check` step states one `rule`, a comparison a notary can read: `sum(founders.shares) == shares`,
  `certified_amount == contribution`, `count(founders) >= 1`, `plan_date <= deed_date`. A term is a
  fact, the sum of a list's field, the count of a list's entries, or a number; both sides are of one
  kind (amount, number or date). Nothing else: no arithmetic, no and/or, no text
  (`suveryn_playbooks.rules`). The loader refuses a rule that doesn't parse, that compares kinds, or
  that reads facts no read step before it reads, with the step named. A manifest grows into a
  programming language the day a notary can't read a line and know what it does; the rule language is
  kept at one comparison for that reason.
- The server computes, by kind, the way the check by meaning reads a value ("twintigduizend euro"
  counts as 20,000; "1.000 aandelen" as 1,000, in the values' own decimal style): the model never does
  arithmetic (`suveryn_harness.checks.evaluate`). A result holds, fails (both sides as computed, for the
  notary) or is open (a value is missing or gives no amount, number or date as written: a person works
  it out first, and the result names what is needed).
- Results live on the run (`playbook_runs.checks`) and are recomputed whenever a value changes: when
  the check step is reached, after an answer, after a correction at the checkpoint, and once more on
  the confirmed values before the summary. The checkpoint shows them as a *Checks* group, one line
  each, with the pack's sentence for the check (`text/<lang>.json`, `checks.<step id>`) and the result;
  a failed check is a point for the notary and never holds *Confirm* back. The summary ends with them.
- Company formation 1.2 has four: shares add up, contributions add up, the bank certifies the
  contribution, at least one founder.

### Choices, and steps that turn on them (3 November 2026)

Cash or in kind decides which documents are asked for, which reads run and which checks apply. Item 5
of the foundation brief.

- A `choice` fact has `options` (two to twelve ids: `cash`, `in_kind`, `mixed`), each with its words in
  the pack's labels (`contribution_kind.cash`). The model reads it when the documents say it, held to
  the options by the schema (an enum); otherwise an `ask` step asks, and the thread offers the options
  as buttons; an answer in words is mapped to an option by its id or its words in the run's language.
  A choice is a fact of its own, never a list's field. It is not a value a check compares.
- Any step may carry `when`: `contribution_kind != in_kind`, one condition on one choice, `==` or `!=`,
  and nothing more (`suveryn_playbooks.conditions`); the loader refuses anything else, and a `when`
  on a choice no read or ask step before it settles. When the step is reached and the condition
  doesn't hold, or the choice isn't known by then, the step is skipped (`StepState.because`: the
  condition and the value) and the playbook says so in the thread, in the pack's name for the step
  (`steps.<id>` in the words file) and the option's words: "Bank certificate: not needed, Contribution
  is In kind." A skipped read makes no facts, so nothing asks about them; a skipped check has no
  result; a skipped request records no documents.
- Company formation 1.3: the contribution's kind is read from the plan or asked before the branches;
  the bank certificate and its read, the contributions' check and the bank's check run when there is
  money; the auditor's and founders' reports and their read run when something is contributed in
  kind; the ask step after the branches asks only about facts a read made.
- Kept out, on purpose: and/or, conditions on anything but a choice, jumps back, loops. A routine a
  notary can read top to bottom and know what runs is the point; the day a condition needs more it
  needs a decision, not a longer line.

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
