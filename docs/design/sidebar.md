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

The artboards are pictures, not code, and they are drawn in Dutch. Their HTML uses literal colour
values: build with the tokens (`tokens.css` from suveryn-brand, v3.3) and the UI kit, never by
copying a hex value from an artboard.

Interface text is quoted here in English, as `en.ts` has it or as proposed. Strings that are new
are listed with their Dutch in *New strings* at the end. French is written alongside, as for every
string.

## 1. Colour and copy rules

These apply to every screen below.

- **Orange means action, nothing else**: *New*, send, primary buttons, and the current-conversation
  dot. Links use `accent-ink`.
- **Teal means the system vouches for something, nothing else** (suveryn-brand guidelines, "Where
  the teal goes", tokens v3.3): the assistant mark, citation markers and the cited passage in the
  source panel, "Covered", `focus`, and `case-surface`.
- **Everything else is ink on neutral surfaces**:
  - avatars: ink initials on `surface-alt`, with a finer `line` border of `max(1.5px, 5%)` of the
    side;
  - avatar badges: an ink outline;
  - statuses ("Ready", "Confirmed"): an ink check;
  - active filters: `surface-alt` with a darker border;
  - progress bars: `text-dim`;
  - the playbook and model chips, the `brain` icon and the pins.
- **Warnings and errors are ink with their own icon** (triangle, cross, circle-alert). The brand has
  no red. They never block, unless the action is impossible.
- **Copy** follows the brand voice (suveryn-brand, "Tone of voice", "Wording and spelling") and
  reuses the strings already in `i18n/*.ts` as they are.
  - "sūveryn" is lower case, also mid-sentence. It takes a capital S only where the name opens a
    sentence or a label; `i18n.test.ts` checks this.
  - Dutch is formal (u and uw, never je, jij, jouw or jullie); this is also checked.
  - Copy is sober and exact. It says what happens, with no "we", no exclamation marks and no hype:
    "Retrying in 8 seconds.", not "We're trying to reconnect".
  - Roles follow cases.md: **administrator** is the office's system role, and **manager** is a
    case's manager. *Administration* is the name of the menu item.
  - Case access: "Whole office", "Members only".

## 2. The left column

**Top strip.** The lockup (30 px mark, 22 px wordmark) with two `IconButton`s on the right:

- Search: one search across conversations, cases and documents, shown in the main area.
- Collapse.

**Collapsed rail.** The rail is 60 px wide, and the collapsed state is remembered per browser
(`.sidebar[data-collapsed]`). From top to bottom:

1. The mark, which also expands the column.
2. Search.
3. *New*.
4. One icon per navigation row.
5. The avatar.

Every icon-only button has an `aria-label` and a title.

***New*** is one orange button with a downward chevron. It opens a `Menu` with two items:

- *New chat*: personal, outside a case. When a case is open, the item says so.
- *New case*.

**Navigation rows**: *Conversations*, *Cases* (with the count) and *Documents*, in that order
everywhere, the rail included.

- A click opens the overview in the main area (section 4).
- They have no icon on the right and do not expand in the column.

**Chevrons open something.** A chevron appears only on a row that expands in place: a pinned case.

- It sits on the left, before the case icon. It points right when closed and down when open: a 90°
  rotation over 150 ms, none under `prefers-reduced-motion`. The row carries `aria-expanded`.
- The case icon also shows the state: `folder` when closed, `folder-open` when open, `lock` for a
  closed case.
- A downward chevron on a button (*New*, the model chip) means a menu, not a panel.

***Pinned*** lists pinned cases first, then pinned personal conversations.

- A pinned case shows its reference in bold and its name dim. Opened, it lists the person's own
  conversations in the case (and, for the open case, those shared with it) on a hairline aligned
  with the case icon. The current conversation has an orange dot.
- A pinned personal conversation has a conversation icon and no chevron, aligned with the case
  icons.
- Every pinned row has a three-dot actions button. It shows on hover and keyboard focus, and always
  on touch (`@media (hover: none)`).

***Recent*** is the only list of conversations in the column: newest first, across cases and the
personal space.

- The case reference is the row's meta.
- The icon says who sees the conversation: `message-square` for only me, `users` for shared with the
  case.
- It never repeats a conversation that is visible under *Pinned*.

**Account row** at the bottom: the `Avatar` at 32 px (with the administrator's badge when
applicable), the name and chevrons. It opens a `Menu`:

1. A header: the avatar (a button that opens the picture dialog), the name, "· Administrator" when
   applicable, and the username.
2. *My usage*, with the person's own tokens today as meta: personal, never the group's.
3. *Settings*: picture, password, and the default thinking mode.
4. *Language*: the `LanguagePicker`.
5. *Administration* (users, office usage) and *Playbooks*, under "Administrators only" and shown to
   administrators only.
6. *Sign out*, with the fine print "Documents and answers stay on this server".

**Avatar badges.** A small disc in the surface colour sits over the avatar's bottom-right corner,
with an ink outline icon:

- `shield` for an administrator;
- `folder` for a case's manager;
- `message-square` for the owner of a conversation shared with a case.

A person shows one badge at a time: the one that matters where the avatar appears.

**Narrow screens** (below 768 px, artboard 15):

- The column becomes a 320 px drawer over a scrim. It opens from a menu button in a 56 px top bar
  that names the case and the conversation.
- Every target is 44 px.
- The composer is one pill. Document, playbook and model move behind a single "+" button.

**First use** (artboard 12):

- There is no *Pinned* or *Recent* section. One line takes their place: "Your recent chats and what
  you pin appear here."
- *Cases* shows 0.
- The main area offers the two ways in: a question, or a case (*New case* as a secondary button).

## 3. Pinning

- **Who pins**: each person pins for themselves.
  - Storage and API: `case_pins (case_id, user, pinned_at)` and
    `PUT /v1/cases/{id}/pin {pinned}`.
  - It is a personal choice, so it is not written to the case's access log.
  - `GET /v1/cases` and `GET /v1/cases/{id}` carry `pinned` for the caller.
- **What can be pinned**: cases, and personal conversations.
  - A conversation in a case has no pin of its own; it follows its case.
  - In that conversation's menu, *Pin* is disabled with the reason "Pin the case instead".
  - In the overview, its pin cell is empty.
- **Where**: the pin column in the Cases and Conversations overviews, and the three-dot menus
  (*Pin* / *Unpin*).
- **How it looks**:
  - Pinned: a filled pin in ink, always visible.
  - Not pinned: an outline pin at low contrast. It comes up on row hover and keyboard focus, and is
    always shown at `text-dim` on touch.
  - `aria-pressed`, with the labels "Pin …" / "Unpin …". No colour.
- **Five conversations is a hint, not a limit.** Pinning a sixth works, and shows once, under the
  list: "Five pinned. A case keeps them together."

## 4. Overview pages (artboards 06 to 08)

**Shared build**:

- A title with the count, and the primary action (*Upload*, *New case*, *New chat*).
- A `SearchField`.
- Filter chips as `Select`s. An active filter is `surface-alt` with a darker border and a clear ×.
- A sort or group control.
- A React Aria `Table` with virtualised rows, 25 per page.
- A three-dot `MenuTrigger` per row. An action the person has no right to is shown disabled, never
  hidden.

**Cases**:

| Column | Content |
|---|---|
| Pin | The pin toggle (section 3) |
| Reference and name | A link that opens the case |
| Type | |
| Status | Open; open with a warning; closed, with its deletion date or retention |
| Members | Stacked avatars, the manager with the folder badge. "Members only" appears only when access is restricted and there is more than one member |
| Counts | Documents and conversations. Each count opens that overview filtered on the case |
| Last activity | With who |

**Conversations**:

| Column | Content |
|---|---|
| Pin | The pin toggle (section 3) |
| Title | With the who-sees-it icon |
| Case | The reference, or "Personal" |
| From | With the owner badge when the conversation is shared |
| Visibility | "Only you", "Shared with the case", or "· read-only" for a colleague's |
| Messages | |
| Last activity | |

- The overview is unfiltered when opened from the column, and filtered on a case when reached from
  a count or from the case itself.
- A colleague's conversation appears only when it is shared with the case.
- Row menu: *Pin*, *Rename*, *Move to a case*, *Delete*.

**Documents**:

| Column | Content |
|---|---|
| Name | |
| Case | Truncated at 200 px, the full name in a tooltip, so the row actions stay visible at 1440 px |
| Origin | Section 6 |
| Status | Ready; needs review (with the pages); processing; failed; case closed (with its deletion date); "Not a source" for a saved answer |
| Pages | |
| Added | Date and who |

A legend under the table explains *Source* and *Made*.

**Data**:

- `GET /v1/conversations?all=true`: the caller's own conversations across their space and every
  case they may read, plus the conversations shared with a case they can read.
- `GET /v1/documents/all`: every document they may see, each with its `case_id`.

## 5. The conversation pane

**Personal or in a case.**

A personal conversation has a white pane, a title line and no header. "Personal chat · only you can
see this" sits under the composer.

A conversation in a case has:

- a case header: folder icon, reference in Space Grotesk, name, type, members (the manager set
  apart), document count, actions;
- `case-surface` on the pane and the header;
- the composer placeholder "Ask about case 123…";
- under the composer: "Answers in this case use only the documents of case 123."

**The composer**:

- the document button (paperclip);
- in a case, the playbook chip;
- the model chip;
- send.

The playbook chip opens a menu of the playbooks that fit the case type
(`GET /v1/cases/{id}/playbooks`). Each item shows the name, one line, the version, and its coverage
from `covered()`: "Covered" (teal) or "Not covered" (ink triangle, never blocking).

**Model and thinking mode.** The model chip opens one small dialog:

- **Models**: each with one line on what it is for, and a check on the current one.
- **Thinking**: a segmented `RadioGroup` with *Fast* (answers at once) or *Thorough* (thinks first,
  slower).
  - The choice applies to the conversation. The default lives under *Settings*.
  - With a model that cannot think, *Thorough* is disabled and gives the reason. Whether a model can
    think is decided by model family in the engine (`ModelInfo.thinks`).
- The chip shows the model and, when thinking is on, the ink `brain` icon and "· Thorough".
- The engine needs a per-request thinking flag; today the presets disable thinking.

**Working** (artboard 10).

Built: `WaitingDots` in Messages.tsx. Three outlined squircles (the mark's shape) in `text-dim`
bounce in turn; they stand still under `prefers-reduced-motion`.

- Before the first word, one status line with the squircles. Each step replaces the last: `sending`,
  `statusSearching`, `statusReadingBest` / `statusReadingAll`, `statusLoading`, `statusWriting`.
- Once text arrives, the line goes and the squircles trail the text.
- No step list, no caret.
- `aria-live="polite"`, `aria-busy`.

Built in phase b: *Stop* (Esc) in the send button's place, with the input still usable for the
next question.

Not yet built:

- A collapsed "Thought for 14 s" button above the answer, in *Thorough* only, that opens the
  reasoning.

**Citations and the source panel** (artboard 11).

Citation markers are `teal-ink` on a teal wash. The active one is filled teal with ink text, never
white.

Clicking a citation opens a 440 px panel on the right; Esc closes it. The panel holds:

- the source number, the file, the page and the case;
- previous and next, between the answer's sources;
- the passage, with the cited span in a teal wash and the text around it dimmed;
- the check's verdict, in words;
- *Open document at p. 3* and *Copy passage*.

**Attachments** (artboard 13) are cards above the input, one shape for every state, with × at the
top right to remove:

| State | Card |
|---|---|
| Reading | A `text-dim` progress bar, "page x of y", cancel |
| Ready | A check, the page count |
| Usable with a warning | An ink triangle, the pages to check |
| Failed | An ink cross, the reason in words, and one button *Another file* (aria-label "Choose another file") |
| sūveryn's own output | Section 6 |

Asking is allowed while a document is still being read. The line beside send says it counts once it
is ready.

**Server unreachable** (artboard 09):

- A bar at the top: `surface-alt`, ink, a `wifi-off` icon. It says "Can't reach the sūveryn server.",
  that nothing is lost, "Retrying in 8 seconds.", and offers *Try now*.
- An answer that was cut off says so under its last word, with *Regenerate*.
- The composer keeps the typed text. Send is disabled (grey, not orange), with the reason beside it.

## 6. Saving answers, and where a document comes from

**Under every finished answer** (artboards 02 and 16), after the sources line, a quiet ink `Toolbar`
("Answer actions") holds:

- *Copy*;
- *Word*: already built (`lib/office.ts`, `OfficeButton` in Messages.tsx), with the question, date,
  model, warnings and sources;
- *Save to case*, in a case only.

A table in an answer has its own *Excel* button in its footer (`tableToExcel`). It writes the
source per row; amounts become numbers, and anything ambiguous stays text.

**Other formats.** *Word* and *Excel* are split buttons.

- The word downloads the default format.
- The chevron opens a `Menu`: *Word (.docx)* or *Markdown (.md)* for an answer, *Excel (.xlsx)* or
  *CSV (.csv)* for a table.
- Every format has the same content. CSV is UTF-8 with semicolons (as Belgian Excel expects) and the
  source as a column.
- The last format chosen becomes the person's default.
- New code: `toMarkdown` and `tableToCsv` next to `lib/office.ts`, built on `segmentText`,
  `tableRows` and `checkLines` in `lib/export.ts`.

**Save to case** stores the Word file as a case document with origin `answer`, next to `upload` and
`playbook`.

- Afterwards the toolbar reads "✓ Saved to case 123 as <title>.docx", with *Open* (Documents,
  filtered on the case) and *Undo*.
- *Undo* deletes the document, and is offered until the person leaves the conversation.
- It needs `POST /v1/cases/{id}/documents` to accept a generated file with `origin: "answer"` and
  the conversation and message ids, so the document can lead back to the answer.
- The file is built in the browser, as today.
- Personal conversations have no *Save to case*; download stays.

**Source or Made.** Every document shows where it comes from, as an icon and a word, both ink
(built in phase a, `lib/origin.ts`):

- **Source** (`file-text`): what a person uploaded. The model may cite it.
- **Made** (`file-output`): a playbook result, an export or a saved answer. It is **never a
  source** (cases.md decision 7): retrieval skips it, it gets no pages to cite, and the composer's
  document picker never offers it.
- A triangle, "Waiting for your choice", while a noticed upload waits for a decision (below).

In Documents the *Origin* column reads "**Source** · uploaded", "**Made** · playbook v1.0" or
"**Made** · answer, saved"; the *Origin* filter offers All, Sources or Made; the legend under the
table explains the two words. The same icon follows the document wherever it appears.

**sūveryn's own output coming back as an upload.** A downloaded answer can be edited and uploaded
again; then it would be a source, and the model would cite its own earlier output as evidence. This
can't be closed completely, but the common case is caught (built in phase a):

- **The mark** is one plain line of real text on every Word and Excel export: "Made by sūveryn:
  answer from case 2026/0611, 19/10/2026 · sūveryn-ref A-3f9c2e1b", small and light in the Word
  footer, at the end of the Excel sources sheet. The words follow the interface language;
  `sūveryn-ref` and the code don't, so it is found in any language. Being real text, it survives
  "Save as PDF"; a scanned printout is not caught. Markdown gets it as a comment (phase e); CSV
  carries none, by decision.
- **On upload**, the mark is read from the text layer (footers included). The upload is stored and
  never blocked. The attachment card says "This looks like an answer from sūveryn", quotes the
  line, and offers:
  - *Use as a source anyway* (`POST /v1/documents/{id}/source`, a contributor's right in a case,
    logged as `source_confirmed`); the origin then reads "**Source** · uploaded, was an answer";
  - *Delete*, which its uploader may do even as a contributor, while nobody has confirmed it.
- Meanwhile a question can be sent; the document is just not used.

## 7. Administrators

**Playbooks**, in the account menu:

- The list: name, id, version, pack, covered or not.
- An *Active* switch per playbook (`playbook_settings`, `GET /v1/admin/playbooks`,
  `PUT /v1/admin/playbooks/{slug} {active}`).
  - An inactive playbook leaves the composer's menu, and starting it answers 404.
  - Runs already made stay readable.

**Creating a playbook** (an office's own: name, case types, facts, instructions, labels in nl, fr
and en) is wanted, but it pulls the manifest and pack format forward (platform.md). An office
playbook is never covered.

## 8. New case

**New case** (artboard 14) is a modal, open to every user (cases.md decision 5).

- **Reference**: with the duplicate error in ink and a link to the existing case.
- **Name**: with `caseNameHint`.
- **Type**: a `ComboBox`; the type decides the playbooks.
- **Access**: two radio cards, *Whole office* (the office default) and *Members only*.
- **Buttons**: *Cancel* and *Open case*.

## 9. What to build first

1. ~~**Source or Made**, with the upload mark (section 6).~~ Built (phase a, d9e0df2).
2. ~~***Stop***.~~ Built (phase b).
3. ~~***Save to case***, with its API change.~~ Built (phase c).
4. **The column and overviews as specified** (sections 2 to 4), where they still differ from what
   is built.
5. **Markdown and CSV**, and **pinned personal conversations**.
6. **"Thought for …"** and the per-request thinking flag.

## Where it lives in `packages/chat-ui`

- **`Sidebar.tsx`**: the column.
  - The navigation rows are plain buttons.
  - *Pinned* uses the `Expander` from the UI kit for pinned cases: a row button that opens the case,
    and a chevron that expands it.
  - Then *Recent*, and the account `MenuTrigger`.
- **`ui/`**:
  - `Avatar`, with a `badge` prop: `admin`, `manager` or `owner`;
  - `IconButton`, `Button`;
  - `menus.tsx`, for New, the actions and the account menu;
  - a small `Badge` overlay for the avatar;
  - a `Table` wrapper for the overviews.
- **`Composer.tsx`**: the playbook chip and the model dialog (`ModelPicker.tsx`).
- **`Messages.tsx`**: the answer toolbar, the split buttons, `WaitingDots`, and later "Thought for".
- **`App.tsx`**: the three overviews in the main area. Administration gains a Playbooks tab.
- **`i18n/*.ts`**: every new string, in the three languages.

## New strings

English and Dutch as designed; French to be written alongside. Strings that already exist (*New
chat*, *New case*, *Pinned*, *Pin*, *Unpin*, *My usage*, *Sign out*, *Members only*, *Whole office*,
the `status*` lines, the download labels, and the origin strings of phase a) are not repeated
here.

| English | Dutch |
|---|---|
| New | Nieuw |
| Recent | Recent |
| Administrators only | Alleen voor administrators |
| Documents and answers stay on this server | Documenten en antwoorden blijven op deze server |
| Your recent chats and what you pin appear here. | Uw recente gesprekken en wat u vastzet, verschijnen hier. |
| Pin the case instead | Zet het dossier vast |
| Five pinned. A case keeps them together. | Vijf vastgezet. Een dossier houdt ze samen. |
| Rename · Move to a case · Delete | Naam wijzigen · In een dossier plaatsen · Verwijderen |
| Personal · Only you · Shared with the case · read-only | Persoonlijk · Alleen u · Gedeeld met het dossier · alleen lezen |
| Personal chat · only you can see this | Persoonlijk gesprek · alleen u ziet dit |
| Ask about case 123… | Vraag iets over dossier 123… |
| Answers in this case use only the documents of case 123. | Antwoorden in dit dossier gebruiken alleen de documenten van dossier 123. |
| Thinking · Fast · Thorough | Denkwijze · Snel · Grondig |
| Answers at once · Thinks first, slower | Antwoordt meteen · Denkt eerst na, trager |
| Thought for 14 s | Nagedacht · 14 s |
| Stop | Stoppen |
| Covered · Not covered | Gedekt · Niet gedekt |
| Answer actions | Acties voor dit antwoord |
| Save to case | Opslaan in dossier |
| Saved to case 123 as … · Open · Undo | Opgeslagen in dossier 123 als … · Openen · Ongedaan maken |
| Markdown (.md) · CSV (.csv) | Markdown (.md) · CSV (.csv) |
| Not a source · answer, saved | Geen bron · antwoord, opgeslagen |
| Another file / Choose another file | Ander bestand / Ander bestand kiezen |
| Retrying in 8 seconds. · Try now | Nieuwe poging over 8 seconden. · Nu opnieuw proberen |
| Regenerate | Opnieuw genereren |
| Open document at p. 3 · Copy passage | Document openen op p. 3 · Passage kopiëren |

## Resolved while building

- **Phase a, Source or Made (19 October, d9e0df2).**
  - Stored origins stay in English: `uploaded`, `generated`, `playbook`, and later `answer`. The
    translated words appear only on screen.
  - A document's `provenance` (jsonb) says more: for a playbook result, the playbook, version and
    run; for an upload that carries sūveryn's export mark, the mark as found, and who confirmed it
    and when.
  - "Source" is decided in one place, `suveryn_rag.store.SOURCE`: uploaded, and not a noticed upload
    that nobody confirmed. Retrieval, the chat's document check and playbook runs all use it.
  - The mark is a visible line rather than document properties or a hash (section 6), because it
    survives conversion to PDF. This was tested with a Word export saved as PDF by LibreOffice, in
    `packages/rag/tests/fixtures`.
  - The full table layout of the Documents overview is left to phase d.
- **Other upload formats, between phases a and b (19 October).** Uploads can be Word (.docx),
  Excel (.xlsx), Markdown (.md) and CSV as well as PDF (`suveryn_rag.formats`).
  - Read directly from the file, in the same sandboxed reader as PDFs; no OCR, no layout model.
    Older .doc and .xls, macro-enabled and password-protected files are refused with the list of
    what can be added.
  - **Where a passage comes from:** in Word and Markdown, its section (the headings above it, e.g.
    "Article 2 › Price"); in Excel and CSV, its cells in Excel's own notation ("Prices!A2:D31",
    "A2:D31"). The cell notation is the same in every language, so it needs no translation, and it
    is what an Excel user types to go there. Word and Markdown have no pages, so the citation chip
    shows the file name only and the source card the section.
  - Excel values are read as last calculated, never as formulas. Each sheet's first row is
    repeated at the top of every passage of that sheet, so the model always sees what the columns
    are. Hidden sheets are read: their text is in the file.
  - Word headers and footers, and Markdown comments, are not stored as passages (as a PDF's
    repeating headers and footers aren't), but they are checked for the export mark, so a Word
    answer or Excel table exported by sūveryn and uploaded again is noticed like a PDF. CSV
    carries no mark, as decided.
  - Lists show "Word", "Excel", "Markdown" or "CSV" where a PDF shows its pages.
- **Phase b, Stop (19 October).**
  - Stopping keeps what was written, with the note "Stopped. This answer is incomplete, and its
    figures and sources were not checked." Its markers still open their passages: the server now
    sends a grounded answer's passages before its first word (SSE event `sources`). The checks
    (calculations, figures, citations) only run on a finished answer, so none are shown, and Word
    export is offered for finished answers only.
  - A stopped answer is saved with the conversation, but not sent to the model as history for the
    next question: it may stop mid-sentence.
  - The server stops the model: the gateway watches the connection from the start (also before the
    first word, while the model reads), and when it closes, closes its own to llama-server, which
    stops generating. The tokens used until then are still recorded for the person, from
    llama-server's running counts.
  - Esc stops wherever the focus is, except in an open menu or dialog, which Esc closes first. After
    stopping, the focus goes to the question box.
- **Phase c, Save to case (19 October).**
  - What is stored is what builds the Word file, not the file: the question, the answer as written, its
    sources with their file names as they were, its checks and the answer's id (`documents.content`,
    not in the lists). The file is built again in the browser on download, the same as from the chat,
    mark included (the mark's reference comes from the answer's id). The question and the answer are
    also stored as text, so search finds the answer.
  - The file is named after the answer's own question ("What is the price.docx"), not the
    conversation's title, so several answers saved from one conversation can be told apart.
  - Saving the same answer again gives the document already saved, not a second one.
  - Deleting a document takes its passages and file name out of the answers saved where it was, as
    out of saved conversations (suveryn-tracker#12); the answer itself stays.
  - Who may delete it: the case's manager, and, as a contributor, the person who saved it (*Undo*).
    *Undo* is offered only during the visit in which it was saved; afterwards the toolbar still says
    where it was saved, with *Open*.
  - *Open* shows Documents searched on the case's reference. A saved answer has a download button
    there.
  - Saving is logged in the case's access log ("saved an answer to the case").
- **Phase d, part 1: the column (19 October).** Phase d is built in two parts: the column (§2) now, the
  overviews (§4) next.
  - The navigation rows open their overview and no longer expand. *Recent* shows the eight newest
    conversations; the full list is the Conversations overview.
  - *New chat* in the *New* menu is always personal. A conversation in a case starts from the case
    itself (its pinned row, or the Cases overview).
  - Recent rows get their three-dot menu with phase e, together with pinning a personal
    conversation, *Rename* and *Move to a case*; until then a row has no menu.
  - The account menu's header has no office name yet: the server doesn't send one.
  - Opening an overview leaves the column as the person last set it (the artboards draw it
    collapsed, the spec doesn't ask for it).
  - Start screen: "Welcome, <first name>" over the question box; *Work in a case* lists the open cases
    the person is a member of and *New case*. First use (no conversations and no cases): the two cards
    and "Personal conversation · only you see this" under the box.
  - Narrow screens: the drawer is a modal (focus inside, Escape or the scrim closes it, the focus
    returns to the menu button) and closes once something is chosen. The composer's "+" holds the
    document, the case's playbooks and the model.
- **Phase d, part 2: the overviews (19 October).**
  - One table for the three (`ui/table.tsx`, React Aria's `Table`): arrow keys move between rows and
    cells, Enter opens the row, a cell's own buttons (the pin, a count, the row menu) are reached with
    the arrow keys. 25 rows per page; at that size the rows aren't virtualised, which would gain
    nothing.
  - The sort is one `Select` per page, as drawn, not the column headers.
  - New: `GET /v1/cases/overview` (each case with its members, the manager first, and its last
    activity, when and who, from the access log), and `GET /v1/conversations?all=true` now also lists
    the conversations colleagues shared with a case the caller may read, with `messages` and the
    owner's name. An administrator who isn't a member sees no members of a case, only that it exists.
  - A case's counts are what the person may see: every document in it, and the conversations in
    their own list (their own and the shared ones). Each count opens that overview filtered on the
    case. *Open* after saving an answer (phase c) now does the same, instead of searching on the
    reference.
  - Status of a case: *Open*; *Open · n documents to check* when pages need checking; closed with its
    deletion date, or *kept until deleted*. Status of a document: the case's closure first, then *Not
    a source* for sūveryn's own output (*Confirmed* for a playbook result someone confirmed), then *To
    check* with the pages, or *Ready*. Uploads still being read, or failed, show in the place that is
    open, as before.
  - Row menus. Cases: *Open*, *Pin*/*Unpin*, *Members*, *Access log*, *Close case*. Conversations:
    *Open*, *Delete* (one's own). Documents: *Use in this conversation* (sources, open case),
    *Download as Word* (a saved answer), *Use as a source anyway* (an upload waiting for a choice),
    *Delete*. *Delete* follows the server's rule (`lib/overviews.ts`, tested). The conversations'
    *Pin*, *Rename* and *Move to a case*, and their pin column, come with phase e.
  - *Upload* on Documents puts the files in the place that is open, ready to ask about, and goes back
    to the conversation. *New conversation* starts one in the place that is open.
  - The last-activity and added columns are truncated at 200 px with the full text as a tooltip, and
    a status wraps, so the row menu stays visible at 1440 px with the column open. On a phone the
    table scrolls inside its box.
- **The conversation pane, part 1: the case, the composer and the source panel (20 October).** Section 5
  is built in two parts: this one, then the attachment cards and the server-unreachable states.
  - The case header (artboard 02): the case and its type, the conversation, the members (the manager
    first, with the folder badge; the button opens *Members*), the document count (opens Documents
    filtered on the case) and the case's menu. The case's members are read when it opens and again
    after the *Members* dialog closes.
  - In a case the pane is `case-surface`; the question bubbles are white with a line, as drawn.
  - The composer drops its case chip: the header, the placeholder ("Ask about case 123…") and the line
    under the box name the case. A personal chat's line is "Personal conversation · only you see
    this" (the first-use hint, now always), instead of "Documents and answers stay on this server".
  - The source panel (artboard 11) replaces the card under the answer. It is not modal: the
    conversation stays usable. The focus moves into it when a citation opens it and back to that
    citation when it closes. Esc closes it from inside it; elsewhere Esc stops an answer being
    written first, as in phase b, and otherwise closes the panel. Below 768 px it is a drawer from the
    right, which is modal.
  - The verdict in words: for a marker, whether its sentence's names, dates and figures are in the
    passage; for a source chip, whether everything the answer takes from that source is; the check's
    findings otherwise; "not checked" for a stopped answer.
  - *Open document at p. 3* is not built: sūveryn keeps a document's text, not the file it was read
    from, so there is no page to open. The panel keeps *Download* next to *Copy passage*.
  - The active marker and the active source chip are filled teal with ink text. The chip's former
    wash failed contrast on `case-surface` (4.39:1).
  - The answer's actions are a kit `Toolbar` after the sources (one Tab stop, arrow keys), with a new
    *Copy*: the answer without markers, then its sources.

## Open

- **Playbook creation by an administrator**: decide after the third hand-built playbook
  (platform.md).
- **A dark-theme check of artboard 02**: `case-surface` has a dark value, but no dark screen has
  been drawn.
- **The model's name in the chip** ("Qwen3.8-27B") is jargon for a notary. Should the chip show
  *Fast* / *Thorough*, and the model only in the dialog?

## History

- **18 October**: the first design.
  - A flat menu that expanded in place.
  - A teal link badge for "in a case".
  - *Conversations* and *Documents* as lists in the column.
  - Orange avatar badges, and a teal playbook chip and brain icon.
  - Built in part; the decisions taken while building are now in sections 3, 4 and 7.
- **19 October, "the calm version"**:
  - orange only for action, and teal only for what the system vouches for;
  - the link badge retired;
  - the navigation rows became plain links, with chevrons only on pinned cases;
  - `case-surface` (tokens v3.3) for conversations in a case;
  - the model and thinking mode in one dialog.
- **19 October, later**:
  - the state screens (09 to 15);
  - saving answers, and other formats (16);
  - pinned personal conversations;
  - Source or Made by sūveryn;
  - the copy pass;
  - the working indicator aligned with the code;
  - this rewrite into one spec, in English with the Dutch strings in one table.
