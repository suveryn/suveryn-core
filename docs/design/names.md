# Names

How sūveryn names two things: an **operation** (what the gateway can be asked to do; its name is what the chat
UI's generated code will call it by, once that code is generated: suveryn-tracker#159) and a **code** (what went
wrong or needs checking; [messages.md](messages.md)). A code's name is permanent once released; an operation's
isn't yet (*Released*, below). The founder's decision of 15 November 2026, after independent reviews
(suveryn-tracker#159, #161, #162).

**Released.** A code is released when it is on the list of released codes (`messages-released.json`). A released code is never
renamed, removed or reused: codes are stored (a document that couldn't be read,
a run that failed), so an old case and a restored older backup must still be read. `packages/harness/src/suveryn_harness/messages-released.json` lists the released codes, and a test fails when
one of them is no longer in the registry. It is added to in the change in core that an appliance leaving Sūveryn
Labs, a pilot included, is to pin: `uv run python -m suveryn_harness.released`. For the version that goes to the pilot, that is just before its last regression round. A code that round finds to rename may come off the list again, as long as nothing has left Sūveryn Labs: by hand, in the fix, whose PR says so; the new name goes on the list before the next round. Nothing checks this but care. Nothing is released yet. The
founder's decision behind this is the handbook's [*names and the pin*](https://github.com/suveryn/suveryn-handbook/blob/main/decisions/2026-11-15-names-and-the-pin.md).

An operation's name is not frozen. It is stored nowhere, and the chat UI is built from the same commit as the
gateway, so a rename reaches both at once (the founder's decision of 15 November 2026). That changes the day
something outside sūveryn calls the gateway (a connector, a partner's tool, an office's script): from then a
released operation is never renamed, and a list and a test guard it, as for codes.

This is about names. A **web address** (`/v1/chat`, `/health`) is another matter and is not free to change: the
appliance is pinned to one core commit and calls the gateway by address (its web server's rules for `/health`,
`/v1/chat` and `/v1/documents`; provisioning's checks of `/auth/…` and `/v1/documents…`), so a changed address
doesn't reach it at once, and for the streaming rules it wouldn't even fail: it would silently stop streaming. An
address changes in both repositories together.

**What a test can't check.** For operations, tests stop a verb that doesn't fit what the request does (a read named as a change, a delete not named as one), and an old word (`avatar`, `job`) (`tests/test_description.py`); for codes, a test stops a banned word and an ending that isn't on the list. Whether
a name is true, says what it is about, and is in the right area or group is read from the code that says it, by
whoever reviews the change.

## Words used the same way everywhere

| Word | Means |
|---|---|
| **user** | A person of the office, as others see them: in the list of people, as a case member, with a picture |
| **account** | That person's sign-in account, as an administrator manages it: created, switched off, password reset, deleted |
| **picture** | A person's picture (never "avatar") |
| **upload** | A file that was sent and is waiting to be read, being read, or couldn't be read. The file that was read is a **document**; the reasons a file couldn't be read are still the `document` area's codes, since they are about the file as a document |
| **office** | The whole office, for administrators (`list_office_cases`, `get_office_usage`) |
| **my** | The caller's own (`get_my_usage`, `delete_my_conversations`) |
| **all** | Everything the caller may see, across cases (`list_all_documents`): never "the whole office" |

## The convention for codes

- **Shape**: `area.condition`, lower case.
- **The condition states a fact about what is wrong**: not what to do about it, not a status number.
- **The thing first, then what is wrong with it** (`share_unreachable`, `pages_too_many`). The patterns that read the other way stay as they read: `not_a_<thing>`, `no_<thing>`, `<role>_only`, `already_<state>`, `not_<state>`.
- **A part that has its own area says `unavailable` under that area** (`model.unavailable`). The `system` area is for what has no area of its own: `system.internal` (nobody planned for it), `system.unavailable`, `system.database_unavailable`.
- **A code ends in one of the listed endings**, each with one meaning:

| Ending | Means |
|---|---|
| `unavailable` | A part of sūveryn is down |
| `unreachable` | Something outside sūveryn can't be reached (a share, a disk) |
| `not_found` | What was asked for doesn't exist, or isn't the caller's to see |
| `missing` | Something required wasn't given |
| `gone` | It was there and isn't any more |
| `invalid` | It was given, in a form that can't be used |
| `mismatch` | Two things that must fit each other don't |
| `unsupported` | A kind sūveryn doesn't handle |
| `not_a_<thing>` | The file given isn't the thing asked for |
| `out_of_range` | A value is outside what is allowed, too small or too large |
| `too_large`, `too_many`, `too_long`, `too_short`, `too_slow`, `too_new` | A limit was crossed, on one side |
| `unreadable`, `damaged`, `empty`, `expired`, `changed`, `full`, `busy`, `exists`, `protected`, `removed`, `unsafe`, `outside`, `unclear`, `mixed`, `low`, `recovered` | As the words say |
| `refused` | Another system said no |
| `failed` | Something sūveryn was doing stopped |
| `unfinished` | It stopped partway, and doing it again finishes it |
| `<role>_only` | Only the roles named may do this (`manager_or_administrator_only`) |
| `no_<thing>` | It has none |
| `already_<state>` | It has been done, or is going, already |
| `not_<state>` | It isn't in the state this needs (`not_switched_off`, `not_writable`) |
| a state: `paused`, `ended`, `closed`, `synced`, `started`, `signed_out`, `interrupted`, `moved_on` | It is in a state that doesn't allow this |

- **Eleven codes state a fact in words of their own**: `case.single_manager`, `case.strictly_confidential`, `conversation.in_case`, `account.last_administrator`, `account.own_account`, `account.manages_cases`, `calc.division_by_zero`, `document.instruction_like_text`, `setup.password_common`, `setup.password_personal`, `setup.manifest_other_appliance`.
- **The seven general codes** of the `request` area keep the names of the web's own statuses.
- **What enforces it.** A test (`packages/harness/tests/test_messages.py`, which holds the list of endings): a code ends in a listed ending or is one of the eleven; a new ending is added on purpose in the same change, to the table above and to the test, which fails when the two differ; every area has codes, kept together in the areas' order; banned words fail (`too_big`, `none_found`, anything ending in `_first`); a released code that is no longer in the registry fails. The test stops banned words and lost codes. Whether a name is **true**, says **what**, and is in the **right area** is checked by the reviewer, who reads the code that says it: no test can.

## The convention for operations

- **A verb, then what it acts on**: `list_cases`, `get_case`, `close_case`.
- **Fixed verbs**, tied to what the operation does:

| Verb | Means |
|---|---|
| `list_` | Many things come back (a read) |
| `get_` | One thing, or one state, comes back (a read) |
| `preview_` | What a change would do, without doing it (a read) |
| `create_` | A new thing is made |
| `update_` | Some of a thing's fields change; the others stay |
| `set_` | One value is put in place: on or off, a role, a figure, a picture |
| `delete_` | A thing is gone for good |
| `remove_` | A thing is taken out of a group it was in (a member from a case) |

- **An ordinary verb for an action that isn't one of those**, when it does one thing only: `close_case`, `pause_run`, `test_recovery_key`. An operation that turns something on **and** off is `set_…` (`set_case_pinned`, `set_conversation_shared`).
- **`my_`, `office_`, `all_`** as in the table of words.
- **The name is the server function's own name.**
- **What enforces it.** A test: a read starts with `get_`, `list_` or `preview_` and nothing else does. As for codes, whether a name is true is the reviewer's to check.

## The groups of operations: thirteen

Called groups, not areas ("area" is the codes' word): `auth`, `answers`, `models`, `cases`, `settings` (the office's settings), `playbooks`, `documents`, `conversations`, `users` (people, pictures and accounts), `usage`, `backups`, `clock`, `status`.

Three groups hold operations that live in another group's module: the office's people (`users`) and the office's
settings (`settings`) are in `routes/cases.py`, the installed models (`models`) in `routes/health.py`, each on a
router of its own that carries the group.

## Still to name

Settled as their own later changes: the words stored in the database (the access log's
actions, the states of runs and uploads: suveryn-tracker#159), the names of each operation's inputs (`case_id` and
`case` for the same thing), the field names inside answers, the names of the values inside codes (`n`, `max`), the
names of the data shapes, and the web addresses that no longer match their operation (`/auth/logout`, `/v1/chat`,
`/v1/admin/cases/settings`, `/v1/documents/jobs/…`, `…/avatar`), which the appliance's web server and checks use too.
