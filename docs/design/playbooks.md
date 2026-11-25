# Playbooks

A playbook is a conversation with a routine. When it is active in a case it holds the chair: it asks for documents, reads them, asks about what it couldn't find, waits for a person to confirm every fact, and writes a result. Everyone who contributes to the case takes part through that routine. The model is asked only inside a `read` step and never decides what comes next; a fact becomes the case's only when a person confirms it.

A playbook is written as a manifest, a YAML file, with its words per language beside it. The format's rules (the keys, the kinds of fact, the steps, the checks, the words file, a pack's calendar) are in the public guide, [Writing a playbook](https://github.com/suveryn/suveryn-docs/blob/main/playbooks/writing-a-playbook.md), and are not repeated here. This note is the design and the why: how a playbook runs in a case, what it records, and what is not built. The loader is `packages/playbooks`; the runtime is the gateway's (`suveryn_api_gateway.playbook_runtime`).

## Deed intake

Deed intake is the public reference playbook: the worked example, the test fixture and what an office copies (`packages/playbooks/src/suveryn_playbooks/be_notary/deed-intake.yaml`; the guide's complete example is this file, line for line). A notary opens a sale case; the parties have sent the signed private sale agreement (compromis), the earlier title deed, the energy and soil certificates. Before anyone drafts the deed, someone reads all of it and writes down the facts the deed will need. Deed intake does the reading and leaves the writing-down to be checked: it asks for the agreement, the title deed and the certificates, reads each for the facts it states, asks about what it didn't find, runs five checks, waits for a person to confirm, and writes the summary.

Its thirteen facts are the parties (sellers and buyers, lists with a name, an address and a register number), the property, the cadastral identification, the price, the deposit, the agreement's date, the deed's deadline, the suspensive conditions (a list, each with its term), the seller's title, the energy and soil certificates and the occupancy. Thirteen, not more: every fact is a line the notary has to check. The guide explains each.

The certified playbooks, company formation and the care mandate, are in suveryn-packs (*Where playbooks live*).

## The routine

The routine is the manifest's `steps`, of six kinds, each saying what it needs (by default the step before it).

| Kind | What the runtime does | Waits for |
|---|---|---|
| `request` | Puts the pack's question for documents in the thread; a named request (`expects`) records which documents answered it | A person's answer: documents, *Use the documents already in the case*, or, where allowed, *There is none* |
| `read` | One grounded model call for the step's facts, over the case's uploaded documents or, when aimed (`documents`), over the documents that answered those requests. Documents longer than one reading takes (the whole-document budget, architecture.md) are read by the passages that best match the step's facts (their questions and labels in every language, not the instructions); the facts still not found are then looked for in each document alone, in the order the step names them, and a fact found is never replaced by a later document. The step keeps their names (`in_part`) and the thread says so once per document | The model; nothing, when every request it is aimed at was answered *There is none*: its facts are then not established without a call |
| `ask` | One question per fact the documents didn't contain, in the pack's words | A person's answers (empty: not known yet) |
| `check` | Evaluates one rule on the values as they stand (`suveryn_harness.checks`) | Nothing |
| `checkpoint` | Shows every fact with its evidence | A person confirming, correcting or clearing each |
| `produce` | Writes the summary into the case, origin `playbook` | Nothing |

The runtime walks the graph: `next_step` is the first step, in the manifest's order, that isn't done and whose needs all are; `advance` does what needs nobody (a request already met, an ask with nothing to ask, a check, the summary) and stops where the run waits. It takes its stores as arguments and is tested without a request. Nothing advances on a GET.

**A request always asks first**, even when the case already holds documents, so a deed already in the case is never read as the agreement without a word. The documents come with the person's turn (the composer's paperclip: a line and its documents are one turn); with none attached, the request takes the case's uploaded documents no other request has yet.

**Choices.** A step may turn on a choice fact ([the rule](https://github.com/suveryn/suveryn-docs/blob/main/playbooks/writing-a-playbook.md#choices-and-steps-that-depend-on-them)); a skipped step says why in the thread (`StepState.because`). Conditions are kept to one, on a choice, with no and/or, jumps back or loops: a routine a notary can read top to bottom and know what runs is the point, and the day a condition needs more, it needs a decision, not a longer line. The answer's instructions tell the model that a document saying something was decided against gives the choice's no or none option, and only silence is null, because a real care mandate's "decided not to appoint a trusted person now" was otherwise read as nothing.

**Who confirms** is set by the checkpoint ([the rule](https://github.com/suveryn/suveryn-docs/blob/main/playbooks/writing-a-playbook.md#checkpoint-a-person-confirms)), in the case's roles only: in a notarial office the case's manager is the notary, while a clerk prepares and corrects, so no notary role is added to accounts. The gateway refuses the confirmation from anyone else (`run.manager_only`); a contributor still sees every card with *Adjust* and *Fill in*, and the review says who confirms in place of the button. Deed intake lets anyone in the case confirm; the certified playbooks ask the manager.

**People answer in words.** At an `ask`, the answer is mapped to the facts asked by one plain model call (`suveryn_harness.facts.map_answer`: the facts' ids and labels, the person's words, `id: value` lines back, anything else ignored); each value is a proposed fact from that person, and the quick reply *Not known yet* leaves them unknown. At the checkpoint, a correction in words is mapped the same way over every fact plus one entry beyond the last of each list, and becomes a new version from that person (the value as read is kept and shown as "read as"); the playbook says what changed. When nothing can be placed, it says so and asks again; the facts panel's fields stay the precise way in.

**The read.** The model call is one grounded request, like a chat question but with the playbook's own instructions and no history, and without thinking. The loader derives the answer's JSON Schema from the facts (`read_schema`) and appends its shape in words to the instructions; the request carries the schema and llama-server holds the model to it by grammar, so the answer has every fact as a key by construction and a value is never taken by position. Values are strings copied as written; the harness reads them by kind and runs the check against the cited passage, as for a chat answer (`suveryn_harness.support`, `values`). Still to measure: Qwen3.8 held to a grammar on a real deed, and the time the grammar adds per read; the GPU round's runs are on fictional documents. An answer that still isn't the object is asked for once more with a stricter reminder; then the run fails with `run.answer_unreadable` and can be started again. Starting a run, or answering the request a read waits on, counts against the caller's chat rate limit. When too many runs are reading at once a new one fails with `run.too_many`. A run still reading when the gateway stops is failed as `run.interrupted` at the next start, and the hourly sweep fails one that has read for over thirty minutes, so nobody waits on a spinner for a call that no longer exists.

## The thread

Starting a run makes a conversation in the case (`conversations.run_id`; `playbook_runs.conversation_id` points back), titled with the playbook in every language (`conversations.titles`, the pack's words), its starter its owner, shared with the case from the start. It is listed, opened and named like any other conversation, with the route icon. It goes with its case, not with the conversations' keep period, "Delete history" or its owner's account, and it can't be unshared, moved, saved over or deleted on its own (stop or cancel the run).

Every conversation's turns are rows in `turns` (`conversations.py`, `TurnStore`), one per turn, stamped with who and when: a thread several people write in can't be one blob, where the last save wins. Every turn is appended by the server and never rewritten: a playbook's thread, and a conversation's questions and answers (suveryn-tracker#251). **A playbook's own turn is its meaning, never a sentence** (the handbook's decision *Meaning on the server, words at the edge*): no text, and in `meta` its kind (one of `suveryn_api_gateway/turn_kinds.json`) and its facts, values and counts. The chat UI words each in its reader's language (`src/lib/runTurns.ts`); `RunStore.say` refuses a playbook turn with text or of another kind, and both sides' tests read the kinds file. A person's turn keeps what they wrote; a button or form answer is its values, worded by the screen too. So everyone in a case reads the whole run in their own language. The playbook never writes the same line twice in a row.

Event-sourcing the run (deriving steps, facts and turns from one event log) was considered and rejected: tables a notary can read beat a log only a developer can.

## A running playbook is visible

The case lists show a chip: the playbook's title and who the run waits for ("Deed intake · waiting for Mieke", "· waiting for you" for its starter, "· waiting for a member" at the checkpoint), "· Paused", or else its step (`runChipText`; the gateway puts the playbook's title per language and the step's kind on every run it answers, so a list across cases needs no playbook lookup). The run's conversation says its status, its step, what it waits for and from whom. Statuses: `reading` (the model), `waiting` (a person), `paused`, `done`, `stopped`, `cancelled`, `failed` (with a code of the registry).

Three acts, three states:

- **Pause** keeps everything and waits. Anyone who contributes may pause and resume; a run that is reading is paused when it next waits.
- **Stop** ends early and keeps what was achieved: confirmed facts stay the case's, facts only read are superseded, a product so far stays.
- **Cancel** says the run should not have happened: every version the run established, read, answered or confirmed, is superseded (kept in the record, no longer the case's), and its product is marked `withdrawn` in its provenance, never deleted.

Stop and cancel are the starter's (by id, never by the shown name) or the case manager's. The run record always stays; nothing is deleted except with the case. **One live run per playbook per case**: a second start is refused (`run.already_going`, with the live run's id). A closed case can't start a run; a case closed while a run waits keeps the run, and the screen says to reopen the case to go on. Every act is in the case's access log: `playbook_started`, `playbook_answered`, `playbook_confirmed`, `playbook_paused`, `playbook_resumed`, `playbook_stopped`, `playbook_cancelled`.

## The data model

```text
playbook_runs   id, case_id, playbook_id, playbook_version, status, documents uuid[], language,
                started_by, starter, started_at, finished_at, confirmed_by, confirmed_at,
                step, steps, paused_by, paused_at, ended_by, ended_reason, model, error,
                result_document_id, out_of_date, conversation_id, manifest, requested, checks
case_facts      id, case_id, run_id, step_id, fact_id, kind, value, status, source, issues,
                by, at, replaces, seq
```

**The case is the container** (cases.md, decision 9): a playbook's state lives in its run, keyed by `case_id`; the case itself stays open or closed. Starting a run and confirming are a contributor's rights; a reader sees the results.

**Facts have a record of their own**: `case_facts`, one row per version, never rewritten. The model's reading is `proposed` (or `not_established` when the documents don't contain it); a person's answer is `proposed` from that person; the checkpoint writes `confirmed`, or `not_established` when the person clears it. A version that replaces another points at it (`replaces`), and the older one becomes `superseded`. So a fact's history reads in plain SQL: read as X by the model, answered Y by a person, confirmed Z by another. `Run.facts` is assembled from the current versions. Which facts recur between playbooks is still to be seen (*Open*).

**A run keeps the manifest it started under** (`playbook_runs.manifest`, written by `suveryn_playbooks.record`: facts, steps, instructions, words). Everything about that run reads its own record: the runtime's steps, the harness's read, the labels in the thread and the summary. An upgrade of the installed manifest changes nothing in a run under way, and a finished run is still shown with its own words: a new version can add or rename a list's fields, and a run's paths must mean what they meant. The installed manifest still supplies what a chip needs across many runs (titles, the kind of a step).

**Only uploaded documents are sources** (cases.md, decision 7): a run reads documents with origin `uploaded`, never an earlier run's summary, so sūveryn never cites its own output as evidence. A run holds the cited passages' text, so a document deleted after the run still shows its passage as it was read, marked as coming from a deleted document, as a saved conversation does. Deleting a document a run read marks the run `out_of_date`; the run is not deleted, because the confirmed facts and who confirmed them are the record.

**Provenance.** The run and every document a playbook produces carry `playbook_id` and `playbook_version`. A notary, an insurer or a court will one day ask which version of what read a given file; that is a liability question before it is a commercial one, and it can't be answered after the fact. The summary is named with the playbook's title in the run's language, the case's reference and the run's version ("Akte-intake 2026/0417 (1.7)"), never the version installed at confirmation: the version that read the documents is the one that counts. The summary is a document in the case with origin `playbook`, stored like an upload (listed, searchable, deleted with the case) but never a source.

**Coverage, never a block.** One function, `covered(playbook_id)`, says whether a playbook is certified and listed in the appliance's licence manifest (handbook §7). The API reports it (`covered` on `GET …/playbooks`) and the screen warns when it is false; the run starts regardless, because the licence warns and never blocks. Today it answers yes for the official playbooks and the installed packs' (the licence manifest isn't built); it is the one place the licence check will land.

## Lists

A deed's parties don't fit one line, so a fact can be a list of entries, each a record of plain values or one plain value. Lists are one level deep ([the rule](https://github.com/suveryn/suveryn-docs/blob/main/playbooks/writing-a-playbook.md#lists-and-numbers)): a deed has several parties each with a few details and no deeper, and a file an office can still write by hand stays that way.

A list's values are named by **path**: `founders[1].name`, `conditions[2]` (`suveryn_playbooks.paths`). A path is a string, so `case_facts.fact_id`, a person's answer, a correction, the confirmation, the summary's line and the screen's label all take it as they take `price`; only what a path means is new. The list's own id names the list as a whole: the read writes it as one fact not found when the documents name no entries, so an `ask` can ask about it, and the first entry a person gives supersedes that "none" (`_settle_lists`). A list with entries is shown by its entries, never by its id (`shown_facts`). People add entries at an `ask` (mapped onto the first entry) or at the checkpoint (onto one entry beyond the last); `PUT …/facts/{fact}` takes a new path into a list as new ground. Removing an entry is clearing its values. Wherever facts are counted ("12 of 13"), a list counts as one, found when it has an entry.

## Documents by name

A routine a clerk recognises asks for the bank certificate and reads it, then asks for the financial plan and reads that. A named request records which documents answered it (`playbook_runs.requested`, request step id to document ids); `min` counts those while they are still in the case. A read aimed at it reads those documents and nothing else, with a schema over its own facts. `Run.documents` is the union of what the run's reads read, for the out-of-date mark.

**A document that comes later.** The bank certificate a week after the plan: `POST …/documents` names the request it belongs to (a named one), while the run waits elsewhere or after it is confirmed; a request the run hasn't reached, or one its `when` skipped, is refused (`run.document_not_asked`). The documents are recorded as that request's, and **only the reads aimed at it** are read again: no other fact can move. The checkpoint and the summary follow again; a confirmed run is reopened, its summary out of date until the facts are confirmed again and a new summary is made (the earlier ones stay). The reading again keeps what stands: a fact it doesn't find, or finds as it stands (by meaning for an amount, a number or a date), keeps its version; one only read, or left empty, takes the new reading; one a person confirmed or answered keeps its value, and the new reading waits beside it (`case_facts.source.competes`; `RunFact.alternative`) until a person chooses at the checkpoint: a later document isn't always the right one. The checkpoint's turn counts them (`differ`). A list read again is matched to the run's entries by who they are, never by their place (`align_entries`): by a number with check digits when the entry has one, else by its first field, the name, its words in any order; an entry that matches none is new. The thread says which documents came and what is read again (`late_documents`). The screens for this (adding a document to a request already answered, the choice at the checkpoint) wait for their design board; the API is there.

**Two people at one checkpoint.** Every change to a fact is a version of its own, by name; the newest stands and the thread says "Changed". A confirmation says which state of the facts its screen showed (`Run.facts_seq`, sent back as `seen`): when a colleague changed a fact since, it is refused (`run.facts_changed`), nothing is written, and the screen reads the run again for the person to confirm what stands. Compared and written as one.

## Checks

What a notary adds up by hand: the founders' shares against the shares issued, the bank's certificate against the contribution, every condition's term before the deed. A `check` states one comparison a notary can read (`suveryn_playbooks.rules`). A manifest grows into a programming language the day a notary can't read a line and know what it does, so the rule language stays at one comparison.

The server computes, by kind, the way the check by meaning reads a value ("twintigduizend euro" counts as 20,000): the model never does arithmetic (`suveryn_harness.checks.evaluate`). A result holds, fails (both sides as computed, for the notary) or is open (a value is missing or gives no amount, number or date as written; the result names what is needed). Results live on the run (`playbook_runs.checks`) and are computed again whenever a value changes: when the check is reached, after an answer, after a correction at the checkpoint, and once more on the confirmed values before the summary. A failed check is a point for the notary and never holds *Confirm* back. The summary ends with them.

**A number that carries its own check.** A Belgian national register number, an enterprise number or an IBAN (`format`) has its check digits checked by arithmetic (`suveryn_harness.identifiers`): the national register number's 97 minus its first nine digits modulo 97 (with a 2 in front for a birth from 2000), the enterprise number's 97 minus its first eight modulo 97, the IBAN's ISO 13616 remainder. A value whose digits don't match, a typo or a scan that read an 8 as a 3, goes under *Check* (`needs: invalid_number`); nothing is blocked and no model is asked.

## A date written as a term

An agreement often gives a deadline as a term ("binnen vier maanden na de ondertekening") and a deposit as a share ("tien procent van de koopprijs"). A date fact may name the date such a term counts from (`counts_from`), an amount fact the amount such a percentage is a share of (`share_of`). When the read gives a term or a share and the run has the date or amount it rests on, the harness works the value out (`suveryn_harness.terms`), written as the document would write it ("12 februari 2027", "EUR 41.250,00"); `needs` is `computed`, and `computed` keeps the term as written, what it counted from and how. The fact stays under *Check* until a person confirms it, with how it was worked out ("Berekend: 12 oktober 2026 plus vier maanden."). What can't be worked out stays as written for a person (`not_a_date`, `not_an_amount`). An amount the document gives as approximate is read and checked like any other and goes under *Check* (`approximate`): the document isn't exact, and a person decides what it means for the deed.

## Working days

"Binnen tien werkdagen" counts working days, and which days those are differs per country and per law. So the core knows how to count them and nothing about any country: a pack brings its calendar (`calendar.yaml` beside its manifests, `suveryn_playbooks.Calendar`), the loader gives it to every playbook of the pack, and a run keeps it with its manifest. The note under a worked-out date names it ("Berekend: 23 december 2026 plus tien werkdagen (maandag tot vrijdag, Belgische feestdagen)."). A pack without a calendar leaves a term in working days as written, for a person: never counted on another country's holidays, nor on weekends alone. The calendar follows the pack, not the deed: a Belgian notary with a deed under Dutch law gets the Belgian calendar, and the note makes that visible to the person confirming. be-notary's calendar is Monday to Friday without the national public holidays; the regional holidays (11 July, 27 September) and a Saturday as a working day under the Judicial Code (art. 52) are not counted, to be confirmed by a notary.

## The manifest

A playbook is a file, not a Python module, loaded into the same `Playbook` object the gateway and the harness use (`suveryn_playbooks.manifest`). A playbook that is code can only exist compiled into the product. A playbook that is a file can be signed into a pack bundle, kept in a private repository and distributed to licensees only, uploaded to an appliance by its administrator, written by an office for itself, and shown in full to a reviewer.

The shape of the model's answer is the harness's contract with the model, not content: the loader derives it from the facts and an author never writes it. Unknown keys are errors and every error names the file and the field, because the people writing manifests by hand are administrators, not developers, and a misspelt key silently ignored is a playbook that quietly does something else. The JSON Schema for editors is generated from the loader into `packages/playbooks/schema/`, and a test keeps the two in sync. One format loads, `manifest: 3`; earlier formats were retired before any playbook was published. The questions people read are the pack's words, reviewed and translated like the labels; the model never words them.

## Where playbooks live

**Core keeps one public reference playbook**, deed intake. The certified content a licensee pays for (`pack/be-notary`: company formation and the care mandate) lives in the private suveryn-packs repository, one folder per pack, and reaches an appliance as a signed bundle beside the models. Certified partners keep theirs in their own repositories and submit them for certification. An office's own playbooks live in no repository: uploaded by the administrator and kept on the encrypted disk only (not built). The reason: a public AGPL repository can't stop updating for a licensee whose licence lapsed, and that is what protects the revenue (the handbook's commercial model).

In code, `suveryn_playbooks.packs` loads a packs directory beside the official playbooks (`SUVERYN_PACKS_DIR`; one folder per pack named as its id, `be-notary/` for `pack/be-notary`, with its manifests, its `text/`, its calendar and its case types) with the same validation, and refuses an id the official playbooks or another pack already have, a case type another source already declares, and a playbook that fits a type no source declares (*Case types* in [cases.md](cases.md)). `python -m suveryn_playbooks <dir>` checks a directory; the packs repository's CI runs it against core. Core's own tests run on a fictional test pack (`packages/playbooks/tests/fixtures/packs/be-test`, installed by the repository's `conftest.py`) that uses what company formation uses of the format with fewer facts, so the mechanism is tested without the paid content in the public repository.

## The API

```text
GET    /v1/cases/{id}/playbooks              which playbooks fit this case's type, with covered and steps
POST   /v1/cases/{id}/playbooks/{playbook}/runs    start: {document_ids?, language?}; no language: the caller's Accept-Language  (contributor)
GET    /v1/playbooks/runs/active              the live run per case the caller may read: the chip (reader)
GET    /v1/cases/{id}/playbooks/runs          the case's runs, newest first        (reader)
GET    /v1/cases/{id}/playbooks/runs/{run}    one run: step, steps, facts, turns  (reader)
POST   /v1/cases/{id}/playbooks/runs/{run}/say      {text?, documents?, unknown?}: a turn in the run's conversation  (contributor)
POST   /v1/cases/{id}/playbooks/runs/{run}/answer   {step_id, text?, facts?, none?}: an ask's facts, or a request  (contributor)
PUT    /v1/cases/{id}/playbooks/runs/{run}/facts    the checkpoint: {facts: [{id, confirmed}]}  (contributor)
PUT    /v1/cases/{id}/playbooks/runs/{run}/facts/{fact}   a card's value {value}: a new version; the same value: checked  (contributor)
POST   /v1/cases/{id}/playbooks/runs/{run}/documents  {step_id, documents, text?}: documents for a request already answered  (contributor)
POST   …/runs/{run}/pause | /resume           anyone who contributes
POST   …/runs/{run}/stop | /cancel {reason}   the starter or the case manager
GET    /v1/admin/playbooks, PUT /v1/admin/playbooks/{playbook} {active}   the administrator's list and switch
```

The playbook path segment is the id's last part (`deed-intake`); the full id is in the response. A start walks the run to its first wait and answers with it; a run in status `reading` is polled.

## The chat UI

A playbook is a conversation (`components/RunConversation.tsx`). The composer's *Playbook* menu starts a run as a new conversation in the case, or opens the conversation of its run still open; it is listed under the case, in *Recent* and in the Conversations overview with the route icon, and earlier runs are earlier conversations. The playbook speaks as sūveryn: the brand mark with the route badge and its title as speaker above each series of its turns. Its messages are short and name the problem, never a place on the screen. A quick reply (*Not known yet*) goes once the question is answered. Pausing, resuming, stopping, cancelling and confirming are centred lines; done is "Confirmed by …" in teal and the summary as a document card with its Word download. Screen by screen: [chat-ui.md](chat-ui.md), section 5.

**A read in part is said.** When a read's documents were longer than one reading takes, the playbook says so, naming them: "akte.pdf: longer than sūveryn reads at once. It read the passages that best match the facts, not every page: a fact not found may still be in them." The summary ends with the same names.

**Review is in the playbook's message.** At the checkpoint its message says how many facts were found and how many need attention, then one card per fact that needs the person, in two groups: *Check*, a value the check couldn't find literally in its passage (the sentence it comes from quoted, what isn't in it said in words, and the source), and *Missing*, a fact without a value. *Adjust* and *Fill in* turn the value into a field in the card (Enter keeps it, Esc cancels); a changed value is a new version from that person and a line in the thread; the same value says the person checked it. *Confirm the facts*, the one primary button, is held back while anything is under *Check*, with its reason; *Missing* may stay open, and confirming then records it as not established. Found and quoted facts get no card; *See all 13 facts* opens the list.

**Check by meaning.** An amount, a number or a date is compared with its passage by what it means, not letter for letter: "412.500" against "412 500", "EUR 26.800" against "zesentwintigduizend achthonderd euro", "12/05/2014" against "le douze mai deux mille quatorze" (`suveryn_harness.values`). A number is checked even when short ("3 aandelen"), which the chat's own figure check leaves alone as too ambiguous: in a playbook it was asked for. A fact of kind amount or date whose value is neither, as written, goes under *Check* with its own reason ("Not a date as written: work it out and check it"). Saying at the checkpoint that a fact already unknown is unknown is answered as such (`already_unknown`), not "That couldn't be placed". A value isn't emptied in words, as it isn't on a card.

**Every fact, in a list beside the conversation** (the source panel's place, a sheet on a phone), headed with the pack's `factsTitle`: every fact in the pack's order with its source, "From the conversation, 10:06" for a value given there, "Not known yet", or the check's warning; nothing is edited there. A source opens in the same place with a way back to the list. The header carries the conversation's state ("Deed intake · to check") and, while the run is live, a toggle "Facts · 12 of 13". The composer carries the run's chip: teal with the playbook's title, ink "… · paused" when paused, with pause, cancel (with a reason) and stop. A reader sees the thread and "Read only".

## Open

Not built, on purpose or not yet:

- `propose` (the model drafts a passage, such as the company's object, marked as the model's and confirmed by a person) and a model chosen per step: the next format, after the notary conversation.
- The Word document from the office's own template (#22): the summary is sūveryn's own layout now. How it could work, in stages, is proposed in [templates.md](templates.md), open until the first notary conversation.
- Products marked out of date when a fact they were made from changes after confirmation.
- Reading every page of a long document, rather than its best-matching passages.
- Which facts recur between playbooks (#27): `case_facts` is the record; a shared vocabulary is to be seen from the playbooks there are.
- Named subject fields on the case type (#29): the intake's facts are the first candidates.
- Facts checked by form beyond check digits (a cadastral pattern).
- An office's own playbook uploaded by its administrator, and whether it may carry its words inline in the manifest (one file to upload) rather than in a pack's text files.
- A second model pass that judges meaning ([answer-checks.md](answer-checks.md)): the rule-based check is what a run gets today.
