# The chat UI: left column, overviews and conversation

The spec for the chat UI's left column, the overview pages and the conversation pane, as decided with
Filip on 18 and 19 October 2026 in a Design canvas
(https://claude.ai/code/artifact/51b64e95-dd2f-48e5-b248-d92945e99b96, artboards 01 to 16).
The column follows the model of Claude's own sidebar (a collapsible rail, a flat menu, pinned items
with their children underneath, an account row at the bottom) and keeps sūveryn's brand and the UI
kit in `packages/chat-ui/src/ui/` (React Aria, Lucide, the light product theme).

This file says how things are to be **now**. It replaces the earlier decision table, revision rules
and dated sections; that history is in git and summarised at the end. Where an artboard and this
file disagree, this file wins; say so and the canvas gets fixed.

The artboards are pictures, not code. Their HTML uses literal colour values; build with the tokens
(`tokens.css` from suveryn-brand, v3.3) and the UI kit, never by copying a hex value from an artboard.

## 1. Colour and copy rules

These apply to every screen below.

- **Orange means action, nothing else**: *Nieuw*, send, primary buttons, the current-conversation
  dot. Links use `accent-ink`.
- **Teal means the system vouches for something, nothing else** (suveryn-brand guidelines, "Where
  the teal goes", tokens v3.3): the assistant mark, citation markers and the cited passage in the
  source panel, "Gedekt", `focus`, and `case-surface`.
- **Everything else is ink on neutral surfaces**: avatars (ink initials on `surface-alt`, a `line`
  border, finer: `max(1.5px, 5%)` of the side), avatar badges (an ink outline), statuses ("Klaar",
  "Bevestigd" with an ink check), active filters (`surface-alt` with a darker border), progress bars
  (`text-dim`), the playbook and model chips, the `brain` icon, pins.
- **Warnings and errors are ink with their own icon** (triangle, cross, circle-alert). The brand has
  no red. They never block unless the action is impossible.
- **Copy** follows the brand voice (suveryn-brand, "Tone of voice", "Wording and spelling") and the
  strings already in `i18n/nl.ts`; where a string exists there, the screen uses it as it is.
  - "sūveryn" in lower case, also mid-sentence; a capital S only where the name opens a sentence
    or a label (`i18n.test.ts` checks this).
  - Formal Dutch: u and uw, never je, jij, jouw or jullie (also checked).
  - Sober and exact: say what happens; no "we", no exclamation marks, no hype.
  - Roles as in the code: **administrator** for the office's system role, **dossierbeheerder** for
    a case's manager. "Beheer" is the name of the menu item.
  - Case access as in the code: "Heel het kantoor", "Alleen leden".

## 2. The left column

**Top strip.** The lockup (30 px mark, 22 px wordmark) with two `IconButton`s: search (one search
across conversations, cases and documents, in the main area) and collapse.

**Collapsed rail**, 60 px, remembered per browser (`.sidebar[data-collapsed]`): the mark (also
expands), search, *Nieuw*, one icon per navigation row, the avatar. Every icon-only button has an
`aria-label` and a title.

**Nieuw** is one orange button with a downward chevron; it opens a `Menu`: *Nieuw gesprek*
(personal, outside a case; when a case is open the item says so) and *Nieuw dossier*.

**Navigation rows**: *Gesprekken*, *Dossiers* (with the count), *Documenten*, in that order
everywhere, rail included. A click opens the overview in the main area (section 3). They have no
icon on the right and do not expand in the column.

**Chevrons open something.** A chevron appears only on a row that expands in place: a pinned case.
It sits on the left, before the case icon, points right when closed and down when open (a 90°
rotation, 150 ms, none under `prefers-reduced-motion`), with `aria-expanded` on the row. The case
icon carries the state too: `folder` closed, `folder-open` open, `lock` for a closed case. A
downward chevron on a button (Nieuw, the model chip) means a menu, not a panel.

**Vastgezet**:

- Pinned cases first. A row shows the reference in bold and the name dim. Open, it shows the
  person's own conversations in the case (and, for the open case, those shared with it) on a
  hairline aligned with the case icon, the current one with an orange dot.
- Then pinned personal conversations: a conversation icon, no chevron, aligned with the case icons.
- Every pinned row has a three-dot actions button on hover and keyboard focus (always visible on
  touch, `@media (hover: none)`).

**Recent** is the only list of conversations in the column, newest first, across cases and the
personal space. The case reference is the row's meta; the icon says who sees it (`message-square`
only me, `users` shared with the case). It never repeats a conversation that is visible under
*Vastgezet*.

**Account row** at the bottom: `Avatar` at 32 px with the administrator's badge when applicable,
the name, chevrons. It opens a `Menu`:

1. A header: the avatar as the button that opens the picture dialog, the name, "· Administrator"
   when applicable, the username.
2. *Mijn verbruik*, with the person's own tokens today as meta (personal, never the group's).
3. *Instellingen* (picture, password, default *Denkwijze*).
4. *Taal* (`LanguagePicker`).
5. For administrators only, under "Alleen voor administrators": *Beheer* (users, group usage) and
   *Playbooks*.
6. *Uitloggen*, with the fine print "Documenten en antwoorden blijven op deze server".

**Avatar badges**: a small disc in the surface colour over the bottom-right corner with an ink
outline icon: `shield` administrator, `folder` dossierbeheerder, `message-square` owner of a
conversation shared with a case. One badge at a time, the one that matters where the avatar is.

**Narrow screens** (below 768 px, artboard 15): the column becomes a 320 px drawer over a scrim,
opened from a menu button in a 56 px top bar that names the case and the conversation. Every target
is 44 px. The composer is one pill; document, playbook and model move behind one "+" button.

**First use** (artboard 12): no *Vastgezet* or *Recent* at all, one line instead: "Uw recente
gesprekken en wat u vastzet, verschijnen hier." *Dossiers* shows 0. The main area offers the two ways
in: a question, or a case (*Nieuw dossier* as a secondary button).

## 3. Pinning

- **Who pins**: each person for themselves (`case_pins (case_id, user, pinned_at)`,
  `PUT /v1/cases/{id}/pin {pinned}`). It is a personal choice, not written to the case's access log.
  `GET /v1/cases` and `GET /v1/cases/{id}` carry `pinned` for the caller.
- **What can be pinned**: cases, and personal conversations. A case conversation has no pin of its
  own; it follows its case. In its menu, *Vastzetten* is disabled with "Zet het dossier vast". In
  the overview its pin cell is empty.
- **Where**: the pin column in the Cases and Conversations overviews, and the three-dot menus
  (*Vastzetten* / *Losmaken*).
- **How it looks**: pinned is a filled pin in ink, always visible. Not pinned is an outline pin at
  low contrast that comes up on row hover and keyboard focus, and is always shown at `text-dim` on
  touch. `aria-pressed`, with the labels "… vastzetten" / "… losmaken". No colour.
- **Five conversations is a hint, not a limit.** Pinning a sixth works and shows once, under the
  list: "Vijf vastgezet. Een dossier houdt ze samen."

## 4. Overview pages (artboards 06 to 08)

**Shared build**:

- A title with the count and the primary action (*Uploaden*, *Nieuw dossier*, *Nieuw gesprek*).
- A `SearchField` and filter chips as `Select`s. An active filter is `surface-alt` with a darker
  border and a clear ×.
- A sort or group control.
- A React Aria `Table` with virtualised rows, 25 per page.
- A three-dot `MenuTrigger` per row. An action the person has no right to is shown disabled, never
  hidden.

**Dossiers**:

| Column | Content |
|---|---|
| Pin | The pin toggle (section 3) |
| Reference and name | A link that opens the case |
| Type | The case type |
| Status | Open; open with a warning; closed with its deletion date or retention |
| Members | Stacked avatars, the dossierbeheerder with the folder badge. "Alleen leden" only when access is restricted and there is more than one member |
| Documents, conversations | Counts. Each count opens that overview filtered on the case |
| Last activity | The date, and who |

**Gesprekken**:

| Column | Content |
|---|---|
| Pin | The pin toggle (section 3) |
| Title | With the who-sees-it icon |
| Case | The case reference, or "Persoonlijk" |
| Van | Who started it, with the owner badge when it is shared |
| Visibility | "Alleen u"; "Gedeeld met het dossier"; "· alleen lezen" for a colleague's |
| Messages | The count |
| Last activity | The date |

- Unfiltered from the column; filtered on a case when reached from a count or a case.
- A colleague's conversation appears only when it is shared with the case.
- The row menu: *Vastzetten*, *Naam wijzigen*, *In een dossier plaatsen*, *Verwijderen*.

**Documenten**: name, case, *Herkomst* (section 6), status, pages, added (date, who).

- Statuses: ready; needs review, with the pages; being processed; failed; case closed, with its
  deletion date; for a saved answer, "Geen bron".
- The case name truncates at 200 px, with the full name in a tooltip, so the row actions stay
  visible at 1440 px.
- A legend under the table explains *Bron* and *Gemaakt*.

**Data**: `GET /v1/conversations?all=true` (the caller's own conversations across their space and
every case they may read, plus those shared with a case they can read) and `GET /v1/documents/all`
(everything they may see, each with its `case_id`).

## 5. The conversation pane

**Personal or in a case.** A personal conversation has a white pane, a title line and no header,
with "Persoonlijk gesprek · alleen u ziet dit" under the composer. A conversation in a case has:

- A case header with the folder icon, the reference in Space Grotesk, the name, the type, the
  members with the dossierbeheerder apart, the document count and the actions.
- The pane and header on `case-surface`.
- The composer placeholder "Vraag iets over dossier 123…".
- The line "Antwoorden in dit dossier gebruiken alleen de documenten van dossier 123." under the
  composer.

**The composer**:

- The document button (paperclip).
- In a case, the playbook chip: a menu of the playbooks that fit the case type
  (`GET /v1/cases/{id}/playbooks`), each with its name, one line, its version and coverage from
  `covered()`. Coverage shows as *Gedekt* (teal) or *Niet gedekt* (ink triangle, never blocks).
- The model chip.
- Send.

**Model and Denkwijze**:

- The model chip opens one small dialog: the models, each with one line on what it is for and a
  check on the current one; then *Denkwijze* as a segmented `RadioGroup`, *Snel* (answers at once)
  or *Grondig* (thinks first, slower).
- The choice applies to the conversation; the default lives under *Instellingen*.
- With a model that cannot think, *Grondig* is disabled with the reason. "Can think" is decided by
  model family in the engine (`ModelInfo.thinks`).
- The chip shows the model and, when thinking is on, the ink `brain` icon and "· Grondig".
- The engine needs a per-request thinking flag (today the presets disable thinking).

**Working** (artboard 10):

- Built: the indicator is `WaitingDots` in Messages.tsx, three outlined squircles (the mark's
  shape) in `text-dim` that bounce in turn and stand still under `prefers-reduced-motion`.
  - Before the first word: one status line with the squircles. Each step replaces the last:
    `sending`, `statusSearching`, `statusReadingBest`/`statusReadingAll`, `statusLoading`,
    `statusWriting`.
  - Once text arrives: the line goes and the squircles trail the text.
  - There is no step list and no caret. `aria-live="polite"`, `aria-busy`.
- **Not yet built**:
  - A collapsed *Nagedacht · 14 s* button above the answer (Grondig only), which opens the
    reasoning.
  - *Stoppen* (Esc) in the send button's place, with the input usable for the next question.

**Citations and the source panel** (artboard 11):

- Citation markers are `teal-ink` on a teal wash. The active one is filled teal with ink text,
  never white.
- Clicking a citation opens a 440 px panel on the right, which Esc closes. It shows:
  - the source number, file, page and case;
  - previous and next between the answer's sources;
  - the passage, with the cited span in a teal wash and the text around it dimmed;
  - the check's verdict, in words;
  - *Document openen op p. 3* and *Passage kopiëren*.

**Attachments** (artboard 13) are cards above the input, one shape for every state, with × top
right to remove:

- Reading: a `text-dim` progress bar, "page x of y", cancel.
- Ready: a check and the page count.
- Usable with a warning: an ink triangle and the pages to check.
- Failed: an ink cross, the reason in words, and one button, *Ander bestand* (aria-label "Ander
  bestand kiezen").
- Looks like sūveryn's own output: section 6.

Asking is allowed while a document is still being read; the line beside send says it counts once
ready.

**Server unreachable** (artboard 09):

- A bar at the top on `surface-alt`, in ink, with `wifi-off`: "De sūveryn-server is niet
  bereikbaar.", that nothing is lost, "Nieuwe poging over 8 seconden.", and *Nu opnieuw proberen*.
- An answer that was cut off says so under its last word, with *Opnieuw genereren*.
- The composer keeps the typed text. Send is disabled (grey, not orange), with the reason beside it.

## 6. Saving answers, and Bron or Gemaakt

**Under every finished answer** (artboards 02 and 16), after the sources line, a quiet ink
`Toolbar` ("Acties voor dit antwoord"):

- *Kopiëren*.
- *Word*: built (`lib/office.ts`, `OfficeButton` in Messages.tsx). The file carries the question,
  date, model, warnings and sources.
- *Opslaan in dossier*: in a case only.

A table in an answer has its own *Excel* button in its footer (`tableToExcel`). It writes the source
per row; amounts become numbers, and anything ambiguous stays text.

**Other formats.** *Word* and *Excel* are split buttons:

- The word downloads the default format. The chevron opens a `Menu`: *Word (.docx)* / *Markdown
  (.md)* for an answer, *Excel (.xlsx)* / *CSV (.csv)* for a table.
- The content is the same in every format.
- CSV is UTF-8, separated by semicolons (Belgian Excel), with the source as a column.
- The last format chosen becomes the person's default.
- New code: `toMarkdown` and `tableToCsv` next to `lib/office.ts`, on `segmentText`, `tableRows`
  and `checkLines` in `lib/export.ts`.

**Opslaan in dossier**:

- It stores the Word file as a case document with origin `antwoord` (next to `upload` and
  `playbook`). Afterwards the toolbar reads "✓ Opgeslagen in dossier 123 als <titel>.docx", with
  *Openen* (Documenten, filtered on the case) and *Ongedaan maken*. *Ongedaan maken* deletes the
  document and is offered until the person leaves the conversation.
- It needs `POST /v1/cases/{id}/documents` to accept a generated file with `origin: "antwoord"`
  and the conversation and message ids, so the document can lead back to the answer. The file is
  built in the browser, as today.
- Personal conversations have no *Opslaan in dossier*; downloading stays.

**Bron or Gemaakt.** Every document shows where it comes from, as an icon and a word, both in ink:

- **Bron** (`file-text`): what a person uploaded. The model may cite it.
- **Gemaakt** (`file-output`): what sūveryn produced, such as a playbook result or a saved answer.
  It is **never a source** (cases.md decision 7). Retrieval skips it, it gets no pages to cite, and
  the composer's document picker never offers it.

In Documenten the *Herkomst* column reads "**Bron** · geüpload", "**Gemaakt** · playbook v1.0" or
"**Gemaakt** · antwoord, opgeslagen". The filter *Herkomst* offers alle, bronnen and gemaakt. The
same icon follows the document wherever it appears.

**Sūveryn's own output coming back as an upload.** A downloaded answer can be edited and uploaded
again; then it would be a *Bron*, and the model would cite its own earlier output as evidence. This
cannot be closed completely, but the common case can be caught:

- Every Word, Markdown and Excel export carries a mark:
  - In Word and Excel, custom document properties `suveryn:origin` (`antwoord` or `playbook`),
    `suveryn:case` and `suveryn:message`.
  - In Markdown, a front-matter block with the same three fields.
  - The server also keeps a hash of each saved or exported answer's text.
- On upload, a file with the mark, or whose text matches such a hash, gets the attachment card
  "Dit lijkt een antwoord van sūveryn", with where it came from (case, date) and two choices:
  - *Toch als bron gebruiken*: it becomes a *Bron* whose *Herkomst* reads "**Bron** · geüpload,
    was een antwoord". The decision goes to the case's access log.
  - *Verwijderen*.
- The upload is never blocked. The person decides; the system says what it noticed.

## 7. Administrators

- **Playbooks** in the account menu:
  - A list showing each playbook's name, id, version, pack and whether it is covered.
  - An *Actief* switch per playbook (`playbook_settings`, `GET /v1/admin/playbooks`,
    `PUT /v1/admin/playbooks/{slug} {active}`). An inactive playbook leaves the composer's menu, and
    starting it answers 404. Runs already made stay readable.
- **Creating a playbook** (an office's own: name, case types, facts, instructions, labels in nl, fr
  and en) is wanted, but it pulls the manifest and pack format forward (platform.md). An office
  playbook is never covered.
- **Nieuw dossier** (artboard 14) is a modal with these fields:
  - Reference, with the duplicate error in ink and a link to the existing case.
  - Name, with the hint about client names from `nl.ts`.
  - Type, a `ComboBox` that decides the playbooks.
  - Access, as two radio cards, *Heel het kantoor* (the office default) and *Alleen leden*.
  - The buttons *Annuleren* and *Dossier openen*.

## 8. What to build first

1. **Bron or Gemaakt**, with the upload mark (section 6). It is about trust in the citations, the
   product's core.
2. **Stoppen.**
3. **Opslaan in dossier**, with its API change.
4. **The column and overviews as specified** (sections 2 to 4), where they still differ from what
   is built.
5. **Markdown and CSV**, and **pinned personal conversations**.
6. **Nagedacht** and the per-request thinking flag.

## Where it lives in `packages/chat-ui`

- `Sidebar.tsx`: the column. The navigation rows are plain buttons; *Vastgezet* uses the
  `Expander` from the UI kit for pinned cases (a row button that opens the case and a chevron that
  expands it); then *Recent* and the account `MenuTrigger`.
- `ui/`:
  - `Avatar`, with a `badge` prop: `admin`, `manager` or `owner`.
  - `IconButton`, `Button`.
  - `menus.tsx` for Nieuw, the actions and the account menu.
  - A small `Badge` overlay for the avatar.
  - A `Table` wrapper for the overviews.
- `Composer.tsx`: the playbook chip and the model dialog (`ModelPicker.tsx`).
- `Messages.tsx`: the answer toolbar, split buttons, `WaitingDots`, and later *Nagedacht*.
- `App.tsx`: the three overviews in the main area; Administration gains a Playbooks tab.
- `i18n/*.ts`: every new string in the three languages.

## Resolved while building

- **Phase a, Bron or Gemaakt (19 October).**
  - Stored origins stay in English: `uploaded`, `generated`, `playbook`, and later `answer`; the Dutch
    words appear only on screen.
  - A document's `provenance` (jsonb) says more: a playbook result's playbook, version and run; for an
    upload that carries sūveryn's export mark, the mark as found, and who confirmed it and when.
    "Source" is decided in one place (`suveryn_rag.store.SOURCE`): uploaded, and not a noticed upload
    that nobody confirmed. Retrieval, the chat's document check and playbook runs all use it.
  - **The mark** is one plain line, not a hash and not document properties: "Gemaakt door sūveryn:
    antwoord uit dossier 2026/0611, 19-10-2026 · sūveryn-ref A-3f9c2e1b", small and light in the Word
    footer and at the end of the Excel sources sheet; Markdown gets it as a comment (phase e); CSV
    carries none (Filip, 19 October). The words follow the interface language; `sūveryn-ref` and the
    code don't, so it is found in any language. It is real text, so it survives "Save as PDF" (tested
    with a Word export saved as PDF by LibreOffice, `packages/rag/tests/fixtures`); hidden text would
    not. A scanned printout is not caught: a hint, not a guarantee.
  - **The upload check** reads the mark from the PDF's text layer (footers included) while the upload
    is read. The upload is stored, never blocked; the attachment card says what was noticed, quotes the
    line, and offers *Toch als bron gebruiken* (`POST /v1/documents/{id}/source`, logged as
    `source_confirmed`) and *Verwijderen*. Meanwhile a question can be sent; the document is just not
    used. *Verwijderen* is allowed to its uploader even as a contributor (deleting is otherwise the
    dossierbeheerder's), only while nobody has confirmed it.
  - Documenten: *Herkomst* per row with its icon (`file-text` Bron, `file-output` Gemaakt, a triangle
    while it waits for a choice), the *Herkomst* filter (alle, bronnen, gemaakt) and the legend; the
    same icon in the column's document rows. The full table layout of the overview is phase d.

## Open

- **Playbook creation by an administrator**: decide after the third hand-built playbook
  (platform.md).
- **A dark-theme check** of artboard 02: `case-surface` has a dark value, but no dark screen has
  been drawn.
- **The model's name in the chip** ("Qwen3.8-27B") is jargon for a notary. Should the chip show
  *Snel* / *Grondig*, and the model only in the dialog?

## History

- **18 October**: first design. A flat menu that expanded in place; a teal link badge for "in a
  case"; *Gesprekken* and *Documenten* as lists in the column; orange avatar badges; a teal
  playbook chip and brain icon. Built in part, with the decisions now in sections 3, 4 and 7.
- **19 October, "the calm version"**:
  - orange only for action, teal only for what the system vouches for;
  - the link badge retired;
  - the navigation rows became plain links, and chevrons only for pinned cases;
  - `case-surface` (tokens v3.3) for conversations in a case;
  - the model and thinking in one dialog.
- **19 October, later**:
  - the state screens (09 to 15);
  - saving answers and other formats (16);
  - pinned personal conversations;
  - Bron or Gemaakt;
  - the copy pass;
  - the working indicator aligned with the code;
  - this rewrite into one spec.
