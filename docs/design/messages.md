# Messages: what the server says when something goes wrong, or needs checking

The handbook's decision of 12 November 2026, [*Messages are codes*](https://github.com/suveryn/suveryn-handbook/blob/main/decisions/2026-11-12-messages-are-codes.md),
as it is built here (suveryn-tracker#139; the appliance's web setup, #141). In one line: **the server sends, stores and logs a code with parameters,
never a sentence, and each screen words the code in its reader's language.**

## The four kinds

By what the person can do, not by how bad it is.

| Kind | Meaning | The person | Travels |
|---|---|---|---|
| `refused` | Nothing was done, nothing changed | Fixes the input, waits, or asks someone with the right | Instead of the answer, HTTP 4xx |
| `unavailable` | A known part is down (the database, the model, sign-in, a disk) | Waits, or tells the administrator which part | Instead of the answer, HTTP 5xx; or stored as a run's or an upload's error |
| `internal` | Nobody planned for it: a bug, a file that should be there | Reports the reference | Instead of the answer, HTTP 500, with a reference |
| `warning` | It was done, and something should be checked | Checks it | Inside the answer, never as an error |

## The registry

[`packages/harness/src/suveryn_harness/messages.json`](../../packages/harness/src/suveryn_harness/messages.json) lists
every code. It is the contract: the server may only use a listed code, the chat UI's build fails on a listed code
without words in every language, the appliance's web setup reads it from the core on the appliance and keeps no list
of its own, and a partner gets it with the API. A line:

```json
"upload.too_large": {"kind": "refused", "status": 413, "title": "The file is larger than `max_mb`.",
                     "params": {"max_mb": {"type": "number"}}, "since": "0.2.0"}
```

- **Name:** `area.condition`, lower case, two levels. The areas are a short fixed list at the top of the file. The
  kind is not in the name.
- **`kind`** is chosen by what the person can do, never by how the message travels: `refused` (nothing was done),
  `unavailable` (a known part is down), `internal` (nobody planned for it), `warning` (done, check something).
  It fixes the status range when the code takes an answer's place: `refused` 4xx, `unavailable` 5xx, `internal`
  500. A refusal or a part that is down can also be an upload's or a run's stored error: such a code has no status
  and keeps its kind (`document.password` is refused). A warning never has a status.
- **`title`:** English, for a developer reading the registry or an answer. Never shown to a person.
- **`params`:** each with a type (`number`, `string`, `id`). Raw values only: the reader's locale formats a number or
  a date, and an id becomes a label on the screen. `"private": true` marks client data (a file name, a case
  reference): it is never logged (`messages.loggable`).
- **`retry`:** trying again can help.
- **`since`:** the gateway version the code arrived in.

**A code, once released, is never renamed or reused.** A wrong name is retired and a new code added. Many refusals
are one situation seen from a screen that is out of date ("the run isn't waiting", "this step takes no answer"):
those share one code. A code is added for what a person can meet and act on, not for every sentence.

## On the server

`suveryn_harness.messages` is the one way to use a code:

- `message(code, **params)` gives `{kind, code, params}`, for a message inside an answer or stored (a calculation
  that couldn't be done carries its `code`).
- `raise Problem(code, detail, **params)` takes the answer's place. `detail` is English, for developers.
- A code that isn't listed, or a parameter it doesn't have, is a programming error at once.

The gateway (`problems.py`) answers every refusal and failure as Problem Details (RFC 9457,
`application/problem+json`):

```json
{"type": "urn:suveryn:problem:upload.too_large", "title": "The file is larger than `max_mb`.", "status": 413,
 "detail": "The file is larger than 100 MB.", "kind": "refused", "code": "upload.too_large", "params": {"max_mb": 100}}
```

`type` is a URN, a name and not an address: an appliance is offline. Three ways lead to this one shape:

1. A `Problem`: its own code.
2. A plain `HTTPException`, from code not yet moved to the registry: the general code of its status
   (`request.conflict`, `request.not_found` …), its English detail kept for developers. The page shows the general
   code's words, never the detail.
3. Anything unplanned: `system.internal` with a reference such as `7F3K-92QD` in `params.ref`. The log line has the
   reference, the request, the exception's type and where it was raised; never the exception's message, which may
   quote a document or name a file.

A request that doesn't validate is `request.invalid` with `errors` (where and what, never the values sent).

## On the screen

`packages/chat-ui/src/lib/messages.ts` words a message from the language tables (`messages`, `messageAreas`,
`messageKinds` in `src/i18n/<lang>.ts`): the code's own words, else its area's, else its kind's. So a code newer than
the screen still gets a sentence in the reader's language. The tables are typed from the registry, and
`messages.test.ts` fails on a code, area or kind without words in a language. An answer that isn't the gateway's (a
proxy's 502) gets its status's general code.

## The appliance's web setup

The setup's API is not the gateway: it is a small service in suveryn-appliance (`setup/suveryn-setup`) that runs
before there is a database or a sign-in. It says the same thing in the same shape (suveryn-tracker#141):

- Its codes are the registry's `setup` area, said through this package's `messages.py`, which the service loads
  from the pinned core at `/opt/suveryn/core` (the module uses the standard library only, and must stay so): one
  list, and the same Problem Details as the gateway's. A new setup code is merged here first and reaches the
  appliance when its pin moves. An answer refused field by field is `request.invalid`
  with `fields`: `{"password": {"kind": "refused", "code": "setup.password_short", "params": {"min": 15}}}`.
- What is stored or travels inside an answer is a message, `{kind, code, params}`: a share's test, why a restore's
  check failed, the step where provisioning stopped (`setup.provisioning_failed`, its `step` an id the screen names).
- Anything unplanned is `system.internal` with a reference, logged by the service with the request, the exception's
  type and where it was raised, never its message. The screen says the reference instead of "HTTP 500".

Two screens word codes, each for its own reader. The chat's tables (`src/i18n/<lang>.ts`) word every code but the
`setup` area; the setup's tables (`src/setup/i18n/<lang>.ts`) word that area in full sentences that speak of the
appliance and the partner, and its own `messageKinds` say anything else. Both meet the backup service's codes
(Administration › Backups; a restore in the setup): those are worded once, in `src/i18n/backups/<lang>.ts`, which
both tables take, and the setup says three its own way. `setup/screens.test.ts` fails on a `setup` or `backup` code
without words in a language, and on words for a code the registry doesn't list.

## The appliance's helpers: backups and the clock

The backup service and the clock helper are small programs in suveryn-appliance that run as root and answer through
files the gateway reads (suveryn-tracker#154). They keep no list of their own: they say codes of the registry's
`backup` and `clock` areas, loaded from the pinned core as the web setup does, and write them as they are.

- A helper writes a message where it wrote a word: `failure`, `{code, params}`, in a backup's status
  (`last_error`), a key test's result, an answer to a request; `fields`, a message per field, for a form it refuses.
- The gateway passes it on and decides nothing: `messages.stored` reads it against the registry as it is today (its
  kind comes from the registry, not from the file), and a code the registry doesn't know becomes `system.internal`.
  A playbook run's stored failure is read back by the same function.
- One code for one situation, whoever meets it: `backup.wrong_key` is the key test's answer in Administration and
  the restore's in the web setup. The codes the setup used to say for these (`setup.share_…`, `setup.restore_…`,
  `setup.key_invalid`, `setup.disk_gone`) were renamed before any release; from the first release a code is never
  renamed.
- A backup that fails on something nobody planned for (the database can't be dumped, encryption fails) is
  `system.internal` with a reference the backup's own log has.
  A failure the administrator can be told about has a code of its own: a link in a settings folder that a restore
  would refuse is `backup.unsafe_link` (a VM regression found the page saying "an unexpected error" for it).
- The gateway's own refusals for these pages are codes too: `backup.unavailable`, `backup.busy`, `clock.synced`,
  `clock.busy`, `clock.measurement_slow`, `clock.unavailable`.

## Moving the rest over

The foundation moved what already had a code: uploads, the busy and too-large refusals, the parts that are down, a
calculation's reason. The gateway's 138 plain refusals moved area by area, and none is left:

- `api-gateway/tests/test_problems.py` fails on a plain `HTTPException` anywhere in the gateway: a refusal is a
  `Problem`.
  Playbook runs (suveryn-tracker#150), cases, conversations, users and the checks every route shares (#151),
  documents (#152), answers (#153), backups, the clock, Status and usage (#154).
- **How an area moves, as playbook runs did.** A refusal a person can meet and act on gets a code of its own (a run
  is paused: `run.paused`; it has ended: `run.ended`; only the case manager confirms: `run.manager_confirms`).
  The many refusals that are one situation, a screen that is behind the run, share one (`run.moved_on`). What only
  a programming error or a deleted thing leads to takes the general code (`request.invalid`, `request.not_found`),
  written as a `Problem` so its English detail is still there for a developer.
- **What catches a refusal catches a `Problem`.** Two places act on a refusal from a shared check instead of passing
  it on (a conversation in a case the caller may not see reads as missing; a contributor may delete their own
  noticed upload). They catch `Problem` and read its `status`.
- **A failed reading says why as a code** (#152). A job that failed carries `failure`, `{kind, code, params}`,
  made at the API's edge from the reader's own reason (`suveryn_rag.reading.CODES`; a test holds the two together):
  a reason the reader knows is **refused** (`document.password`, `document.too_many_pages` with `pages` and `max`
  …: nothing was read, the person gives another file), and a crash nobody planned for is **internal**:
  `system.internal` with a reference, logged with the exception's type and where it was raised, never its message.
  The English `error` stays beside it for developers.
- **What a reading noticed is a warning of the registry** (#152). The document was read and something should be
  checked: `document.page_coverage_low`, `document.layout_failed`, `document.instruction_like_text`,
  `document.text_recovered`, `document.text_layer_recovered`, `document.furniture_restored`, each with its `page`.
  They are stored with the document and sent as `{kind, code, params}` (and `detail`, English, for developers),
  as every message is. The page says each code once for all its pages, in the code's own sentence; the card and
  the overview have shorter forms of their own, and a warning newer than the page is still said, by its kind's
  words. A document stored before this keeps its status and shows no notes until it is read again.
- **What only the page says isn't in the registry.** "This page lost track of the upload" is the page's own
  sentence (`uploadLost`), said when an upload's job is gone; the server never sends it.
- **An answer that fails says why as a message** (#153). The stream's `error` event is `{kind, code, params}`
  (and `detail`, English): `system.model_unavailable`, `system.documents_unavailable`, `answer.document_gone`, or
  `system.internal` with a reference. The page keeps the message with the turn, so a saved failure is worded again
  in the reader's language of the day it is shown. "The connection closed before the answer was complete" is the
  page's own sentence: the server never says it.
- **A run that failed stores why as a message** (#153): `failure`, `{kind, code, params}`, kept as its code and
  parameters (rule 6). By what the person can do: `system.model_unavailable`, `system.documents_unavailable` and
  `run.interrupted` (a part was down: try again), `run.document_missing`, `run.unreadable_answer` and `run.busy`
  (nothing could be read), `system.internal` with a reference (nobody planned for it).
- **One code for one situation.** The model that can't be reached is `system.model_unavailable` wherever it is met:
  asking, a stream, a playbook's reading, an answer given in words. It answers 503 everywhere (asking answered 502).
  Its sentence is the one the playbook's board shows (P04) and the banner uses: "The model isn't available right now."
- **An unplanned failure is logged alike everywhere**: `suveryn_harness.messages.unplanned` gives the reference and
  where the exception was raised, for an HTTP answer, a stream, a run and a reading. The log line has the
  exception's type, never its message.
- Still under their own names: the answer's checks, which are warnings (#157), and a few lists a part keeps for
  itself (#158).
- The appliance's console (its installer, and its screen after installation) says the registry's codes too
  (suveryn-tracker#160; the founder's decision of 15 November 2026): the areas `network` (a network setting it
  refuses) and `bundle` (a bundle on the stick it can't trust), named for what they are about, since the installer
  and the installed appliance meet the same situations. An installation that stops on something nobody planned for
  is `system.internal` with a reference the installer's log has. Its words stay in suveryn-appliance's
  `installer-text.json`, the console's language file: the chat and the web setup don't word these two areas.
- Status shows recent references to the administrator, with the support request: with the appliance's part.

Keycloak's own pages and e-mails keep Keycloak's message files; this is for what sūveryn's server says.
