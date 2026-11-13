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
- **`kind`** fixes the status range: `refused` 4xx, `unavailable` 5xx, `internal` 500, `warning` none.
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
appliance and the partner, and its own `messageKinds` say anything else. `setup/screens.test.ts` fails on a `setup`
code without words in a language, and on words for a code the registry doesn't list.

## Moving the rest over

The foundation moved what already had a code: uploads, the busy and too-large refusals, the parts that are down, a
calculation's reason. What remains is counted, and the count may only go down:

- `api-gateway/tests/test_problems.py`, `PLAIN_REFUSALS`: the plain `HTTPException`s still in the gateway. A PR that
  moves an area lowers the number; a new refusal is a `Problem`.
- Still under their own names, each its own issue: an upload job's `error_code` and the warnings of ingestion, a
  run's stored `error`, the chat stream's `failure`, the answer's checks, backups and the clock. The backup service's
  codes (`login`, `write`, `unreachable` …) are worded for Administration › Backups from `backupErrors` in the setup's
  tables until then.
- The console installer is not a server and keeps its own text file (`installer-text.json`, its keys are its codes);
  its engine gives the screens a code, not an English sentence to recognise (suveryn-appliance, #141).
- Status shows recent references to the administrator, with the support request: with the appliance's part.

Keycloak's own pages and e-mails keep Keycloak's message files; this is for what sūveryn's server says.
