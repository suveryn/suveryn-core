# Administration

The spec for *Administration* in the chat UI (`packages/chat-ui`): what an administrator manages for
the office and the appliance, drawn on artboards 26 to 43 of the design canvas. Split from
`sidebar.md` (now [chat-ui.md](chat-ui.md)) on 28 October 2026. The colour and copy rules of
chat-ui.md section 1 apply here; this file only adds what is particular to *Administration*.

This file says how things are to be **now**; where an artboard and this file disagree, this file
wins. Interface text is quoted in English, with Dutch and French under *Strings*.

## The pages

From the build chat's brief (27 October) and the founder's decisions the same day: a side menu, nothing is
ever blocked by the support agreement, no scheduled install, and updates never uploaded through the
browser. Artboards 26 to 29 show the first pages, still with tabs; 30 to 43 are the design.

**A side menu in two groups** (built: `components/Admin.tsx`; the pages not built yet are left out):

- *Office*: Users, Cases, Playbooks, Usage, Settings.
- *Appliance*: Status, Updates and models, Backups, Network, Licence.
- A triangle beside an item that needs attention, a download icon beside *Updates and models* when
  an update is ready. *Status* opens first.
- Narrow screens (42): the menu becomes the first page, a list with the same groups; every page has
  a back arrow to it. Tables become lists, row menus and dialogs become sheets, targets 44 px.

**Status** (30): plain words, no product names.

- *Needs attention*, only when something does, each with the button that fixes it. A key test with a file
  that isn't this appliance's recovery key says so on *Backups* only ("This key doesn't open the backup. Try
  another file."), with when the right key last passed; the key's state stays that last passing test, so one
  wrong file doesn't put "the last test of the recovery key failed" here (`key_test.step: key`, `last_ok`). A test that fails on the backup itself still does.
- *Is everything working?*: answering questions (the model), reading documents, signing in
  (Keycloak), keeping your data (the database), disk space. A teal check with "Working", or an ink cross
  with "Not working since 09:12" and what still works (39). Signing in asks Keycloak each time, not a copy read at
  start, in two steps: does it answer (its discovery document), and can it sign
  someone in, which needs its database (the number of accounts, read with the directory's service
  account; Keycloak serves its discovery document while its database is down, and then every sign-in
  fails). Each answer counts 15 s. A stopped Keycloak or its stopped database shows within the minute,
  and `/health`'s `auth` says the same. The read leaves no event in Keycloak; the service account's
  token, a sign-in of its own, is fetched again only when it expires, every few minutes.
- The clock (decision, 30 October 2026; artboard 44): "On time", "via a time server" or "via the browsers"
  (the browsers of the people signed in), or how far ahead or behind it is ("95 s behind"), warned from 10
  seconds (two-step codes fail from about 30). The seconds show only when it is off, never next to "On time".
  Small differences are corrected by themselves, slowly, when the browsers agree; for a larger one, *Set to this
  PC's time*, after a confirmation that shows both times ("Appliance 13:36:09 · this PC 13:37:44") and asks
  whether the PC is right (moved forward, closed cases whose keep period has then passed are deleted within
  the hour). "Clock set." is announced to a screen reader (`role="status"`), "Not set: …" as an alert. Not
  while a time server keeps the clock. How: the gateway's README, *The clock*. When the browsers' earlier
  reports say "On time" but this PC measures it off, the row says what this PC measured, and this PC's
  measurement is reported and the checks read again.
- An overview: version, last backup, users against the agreement, support.

**Users** (32, 34): manages accounts through Keycloak's admin API, so nobody needs its console.

- The list: name and e-mail, administrator or not, last sign-in, account on or off. "12 of 15
  users" from the manifest's `users`; without a manifest, "12 users". Accounts that are off don't
  count.
- *Add user* (the page's one orange button): name, e-mail, administrator or not. **The appliance
  sends no e-mail** (no mail server, maybe air-gapped), so adding shows a temporary password once,
  with the address, to pass on (Keycloak `temporary`, `UPDATE_PASSWORD`). It has no expiry: it works
  until its first use. The person chooses a password at first sign-in, and sets up two-step sign-in
  then too when the office requires it (Settings).
- The row menu: make administrator or remove the rights; have the password set again (a new
  temporary password, as above); have two-step sign-in set again; sign out everywhere; switch the
  account off, or on again; and, only once it is off, *Delete account*.
- **Switching off someone who manages cases** hands each case over inside the dialog, showing only
  the case's reference and name. The button waits until every case has a new manager: the one
  thing that can't be done. The person stays a member.
- **Always one administrator**: the menu item is disabled with the reason under it ("You are the
  only administrator…"), not an error afterwards. Removing your own rights says that
  *Administration* closes for you.
- **More users than agreed** shows a triangle by the count and one sentence in the add dialog.
  Adding still works.
- *Sign-ins and changes*: Keycloak's sign-in and admin events in plain words, kept 180 days.
- **Through Keycloak's admin REST API**, called by the gateway with the signed-in administrator's own
  access token, never by the browser and with no service-account client of its own. The `suveryn-admin`
  role carries `manage-users`, `view-users`, `view-realm` and `view-events`, and `manage-realm` for the
  two-step setting only (decision, 30 October 2026), so Keycloak's admin events name the administrator who
  made each change:
  - list: `GET /users`; last sign-in from the `LOGIN` events (Keycloak keeps no such field): the newest
    2,000, then one `GET /events?user=` for each account not among them; with none found, an account older
    than the 180 days of events kept reads "not in the last 180 days", a newer one "never" (external
    review, pass 7);
  - add: `POST /users` with `requiredActions` `UPDATE_PASSWORD` (and `CONFIGURE_TOTP` while the office
    requires two-step sign-in), then
    `PUT /users/{id}/reset-password` with `temporary: true`;
  - administrator: realm role `suveryn-admin` through `/users/{id}/role-mappings/realm`;
  - off or on: `PUT /users/{id}` with `enabled`;
  - reset password: `reset-password`, temporary; reset two-step: delete the `otp` credential, and add
    `CONFIGURE_TOTP` while the office requires two-step sign-in;
  - two-step for everyone (Settings): first the realm's browser flow, its two-step sub-flow and OTP form
    `REQUIRED` (off: `CONDITIONAL` and `ALTERNATIVE`, as Keycloak makes them), so the code is asked at
    every sign-in and removing one's app doesn't get round it; then `CONFIGURE_TOTP` added to every account
    without an `otp` credential, or taken away from every account when turned off;
  - sign out everywhere: `POST /users/{id}/logout`, and the gateway ends the account's own sessions at
    once (also when it is switched off or deleted);
  - delete: `DELETE /users/{id}`, after the account's own space is deleted. Every store is reached first,
    so a store that is down deletes nothing. A step that fails after that (a store, or Keycloak itself)
    answers 503 with reason `unfinished`, in its own sentence: the account is still there, switched off,
    part of its own space may be gone, and deleting again finishes it, as every step is repeatable
    (external audit, 29 October; tested with each step failing);
  - events: `GET /events` and `GET /admin-events`.
  The gateway enforces "always one administrator" and the case hand-over before switching off. The check
  and the change that could leave no administrator (rights removed, an account switched off) happen one at
  a time in the gateway, so two administrators removing each other at once leave one. Keycloak judges every call by the caller's rights as they are now, so an administrator whose
  rights another removed meanwhile is refused even though their session still says administrator; the
  gateway asks the directory's service account whether they still hold the role, and says "Your
  administrator rights were removed meanwhile" (403, reason `rights_removed`) rather than the sentence
  for a role that lacks a permission, which asks them to contact support. This
  replaces a separate *Activity* page. Nothing from inside a case.

**Settings** (35): what the office decides, in one place. Who sees a case, how long closed
cases and conversations are kept, whether two-step sign-in is required for everyone (off by default:
Decision, 29 October 2026; on asks everyone for a code at every sign-in, and whoever has no authenticator app
sets one up first; the confirmation says so), and the rates for the indicative cost. *Cases* and *Usage* then
only show these, with "Change in Settings". *Save* is active after a change, and a shorter keep
period asks for confirmation with the number of cases or conversations that will go.

- *Who sees a case* applies to new cases or, by choice, to all cases. *All cases* asks for
  confirmation with the count ("38 cases become visible to everyone in the office"). Strictly
  confidential cases never change with it; their members decide.

**Backups** (36) become editable here, not in Settings: they belong with the backup's status and
test.

- *Back up now* (primary), with "Next: tonight at 02:00." beside it. A backup closes nobody out.
- *Every day at*: the time of the daily run, 02:00 by default, in whole hours.
- No "last failed" card (built on 29): a failure of the latest run shows in *Last backup* and on *Status*; an older one is history.
- The target after setup: USB disk (the detected disk) or network share (SMB or NFS: address,
  user, password, *Test connection*), with the setup's cards, fields and strings. Old backups stay
  where they were.
- Retention: 14, 30, 90 days or 1 year.
- **The recovery sheet**: the appliance holds only the public half of the key, so it can never
  print the key. *Print the recovery sheet* prints what it knows (appliance name and ID, where the
  backups are, the key's fingerprint, the restore steps) and a box "Key kept at:" (39). *Make a new
  recovery key…* creates one in the browser, as setup does; only then can the sheet be printed once
  with the key. Older backups still need the old key, and the confirmation says so.

**Licence and support** (37): what differs from the agreement first (more users than agreed, a
missed check-in, an expiry), each in ink with a way out, and "Nothing is blocked". Then the
agreement from the manifest (edition, users, valid until, next check-in), the QR code for the
quarterly check-in, the appliance ID and key fingerprint with *Copy*, and the manifest drop zone.
Uploading the manifest in the browser is fine: it is a small text file, checked on the appliance,
with the setup's four errors.

**Updates and models** (33, 38, 41), depending on #40, which isn't built: until it is, the page
shows the version and the models only.

- Connected: the appliance downloads by itself. Air-gapped: a USB stick plugged into the appliance,
  which the page finds as *Backups* finds a disk. Never an upload in the browser. Either way the
  signature is checked first; a bad one says nothing was installed.
- "New in 1.5.0" comes from the signed bundle itself, in en, nl and fr, so an air-gapped office
  sees it as soon as the stick is found and checked. Without a stick, an air-gapped appliance doesn't
  know a new version exists.
- The administrator chooses when: *Install now…* confirms with what happens (a fresh backup, about
  20 minutes, everyone can still work; then everyone is signed out for about 15 minutes; a restart)
  and who is signed in now. No scheduled install.
- Sign-in shows "sūveryn is being updated. You can sign in again around 11:20."
- If the new version doesn't come up healthy, the appliance goes back by itself and says so, naming
  which check of *Status* failed ("Reading documents didn't work"); details are in the log. If the backup first fails, nothing is installed: impossible, so it blocks.
- **Expired support doesn't block an update**: the page says it and installs anyway.
- *Models*: the list, the default, and *Load model bundle* from a USB stick.

**Network** (31): not in the brief, but setup promises "you can change this later in the admin
dashboard". Name and address read-only (console option 2); connected or air-gapped; outgoing to
approved destinations only or everything; sūveryn's destinations locked, the office's own
removable; the daily check.

**Playbooks** (28), as built:

- The list: name, id, version, pack, covered or not.
- An *Active* switch per playbook (`playbook_settings`, `GET /v1/admin/playbooks`,
  `PUT /v1/admin/playbooks/{slug} {active}`).
  - An inactive playbook leaves the composer's menu, and starting it answers 404.
  - Runs already made stay readable.

**Creating a playbook** (an office's own: name, case types, facts, instructions, labels in nl, fr
and en) is wanted, but it pulls the manifest and pack format forward (platform.md). An office
playbook is never covered.

**Charts on Usage** (26) use the chart palette (chat-ui.md section 1): input violet, output ochre; per kind
violet, ochre, sky blue.

**Privacy on every one of these screens**: an administrator who isn't a member of a case sees only
its reference and name. Counts, never content.

**States** (39): loading as `surface-alt` shapes with `aria-busy`; errors as what failed, what
follows, and one way out; empty states as one sentence and the action that fixes it. Dark: 40 and
41 (dialogs on `surface-alt` with a `line` ring in the dark theme).

## Strings

The strings are in `packages/chat-ui/src/i18n/` (`en.ts`, `nl.ts`, `fr.ts`), the one source. Copy for pages not built yet (*Licence*, *Network*, *Updates and models*) is on artboard 43 of the design canvas, not repeated here.

## Decided (28 October)

- **Nothing is blocked by the agreement**, updates and model bundles included. appliance-architecture.md
  (suveryn-appliance) and the setup's `skipNote` now say so.
- **Everyone sees the notice**: without a manifest after 14 days, every deviation from the agreement,
  and again when support ends.
- **The certificate's expiry** appears on *Status* when it nears (with #41's work, suveryn-tracker).
- **Deleting an account** (29 October): an administrator can, as a second step once the account is off (so
  its cases are handed over already); not their own. Its own space goes with it: its documents outside a
  case, the conversations nobody else can read, its picture and pins. What it did in its cases stays there
  under its name: documents it added, conversations it shared, the access log. Usage keeps its counts.
- **Text actions are orange** (29 October), as the brand says: Remove, Undo, Hand over, Look again, Change in
  Settings… Cancel and Close stay ink.
- **Status shows the version** (29 October): the release and the core commit, without a setting.
- **The order of a new account's first sign-in** (two-step first, then the password: Keycloak's) is fine for now.
- **The dark theme waits**: the chat UI has none yet, so the dark artboards aren't built.
- The update durations (20 and 15 minutes) stay estimates for #40 to confirm, and the place on
  suveryn.com where an appliance learns of a new version isn't designed yet.

## As built

- The side menu (and the narrow list): *Users*, *Cases*, *Playbooks*, *Usage* and *Settings* for the
  office, *Status* and *Backups* for the appliance; *Updates and models*, *Network* and *Licence* join as
  their pages are built. *Status* reads `GET /v1/admin/status` (the
  gateway checks every minute, so "since" is when a failure began); the overview shows the version when
  the appliance has one (its release and the core commit, or `SUVERYN_VERSION`; decision, 29 October), and the
  last backup. Users against the agreement and support join
  with *Licence*. A full disk says "Almost full" (a string the table didn't have).
- *Users*, as the administrator who is signed in (decision, 28 October: no extra client; the gateway's
  README). Built as drawn, with these
  differences: the temporary password has no expiry (decision, 28 October: Keycloak is the password
  manager and can't expire one password; it works until its first use, and one never used shows as
  "never" signed in), so the pass-on dialog has no "Valid until"; *Sign-ins and changes* takes the changes from Keycloak's
  admin events, which name the administrator but hold no details, so switching an account off or on reads
  as "Account changed"; the dialog titles, the event lines and the filter
  needed strings the table didn't have; *Delete account* in the row menu once an account is off (decision, 29 October); the Dutch and French texts that named a person "haar", "hij",
  "ze", "il" or "elle" (drawn for one example person) use the name or "de" instead, since an account
  has no known gender; the "Advanced: open Keycloak" link isn't built, as nobody should need it.
- *Settings*: who sees a case, the two keep periods and the indicative cost's rates, one *Save* for all;
  *Cases* and *Usage* only show them, with "Change in Settings". Differences: "New cases" keeps the
  existing cases with their members by restricting those that followed the default (the case model has no
  other way to hold "as it was"); "All cases" also opens cases a manager restricted, as drawn, with a line
  in each access log; closing to the members needs no choice (it applies to every case that follows the
  default) but is confirmed with its count too; a shorter period for closed cases deletes nothing at once
  (it applies to cases closed from then on, cases.md), so only conversations are counted.

- *Backups*, editable: *Back up now* with when the next one runs, where (the USB disk, or a share whose
  *Test connection* now signs in and writes a test file: the setup's only saw whether the server answered),
  *Every day at* (whole hours, 02:00 by default) and *Retention* with one *Save*, and the recovery sheet
  with *Make a new recovery key…*. The gateway can't change the appliance's backups itself: each change is
  a request its backup service checks as the setup does (suveryn-appliance `backup/README.md`). Since /etc
  is read-only, the hour is in the backup settings and the timer runs hourly. Differences: the sheet shows
  the appliance's address, not its ID (that comes with the manifest, #41), and the key's fingerprint is
  its public half shortened, as on the key file's "public key" line; the existing status and the key test
  stay as they were, so a failure still shows in the notice at the top. The share test signs in and writes and removes a test file; the setup's own only checks that the server answers.
