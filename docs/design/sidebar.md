# The sidebar: Claude's left column, in sūveryn's brand

Design for the chat UI's left column, decided with Filip on 18 October 2026 in a Design canvas
(https://claude.ai/code/artifact/51b64e95-dd2f-48e5-b248-d92945e99b96, three artboards: expanded,
collapsed rail, account menu open). The column follows the model of Claude's own sidebar (a
collapsible rail, a flat menu that expands in place, pinned items with their children underneath,
an account row at the bottom) and keeps sūveryn's brand and the UI kit in `packages/chat-ui/src/ui/`:
Inter and Space Grotesk, the orange accent with `on-accent` text, the teal only for the
"system-level" signals, Lucide icons, `radius-sm` rows, the light product theme.

## Decisions

| # | Decision |
|---|---|
| 1 | **Top strip**: the lockup (30px mark, 22px wordmark, 12px gap, unchanged) with two `IconButton`s on the right: search, and collapse. |
| 2 | **Collapsed rail**, 60px: the mark (doubles as the expand control), search, the "Nieuw" accent button, then one icon per menu item, the avatar at the bottom. Every icon-only button has an `aria-label` and a title. |
| 3 | **"Nieuw"** is one accent-filled button with a chevron; it opens a `MenuTrigger` with two items: *Nieuw gesprek* and *Nieuw dossier*. The old separate "Nieuw gesprek" button and the "Nieuw dossier" text link go away. |
| 4 | **The menu** under it is flat and each item expands in place (one React Aria `Tree`): *Gesprekken*, *Dossiers* (with a count), *Documenten*. Clicking the label opens the full view in the main area; the chevron expands the list in the column. |
| 5 | **Mijn ruimte is gone as a menu entry.** The personal space still exists in the data (cases.md): its conversations are in *Gesprekken*, its documents in *Documenten*, both marked as "not in a case" by the absence of the link badge (decision 7). |
| 6 | ***Gesprekken*** lists all the user's conversations, newest first, across cases and the personal space, with "Alle gesprekken…" at the end. It replaces the per-space conversation list and the separate "recent" idea. |
| 7 | **One visual language for "where does it live" and "who sees it".** A small teal Lucide `link` badge over the bottom-right corner of the row's icon means *in a case*; the case reference is the row's meta. The base icon says who sees it: `MessageSquare` (only me) or `Users` (shared with the case's members) for conversations; `FileText` for documents. Same badge technique as the administrator's shield on the avatar: one small "badge" pattern in the UI kit. |
| 8 | ***Documenten*** lists all the user's documents the same way (file name, case reference and page count as meta, "Alle documenten…"). |
| 9 | ***Vastgezet*** holds only the pinned cases. A pinned case is a row (reference bold, name dim, lock icon when closed) that expands to show its conversations underneath, with a hairline guide and a dot per conversation (filled accent for the current one). |
| 10 | **Every case row has a three-dot actions button** (`MenuTrigger`), shown on hover and keyboard focus: Openen, Losmaken, Leden, Instellingen, Afsluiten. |
| 11 | **Verbruik and Beheer leave the column.** They live in the account menu only. |
| 12 | **Account row** at the bottom: the `Avatar` at 32px (the "normal" size), name, "· organisation" dim, chevrons; a bordered row with the teal `--focus` ring when open. It opens a `Menu`: header (avatar as the button that opens the picture dialog, name, "· Administrator" when applicable, username · organisation); *Mijn verbruik* (the user's own tokens today as meta: personal, never the group's); *Instellingen* (everyone: picture, password); *Taal* (submenu, the `LanguagePicker`); then for administrators only, with the icon in `accent-ink` orange: *Beheer* (users, group usage) and *Playbooks*; then *Uitloggen*, and the "Documenten en antwoorden blijven op deze server" line as fine print. |
| 13 | **Avatar border is finer**: `max(1.5px, 5%)` of the side instead of `max(2px, 7%)` (ui.css, avatars.md). |
| 14 | **Playbooks are chosen in the composer**: a teal "Playbook" chip next to the case chip opens a menu listing the playbooks that fit the case type (`GET /v1/cases/{id}/playbooks`): name, one line, version, and the coverage from `covered()` as *Gedekt* (teal) or *Niet gedekt* (orange warning that never blocks). This replaces the "Deed intake" action in the case header. |
| 15 | **Administrators manage playbooks** under *Playbooks* in the account menu: per playbook name, id, version, pack, covered or not, and an *Actief* switch that decides whether it appears in the composer's menu. "Aanmaken" (an office's own playbook: name, case types, facts, instructions, labels in nl/fr/en) is wanted but pulls the manifest and pack format forward in the sequencing of platform.md; an office playbook is by definition not covered. |
| 16 | **Model chip**: a Lucide `brain` icon in `teal-ink` before the model's name when the model can think; the same icon next to each such model in the picker. |

## What maps to what in `packages/chat-ui`

- `Sidebar.tsx`: the whole column; the three sections become one `Tree` (menu) plus one `Tree`
  (pinned) and the account `MenuTrigger`. `SelectList` for the cases is replaced by tree rows.
- `ui/`: `Avatar` (size `normal` in the row, border rule changed), `IconButton`, `Button`
  (`primary` for "Nieuw"), `menus.tsx` for the "Nieuw", actions and account menus; a new small
  `Badge` overlay used by the avatar's shield and the link badge.
- `app.css`: the `.sidebar`, `.row`, `.sub` and footer rules; the collapsed state as
  `.sidebar[data-collapsed]` at 60px, remembered per browser.
- `Composer.tsx`: the "Playbook" chip; `ModelPicker.tsx`: the brain icon.
- `App.tsx`: the Documents and Cases views in the main area, opened from the menu labels;
  Administration gains a Playbooks tab.
- `i18n/*.ts`: new strings in the three languages: Nieuw, Nieuw dossier, Gesprekken, Alle
  gesprekken…, Alle documenten…, Vastgezet, Losmaken, Mijn verbruik, Instellingen, Playbook,
  Gedekt, Niet gedekt, Kan redeneren, and the actions menu.

## Open

- Playbook creation by an administrator: decide after the third hand-built playbook (platform.md).

## Resolved while building (18 October 2026)

- **Per-user pins.** A case is pinned by the user: `case_pins (case_id, user, pinned_at)`,
  `PUT /v1/cases/{id}/pin {pinned}`, anyone who may read the case; the person's own choice, so it
  isn't written to the case's access log. `GET /v1/cases` and `GET /v1/cases/{id}` carry `pinned`
  for the caller. Pinning is done from the full case list (*Alle dossiers…*, a pin on each row);
  unpinning there or from the row's actions menu.
- **The actions menu** of a pinned case: *Openen*, *Losmaken*, *Leden*, *Toegangslogboek* (the
  manager, or an administrator who isn't a member), *Afsluiten* (the manager, open case); an action
  the person hasn't the right to is shown disabled, never hidden, so the menu reads the same for
  everyone. *Instellingen* of decision 10 is left out: a case has no settings screen of its own yet
  (access and roles live in *Leden*); it comes back when there is one. The dots show on hover and
  keyboard focus of any pinned row, not only the active case.
- **The organisation** ("· organisation" in the account row and its header, decision 12) is left
  out: the product has no office name anywhere yet (the realm's display name is the nearest, and the
  gateway doesn't read it). The row shows the name, the header the name and the username.
- **The lists behind the rows** come from two new endpoints: `GET /v1/conversations?all=true` (the
  caller's own, across their space and every case they may read; never a colleague's shared one)
  and `GET /v1/documents/all` (everything they may see, each with its `case_id`). Under a pinned
  case the column shows the person's own conversations in it, and when the case is the open one
  also the ones shared with it. Each row of the three sections shows the five most recent.
- **"Mijn ruimte" without a menu entry**: *Nieuw › Nieuw gesprek buiten een dossier* (shown when a
  case is open) starts there; opening a personal conversation or document from a list goes there too.
- **The search icon** opens one search across conversations, cases and documents in the main area.
- **Trees.** The rows are an `Expander` in the UI kit (a label button that opens the view, a chevron
  that expands the panel) rather than React Aria's `Tree`: two controls in one row is what the
  design asks for, and a tree row has one.
- **Playbooks on or off** (decision 15): `playbook_settings (playbook_id, active, updated_at,
  updated_by)`, `GET /v1/admin/playbooks`, `PUT /v1/admin/playbooks/{slug} {active}`. Off, a
  playbook leaves `GET /v1/cases/{id}/playbooks` and starting a run answers 404; runs already made
  stay and can still be read.
- **"Can think"** (decision 16) is decided by model family in the engine (`ModelInfo.thinks`,
  Qwen3), since the presets disable thinking and the server doesn't report it.
