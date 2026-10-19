# The sidebar: Claude's left column, in sūveryn's brand

Design for the chat UI's left column, decided with Filip on 18 October 2026 in a Design canvas
(https://claude.ai/code/artifact/51b64e95-dd2f-48e5-b248-d92945e99b96, five artboards: expanded,
collapsed rail, account menu open, the Documents overview, the Cases overview). The column follows the model of Claude's own sidebar (a
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
| 13a | **The avatar badge is an orange outline, and it says what the person is in the context where the avatar appears.** One badge shape: a small disc in the surface colour over the bottom-right corner, a Lucide icon in `accent-ink` as an outline, no fill. Three icons: `shield` for an administrator (the account row, the directory), `folder` for the manager of a case (the case's member list, the Cases overview), `message-square` for the owner of a conversation that is shared with a case (next to the shared conversation, in its header). A person can carry one badge at a time, the one that matters where the avatar is shown. |
| 14 | **Playbooks are chosen in the composer**: a teal "Playbook" chip next to the case chip opens a menu listing the playbooks that fit the case type (`GET /v1/cases/{id}/playbooks`): name, one line, version, and the coverage from `covered()` as *Gedekt* (teal) or *Niet gedekt* (orange warning that never blocks). This replaces the "Deed intake" action in the case header. |
| 15 | **Administrators manage playbooks** under *Playbooks* in the account menu: per playbook name, id, version, pack, covered or not, and an *Actief* switch that decides whether it appears in the composer's menu. "Aanmaken" (an office's own playbook: name, case types, facts, instructions, labels in nl/fr/en) is wanted but pulls the manifest and pack format forward in the sequencing of platform.md; an office playbook is by definition not covered. |
| 17 | **Overview pages** for Documents and Cases open in the main area from the menu label or "Alle …" (two artboards). Same build: a title with the count, the primary action (*Uploaden*, *Nieuw dossier*), a `SearchField`, filter chips as `Select`s (an active filter shows in the teal wash with a clear ×), a sort or group control, a React Aria `Table` with virtualised rows, a three-dot `MenuTrigger` per row. Documents: name with the link badge, case (a link that opens the case: ink text, teal underline on hover), type (uploaded, playbook result with its version), status (ready, needs review with the pages, processing, failed, case closed with its deletion date), pages, added (date and who), 25 per page. Cases: a pin toggle per row (this is where a user decides what sits under *Vastgezet*), reference and name as a link, type, status (open, open with a warning, closed with its deletion date or retention), members as stacked avatars (the manager with the folder badge, "alleen leden" when access is restricted), document and conversation counts, last activity with who. |
| 16 | **Model chip**: a Lucide `brain` icon in `teal-ink` before the model's name when the model can think; the same icon next to each such model in the picker. |

## Revision of 19 October: the calm version

After a critical review the column was simplified (artboard "Uitgeklapt (gekozen: rustig)"). These rules override the decisions above where they differ.

| # | Decision |
|---|---|
| R1 | **Orange means action, nothing else**: *Nieuw*, send, primary buttons, the current-conversation dot. Warnings ("Niet gedekt", "Mislukt", "Na te kijken") are ink with their own icon (triangle, cross). The avatar badges (shield, folder, conversation) are an ink outline, not orange (replaces 13a's colour). |
| R2 | **Teal means the system vouches for something, and nothing else** (suveryn-brand guidelines, "Where the teal goes", tokens v3.3): the assistant mark, citation markers and the cited passage in the source panel, "Gedekt", `focus`, and `case-surface`. Everything else is ink and neutral surfaces: avatars are ink initials on `surface-alt` with a `line` border (no teal border or wash: replaces avatars.md's teal; the badges stay ink outlines), statuses ("Klaar", "Bevestigd") use an ink check, an active filter is `surface-alt` with a darker border, progress bars are `text-dim`, the playbook chip is neutral like the model chip, the brain icon is ink. |
| R3 | **No link badge in the sidebar**: the case reference as meta says where a conversation or document lives. The overview tables have a case column, so they carry no link badge either; the link badge is retired (decision 7 no longer applies). Where a conversation or document lives is always said in words: the case reference. |
| R4 | **Navigation rows go somewhere, chevrons open something.** *Gesprekken*, *Dossiers* (with its count) and *Documenten* are plain rows without an icon on the right: a click opens the overview in the main area, like the rows at the top of Claude's own column. They do not expand in the column (replaces the accordion of 19 October and decision 4's chevron). A chevron appears only on a row that expands in place: a pinned case. It sits on the left, before the case icon (as in a file tree, so it never collides with the actions button on the right), points right when closed and down when open (a 90° rotation, 150 ms, none under `prefers-reduced-motion`), with `aria-expanded` on the row. The case icon carries the state too: `folder` when closed, `folder-open` when open (a closed case keeps `lock`). The conversations under an open case hang from a hairline aligned with the case icon. A downward chevron on a button (Nieuw, the model chip) means a menu, not a panel. *Recent* is the one list of conversations in the column and never repeats one that is visible under an open pinned case. Order everywhere, rail included: Gesprekken, Dossiers, Documenten. |
| R5 | **A conversation in a case looks like it**: a case header over the pane (folder, reference in Space Grotesk, name, type, members with the manager apart, document count, actions), the composer says "Vraag iets over dossier 123…", a line under it says answers use only this case's documents, and the pane and its header get `case-surface` (suveryn-brand tokens v3.3; artboard 02 keeps a tweak to compare it with white and grey). Personal conversations keep the white pane and no header. |
| R6 | **Model and thinking in one popover** (replaces decision 16): the model chip opens a small dialog with the models (one line each on what they are for, a check on the current one) and a *Denkwijze* choice of two: *Snel* (answers at once) and *Grondig* (thinks first, slower). A React Aria `RadioGroup` styled as a segmented control. It applies to the conversation; the person's default lives under *Instellingen*. With a model that cannot think, *Grondig* is disabled with the reason. The chip shows the model and, when thinking is on, the `brain` icon in teal-ink and "· Grondig"; the icon now means "thinking is on", not "can think". The engine needs a per-request thinking flag (today the presets disable it). |

## The screens to build (canvas, 19 October)

The canvas was redrawn as one consistent set in the calm version; earlier variants are gone. Build from these artboards, in this order; where an artboard and a decision above disagree, the artboard and the R-rules win.

| Artboard | What it shows |
|---|---|
| 01 · Start | The expanded column in its default state (all three lists closed, two pinned cases, Recent), the empty state of a personal conversation, a composer with "In een dossier werken" to pick a case. |
| 02 · Gesprek in een dossier | A conversation inside case 123: the column with the case open under Vastgezet and the current conversation marked, the case header, the tinted pane (tweak: white, teal tint, grey; teal tint is the choice), citations, the playbook chip, the line about sources. |
| 03 · Ingeklapte rail | The 60px rail (order Gesprekken, Dossiers, Documenten) with a personal conversation: white pane, a title line, no case header. |
| 04 · Accountmenu | The account menu: header with avatar (opens the picture dialog), Mijn verbruik, Instellingen, Taal, a section "Alleen voor beheerders" with Beheer and Playbooks, Uitloggen. |
| 05 · Menu's | Nieuw, the case actions, the playbook picker and the model picker as specimens. |
| 06–08 · Overzichten | Documents, Cases and Conversations (the last filtered on a case, as reached from a count in the Cases overview). |
| 09 · Server niet bereikbaar | A bar under nothing but the browser chrome, on `surface-alt` in ink with `wifi-off`: what happened, that nothing is lost, the next retry in seconds, *Nu opnieuw proberen*. An answer cut off says so under its last word with *Opnieuw genereren*. The composer keeps the typed text; send is disabled (grey, not orange) with the reason beside it. |
| 10 · Antwoord wordt geschreven | Under the assistant mark: a collapsed *Nagedacht · 14 s* button (Grondig only; opens the reasoning), then the steps as they happen (documents searched, passages found, writing), then the text streaming with a caret and live citations. The send button becomes *Stoppen* (Esc) in the same place; the input stays usable for the next question. `aria-live="polite"`, `aria-busy`. |
| 11 · Bronpaneel | Clicking a citation opens a 440 px panel on the right: the source number, file, page and case; previous/next between the answer's sources; the passage with the cited span marked in a teal wash and the text around it dimmed; the check's verdict in words; *Document openen op p. 3* and *Passage kopiëren*. The active citation in the answer is filled teal with ink text (never white on teal). Esc closes. |
| 12 · Eerste gebruik | No pinned or recent sections at all, one line instead ("Uw recente gesprekken en vastgezette dossiers verschijnen hier"), Dossiers 0. The main area offers the two ways in (a question, or a case with *Nieuw dossier* as a secondary button) and the line "Persoonlijk gesprek · alleen u ziet dit" under the composer. That line belongs under every personal composer. |
| 13 · Documenten toevoegen | Attachments are cards above the input: reading (teal progress bar, page x of y, cancel), ready (check, pages), usable with a warning (ink triangle, the pages to check), failed (ink cross, the reason in words, *Ander bestand kiezen*, *Verwijderen*). Asking is allowed while a document is still being read; the line beside send says it counts once ready. |
| 14 · Nieuw dossier | A modal: reference (with the duplicate error in ink with an icon and a link to the existing case), name (with "no client names", cases.md decision 2), type (a `ComboBox`; it decides the playbooks), access as two radio cards with the office default selected. *Annuleren* and *Dossier openen* (orange). Errors are ink, never red: the brand has no red. |
| 15 · Smal scherm | Below 768 px the column becomes a drawer (320 px, over a scrim) opened from a menu button in a 56 px top bar that names the case and the conversation. Every target is 44 px. The composer is one pill; document, playbook and model move behind a single "+" button. |

## What maps to what in `packages/chat-ui`

- `Sidebar.tsx`: the whole column; the three sections become one `Tree` (menu) plus one `Tree`
  (pinned) and the account `MenuTrigger`. `SelectList` for the cases is replaced by tree rows.
- `ui/`: `Avatar` (size `normal` in the row, border rule changed, `badge` prop: `admin` | `manager` |
  `owner`, replacing the boolean `admin`), `IconButton`, `Button` (`primary` for "Nieuw"),
  `menus.tsx` for the "Nieuw", actions and account menus; a new small `Badge` overlay used by the
  avatar's badges and the link badge; a `Table` wrapper for the two overviews.
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
