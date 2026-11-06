# The chat UI

The spec for the chat UI (`packages/chat-ui`): the left column, the overview pages, the conversation
pane and everything around a question, first decided with the founder on 18 and 19 October 2026 in a
design canvas (artboards 01 to 25). *Administration* has its own spec, [admin.md](admin.md). This
file was `sidebar.md` until 28 October 2026.
The column is a collapsible rail with a flat menu, pinned items with their children underneath and
an account row at the bottom, and keeps sūveryn's brand and the UI
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

- **Orange means action, nothing else**: *New*, send, primary buttons (one per view), and text
  actions in `accent-ink` (links, "Check now", "Remove", "Copy", "Undo", "try again"). Quiet
  controls stay ink: secondary outline buttons, icon buttons, row menus, switches.
- **Teal means a system status, nothing else** (suveryn-brand guidelines, "What each colour
  means", tokens v3.4): what the system vouches for or is doing. The assistant mark,
  citation markers and the cited passage, "Covered", "Working", "Enough", "Ready", "Confirmed",
  "Reachable", "Signature checked", "Loaded", "Backed up", a passed key test, done steps, and
  progress bars and spinners of system work; plus `focus` and `case-surface`. A check icon always
  means such a status, so it is never used as a bullet (use numbers) or on an attribute
  ("Administrator: Yes", "Account: On" are plain text).
- **Everything else is ink on neutral surfaces**:
  - avatars: ink initials on `surface-alt`, with a finer `line` border of `max(1.5px, 5%)` of the
    side;
  - overlay icons on an avatar (the administrator's shield, the manager's folder, the owner's speech
    bubble): ink, as suveryn-brand's *Overlay icons* sets out (tokens v3.5);
  - active filters: `surface-alt` with a darker border;
  - chips: the composer's playbook chip and model chip are ink text on `surface-alt`, never teal or
    orange, whatever they lead to; inside the playbook menu only "Covered" is teal (a status); a
    running playbook's own chip is teal while it runs (a system status) and ink when paused;
  - the `brain` icon and the pins;
  - the current conversation's dot.
- **Violet is the second brand colour, for two things only**: the band of a strictly confidential
  case (`confidential`, section 11) and the first chart series.
- **Charts use their own four colours**, always in this order, and nothing else does: chart-1 violet
  `oklch(0.52 0.16 300)`, chart-2 ochre `oklch(0.76 0.14 82)`, chart-3 sky blue
  `oklch(0.62 0.12 230)`, chart-4 moss green `oklch(0.62 0.13 150)`; dark theme 0.58, 0.66, 0.64,
  0.63 at the same hues. Validated for colour-blind separation in both themes. Ochre on white is
  only 2.2:1, so every chart has a legend and *Show table*. A fifth series becomes "Other".
- **Tables** (tokens v3.6): the header and a footer on `band`, rows on the page colour without
  stripes, a hovered row `row-hover` (a cool blue-grey). A selected row has an ink bar on its left.
  A row is never teal and never warm: its only teal is keyboard focus. A footer holds only what
  belongs to the whole table (a total, "Kept 180 days").
- **Focus looks the same on every control**: the field's, a 1 px `focus` border with a 3 px glow
  against it, no gap (`--focus-ring` in `ui.css`; a control with its own border turns that border
  teal). A row draws it inside.
- **As few colours as possible.** Each colour does only what the brand guidelines' table says
  (suveryn-brand, "What each colour means", tokens v3.6); a new use fits that table or the table
  changes first. There is no danger colour (section 12).
- **Navigation is never orange**: the active tab is underlined in ink, the active item of a side
  menu has an ink bar on its left and bold text.
- **One notice box everywhere**: `surface-alt` (light) or `surface` (dark, one step lighter than
  the page and a dialog) with a `line` border, radius 8, an icon on the left.
  The icon and the colour of the text carry the meaning (teal for a system status, ink otherwise),
  never the box: no white variant, no heavier border for errors.
- **Warnings and errors are ink with their own icon** (triangle, cross, circle-alert). The brand has
  no red and no yellow. They never block, unless the action is impossible.
- **Copy** follows the brand voice (suveryn-brand, "Tone of voice", "Wording and spelling") and
  reuses the strings already in `i18n/*.ts` as they are.
  - Copy is sober and exact. It says what happens, with no "we", no exclamation marks and no hype:
    "Retrying in 8 seconds.", not "We're trying to reconnect".
  - **Short.** One sentence where one will do, and often none. Say the outcome, not the mechanism.
    Don't repeat what the title or the button already says. A hint only when the field isn't clear
    on its own. Explain a consequence only when it is irreversible or surprising. Dialog bodies are
    one or two short sentences; status details a few words ("3 waiting", not "3 documents are
    waiting to be read").
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

***New*** is one orange button with a downward chevron. It opens a `Menu` with two items (three in an open case):

- In an open case, for its contributors, first: *New conversation in case 123*, "Answers from its
  documents".
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
  with the case icon. The current conversation has an ink dot.
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
5. *Administration* (meta "office · appliance") and *Playbooks* (meta "{n} active"), under
   "Administrators only" and shown to administrators only.
6. *Sign out*, with the fine print "Documents and answers stay on this server".

**Avatar badges.** Overlay icons, by suveryn-brand's rule (guidelines, *Overlay icons*, tokens v3.5;
`IconBadge` and `.ui-badge`): one size per host from the `badge` tokens, 40 % outside the bottom-right
corner, the icon filling its box with no disc, ring or fill, in ink for a role; on a photo, a 1 px outline
in the surface colour. Board 55 of the design canvas shows them at every size:

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

- A title, a line under it with the counts ("12 open, 3 closed"), and the primary action (*Upload*,
  *New case*, *New chat*).
- A `SearchField`.
- Filter chips as `Select`s. An active filter is `surface-alt` with a darker border and a clear ×.
- A sort or group control.
- A React Aria `Table`, 25 rows per page. Not virtualised: at 25 rows there is nothing to gain
  (`ui/table.tsx`).
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
from `covered()`: "Covered" (teal) or "Not covered" (ink triangle, never blocking). Choosing one starts
it as a new conversation in the case (board 53): a playbook is a conversation, listed with the route
icon in the column, in *Recent* and in the Conversations overview, opened in the conversation's place
with the facts in a panel beside it ([playbooks.md](playbooks.md), "The chat UI"; boards 52 to 54).
While it is live, its composer carries the run's chip instead: teal "Deed intake 1.1 · running" (a
system status), ink when paused, with pause, cancel and stop in its menu. The case overview's status
column still shows a live run ("Deed intake · waiting for documents", `GET /v1/playbooks/runs/active`).
Every conversation's turns are rows in the `turns` table; a playbook's are written by the server.

**Model and thinking mode.** The model chip opens one small dialog:

- **Models**: each with one line on what it is for, and a check on the current one.
- **Thinking**: a segmented `RadioGroup` with *Fast* (answers at once) or *Thorough* (thinks first,
  slower).
  - The choice applies to the conversation. The default lives under *Settings*.
  - With a model that cannot think, *Thorough* is disabled and gives the reason. Whether a model can
    think is decided by model family in the harness (`ModelInfo.thinks`).
- The chip shows the model and, when thinking is on, the ink `brain` icon and "· Thorough" (decided
  21 October: the model's name stays on the chip).
- Built: the per-request flag `ChatRequest.thinking`; the presets still switch thinking off by
  default, and a request turns it on for itself (`suveryn_harness/thinking.py`).

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

Built: a collapsed "Thought for 14 s" button above the answer, in *Thorough* only, that opens the
reasoning, with the line that it isn't checked.

**Citations and the source panel** (artboard 11).

Citation markers are `teal-ink` on a teal wash. The active one is filled teal with ink text, never
white.

**One rule for sources, in every conversation** (handover of 31 October 2026, boards 1 and 2). In the
text, the marker after the sentence it supports. Under the text, the sources line: "Sources:" and one
item per source, the same marker with the file and page, one link in ink, underlined
("1 Compromis_DeSmet.pdf, p.4 · 2 Compromis_DeSmet.pdf, p.9"; `SourceRef` in `src/ui/`). Pressing the
marker in the text or the item in the line opens the source panel on that source; the open one's marker
is filled in both places, and its link carries `aria-current`. Its name is "Source 1: Compromis_DeSmet.pdf,
page 4". A playbook's card and the facts list show a fact's source with the same `SourceRef`.

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
| Not added | Refused on arrival (a kind of file sūveryn doesn't read, or too large) or left out of a .zip. A full reading queue and the upload rate limit are not refusals: the card waits and the upload is sent again (`lib/turns.ts`). For the rest: "Not added." and the reason, never "Couldn't be read", since nothing went wrong reading it. A .zip's card becomes a card per document in it, and one per file left out ("From Prospectus.zip: it is empty."), and the same *Another file* button |
| sūveryn's own output | Section 6 |

Asking is allowed while a document is still being read. The line beside send says it counts once it
is ready.

**Server unreachable** (artboard 09):

- A bar at the top: `surface-alt`, ink, a `wifi-off` icon. It says "Can't reach the sūveryn server.",
  that nothing is lost, "Retrying in 8 seconds.", and offers *Try now*.
- An answer that was cut off says so under its last word, with *Regenerate*.
- The composer keeps the typed text. Send is disabled (grey, not orange), with the reason beside it.

## 6. Saving answers, and where a document comes from

**Under every finished answer** (artboards 02 and 16), after the sources line (a list of `SourceRef` links, §5), a quiet ink `Toolbar`
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
- The code: `answerToMarkdown` and `tableToCsv` in `lib/textfiles.ts`, next to `lib/office.ts` and
  built on the same `AnswerExport` and `tableRows`; the default in `lib/downloadFormat.ts`; the
  kit's `SplitButton`.

**Save to case** stores the Word file as a case document with origin `answer`, next to `upload` and
`playbook`.

- Afterwards the toolbar reads "✓ Saved to case 123 as *title*.docx", with *Open* (Documents,
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

## 7. Administration

Moved to [admin.md](admin.md) on 28 October 2026: the side menu, every page of *Administration*
and its strings (artboards 26 to 43). The colour and copy rules of section 1 apply there too.

## 8. New case

**New case** (artboard 14) is a modal, open to every user (cases.md decision 5).

- **Reference**: with the duplicate error in ink and a link to the existing case.
- **Name**: with `caseNameHint`.
- **Type**: a `ComboBox`; the type decides the playbooks.
- **Access**: two radio cards, *Whole office* (the office default) and *Members only*.
- **Buttons**: *Cancel* and *Open case*.

## 9. Still to build

- The column and overviews where they still differ from sections 2 to 4.
- In *Administration* ([admin.md](admin.md)): *Licence*, *Network*, and *Updates and models* once updates exist (#40).

## 10. Choosing which documents a question is about (artboards 17 to 19)

Decided with the founder on 21 October, after the Pod runs on 10 real documents and 44 questions: asking
across the whole case gave 37/40 right facts and 7/44 answers citing another document; the server
guessing the document gave 32/40 and 10/44, at up to 33 s; the one document attached gave 15/15 and
44/44, in 2 to 11 s. Choosing works, guessing doesn't. Artboards 20 to 22 (correcting after the
answer, and both together) were drawn and **not chosen**: when the documents were wrong, the person
asks again with the right ones.

**Ask about.** In a case, the composer has one control beside the paperclip (the + button in the
narrow screen's pill): *Ask about: all documents* ▾.

- It opens a `DocumentPicker`, a new kit component: a `DialogTrigger` with a `Popover`, an
  "All documents in case 123" option, a `SearchField` (from about nine sources), and a `ListBox`
  with `selectionMode="multiple"`. `MenuButton` can't do multiple choice with search.
- Each row shows the name, the kind of file, the pages, and who added it and when. Chosen documents
  stay at the top, under "Chosen", even when the search no longer matches them.
- Only sources are listed. sūveryn's own output and uploads waiting for a choice are left out, with
  a line saying so.
- *Upload a new document* at the bottom uploads to the case and chooses the document at once.
  Uploading from the + menu does the same. This replaces "attaching from the case": choosing is one
  thing, in one place.
- Chosen, the control reads *Ask about: akte-verkoop.pdf* or *Ask about: 2 documents* (the name is
  cut at 240 px). It announces "Ask about, 2 documents chosen".
- Keyboard: Enter or arrow down opens, typing searches, Space chooses, Esc closes and keeps the
  choice.
- Narrow screens: the control stays visible above the input, full width, and opens a bottom sheet
  with *Done* and 44 px rows.
- A reader's question box is read-only and has no *Ask about*; she sees what each question read
  (below).
- *Ask about* exists only in a case. In a personal conversation the paperclip attaches documents as
  it does now.

**The choice belongs to the conversation.**

- It stays for every following question until changed, and is never carried to another conversation
  or remembered per case.
- Every question with a choice shows it under the question: "Ask about: akte-verkoop.pdf". A
  question about the whole case shows nothing. Readers of a shared conversation see the same.
- The line under the question box follows it: "Answers use only akte-verkoop.pdf." or "Answers use
  only the 2 chosen documents."
- The basis line above each answer stays ("Based on …"): the question says what it might read,
  the answer says what it used.
- When the documents were wrong, the person chooses the right ones and asks again. There is no
  correcting action on the answer.

**Edge cases.**

- A chosen document that is deleted, or replaced by a new version, leaves the choice; the question
  reads the documents that remain. When none remain, it reads the whole case again, and the line
  under the question box says so: "The chosen documents are no longer in the case. Answers use all
  its documents again."
- When the chosen documents are too large to be read whole, the answer says so above its text: "Too
  large to read in full: the passages that best match your question were read."
- A question that names one document by its kind and maybe its language ("de Franstalige volmacht", "the
  shareholders' agreement", "les statuts") reads only that one, when exactly one in the choice fits by its file
  name (and its own language); the answer says so under its text: "Your question names a document: only R2
  (FR).pdf was read." When several fit, or none, every document is searched as before (`suveryn_rag.naming`). Searching across a case also keeps each document's closest passage by
  meaning (a third of the passages at most), so a French document answers a Dutch question.
- Playbooks always read the whole case; *Ask about* doesn't limit them.
- Asking again counts as a new message, in token usage and in the case's access log.

**Server.**

- The server's guess was measured and dropped (see "Decided while building"): with nothing chosen, a question reads the case's sources.
- A question carries the chosen document ids, as an attachment does today; the server reads exactly
  those.
- The choice is saved with each question in the conversation's history, as its attachments are now,
  so a reopened or shared conversation shows what each question read.

**The reading budget (48,000 characters).** It can be raised, at a cost; the dev chat measures
before choosing a number.

- The limit comes from the context: `-c 65536 -np 4 -kvu` gives four parallel slots one shared
  KV cache, and 48,000 characters (~14k tokens of Dutch) leaves each slot room for history and the
  answer while four people ask at once.
- Ways to raise it, cheapest first:
  1. Count in tokens, not characters (the open item in docs/architecture.md): Dutch and French fit
     more than the character estimate allows for.
  2. A larger budget only for a question with chosen documents: it is what the person asked for, and
     the unified cache lends the slot room when the others are idle. The budget then depends on the
     load, and the answer says when it had to fall back to passages.
  3. A larger context (`-c 131072`): about twice the KV memory, so it depends on the appliance's GPU
     and on the model's own context limit.
  4. Fewer parallel slots (`-np 2`): more room each, more waiting when several people ask.
- Whole documents over 99 passages also hit the two-digit citation markers
  (`WHOLE_DOCUMENT_CHUNKS`); a larger budget needs three-digit markers or a coarser unit.
- To measure on the Pod: the 58-page deed and two deeds chosen together, at 48k, 80k and 120k
  characters, with one and with four questions at once, for right facts, answer time and memory.

## 11. A strictly confidential case (artboards 23 and 24)

Decided with the founder on 21 October. One extra level on a case: **Strictly confidential**. Not "Secret"
or "Top secret": in Belgium those are legal classification levels (the 1998 law, with clearances and
approved systems), and sūveryn would claim an accreditation it doesn't have. Every case already falls
under professional secrecy, so the ordinary level has no label.

**What it does**:

- Access is always *Members only*; it can't be opened to the whole office while the label is on.
- Conversations can't be shared with the case. Turning the label on unshares the ones that were
  shared; their owners keep them, and the dialog says how many.
- Every export carries a watermark: Word, Excel, Markdown, CSV and *Save to case*.
  - Word: a diagonal "STRICTLY CONFIDENTIAL" (in the interface language) on every page, a
    header with the case, the person's name and the time (whoever leaks it is named on it), and
    the existing export mark with "Strictly confidential" added.
  - Excel: the same in the header and footer of every sheet.
  - Markdown and CSV: a first line.
  - *Copy* can't carry a watermark and stays as it is.
- In *Recent*, in search results and in the Conversations overview, its conversations appear
  without their title: "Shielded conversation" with the case reference, so the person can still go
  straight back. Only people with access see the row at all. *Pinned* shows the reference and
  name, because the person chose to pin it; the conversation titles under it show only while the
  case is open.
- **Not**: a reason for an administrator who opens the access log, or a shorter retention.
- **Administrators who aren't members** see that the case exists, by its reference only, with
  "Strictly confidential" where the name would be, in the Cases overview and in *Administration*, so
  they can hand it over, close or delete it, and they can open its access log. The gateway leaves the
  name and the subject out of every answer to them (`shielded`; decision, 29 October, after the external
  review's pass 7). They never see its documents, its conversations or their titles. Its manager and
  members still show, for handing it over.

**Who sets it**: the case's manager, in *Members and access*, as a switch with one paragraph on what
changes. Turning it on or off goes to the case's access log.

**How it looks**: one sign, the same everywhere, and one colour of its own. Six options were drawn
on artboard 25 (violet, night blue, aubergine, raspberry, ochre, ink). Ink was chosen on 21 October,
then violet on 27 October, once violet also became the first chart colour: one second brand colour
with two uses reads as deliberate.

- **The token `confidential`**: light `oklch(0.42 0.15 300)` with white text (8.5:1), dark
  `oklch(0.75 0.12 300)` with ink text (9.3:1). The icon and the label take the same token. It is
  for this meaning only, and never alone: the key icon and the words are always there. In suveryn-brand
  tokens v3.4 (`confidential`, `on-confidential`), with `chart-1` to `chart-4`.
- **A band above the case header**, with `folder-key`, in `confidential`: "Strictly confidential ·
  Members only · Conversations aren't shared · Exports carry a watermark". It says what the label
  does, not how secret the case is.
- On narrow screens, the band shortens to the icon, the label and *What does this mean?*, which
  opens the three rules in a sheet.
- **One sign: the key**, in the shape of the thing it marks. The shape says what it is; the key or
  lock on it says "only those who belong".
  - The case: Lucide `folder-key`, in the column, the case header, the Cases overview, its filter,
    the setting and the band. In the column the chevron alone shows open or closed.
  - A conversation in such a case: `message-square-lock`, in *Recent* and in search results, in
    `text-dim` like the other row icons there; the title "Shielded conversation" is `text-dim`
    too.
  - A document in such a case, if one is ever marked: `file-key`.
  - The lock on a folder still means a closed case, so a closed strictly confidential case shows
    the lock. No eye icon anywhere.
- **In the Cases overview**, the status column also carries an ink outline label in words, and a
  filter chip offers *Strictly confidential*.
- In the conversation menu, *Share with the case* isn't shown at all (decided 28 October); the band already says conversations aren't shared.
- The answer toolbar looks as in any case; no extra label. The *Word* button's description says
  the file carries the watermark ("Download this answer as a Word document, with its sources and the
  Strictly confidential watermark"). The band already says that exports carry one.

**Data**: `cases.confidential` (boolean), set with `PATCH /v1/cases/{id}` by the manager, logged as
`confidential_on` / `confidential_off`. The gateway enforces members only and no sharing; the export
code adds the watermark; the conversation lists return `title: null` and `shielded: true` for these
conversations, and the client shows the placeholder.

## 12. Dialogs

From Claude Design's handover of 6 November 2026 (`Claude outputs/design-handover-dialogs.md`, boards
69 to 79). The kit's `Dialog` (`ui/dialog.tsx`) lays out the buttons from their roles; a screen
names the kind, the roles and the labels, nothing else, and `ui/kit-only.test.ts` keeps it so.

- **Four kinds**: a *confirmation* (one action and a way out), a *choice* (two real actions and a
  way out), a *form* (fields, a submit and a way out) and an *information* dialog (nothing to
  decide).
- **One row, right-aligned, every button 44 px**, the height of a field. Left to right: the way
  out, the second real action, the main action, written in that order so that reading order, Tab
  and a screen reader agree. No text links for a real choice.
- **The main action is `primary`** (orange), also when it deletes: orange means act, and a dialog
  has one action. The second real action and the way out are `secondary` (outlined). The way out
  says *Cancel*; *Keep the run* when the main action is itself a cancel.
- **Helpers** that don't close the dialog (*Copy*, *Print*) are `quiet` buttons with their icon, at
  the left of the row. They are the only dialog buttons with an icon.
- **No danger colour.** A risky action (delete, switch off, sign out everywhere, reset, set the
  clock, a new recovery key, cancel a run) is marked by where the focus starts, on *Cancel*, and by
  the sentence. An ordinary confirmation or choice starts on the main action; a form in its first
  field; an information dialog on its first control, or its × when it has none.
- **The title** is the question with its object ("Delete case 124?") or the task ("Rename
  conversation"), in the `title` style (22 px). **The body** is one or two sentences, only when the
  outcome is irreversible or surprising; it says what happens, not what the button does.
- **The ×** (44 px, top right, "Close") is on forms and information dialogs; confirmations and
  choices have their way out in the row. *Pass this on* (the temporary password, seen once) has
  only *Done*; Escape still closes it.
- **Busy**: the running button shows its progress word ("Deleting…"), every button is disabled,
  Escape and a click outside do nothing. **Failed**: an `InlineNotice` under the body, in ink with
  its icon, the reason in the reader's language; the buttons come back and the focus goes to the
  main action.
- **Narrow** (under 520 px): a sheet from the bottom, the buttons a full-width column in the same
  order top to bottom, the main action last, nearest the thumb. When the labels don't fit on one
  row, `Dialog` uses that column at every width. Labels stay under 45 characters in every language.
- `role="alertdialog"` for confirmations and choices, `dialog` for forms and information.

The setup wizard and the sign-in pages (Keycloak's theme, in suveryn-appliance) still use their own
pattern (a full-width orange button with Cancel as a text link); they follow in a later round.

## Where it lives in `packages/chat-ui`

- **`Sidebar.tsx`**: the column.
  - The navigation rows are plain buttons.
  - *Pinned* uses the `Expander` from the UI kit for pinned cases: a row button that opens the case,
    and a chevron that expands it.
  - Then the pinned personal conversations, *Recent*, and the account `MenuTrigger`.
  - A conversation's menu is `conversationMenu` (`ConversationDialogs.tsx`, from
    `lib/conversationActions.ts`), the same in the column and the Conversations overview; its
    *Rename* and *Move to a case* dialogs are there too.
- **`ui/`**:
  - `Avatar`, with a `badge` prop: `admin`, `manager` or `owner`;
  - `IconButton`, `Button`;
  - `menus.tsx`, for New, the actions and the account menu;
  - a small `Badge` overlay for the avatar;
  - a `Table` wrapper for the overviews.
- **`Composer.tsx`**: the playbook chip, *Ask about* (`DocumentPicker`, new in `ui/`) and the model dialog
  (`ModelPicker.tsx`).
- **`Messages.tsx`**: the answer toolbar, the split buttons, `WaitingDots`, and "Thought for".
- **`App.tsx`**: the three overviews in the main area. *Playbooks* is an item of Administration's side
  menu (`Admin.tsx`).
- **`i18n/*.ts`**: every new string, in the three languages.

## Strings

The interface's strings are in `packages/chat-ui/src/i18n/` (`en.ts`, `nl.ts`, `fr.ts`), the one source; [docs/translations.md](../translations.md) says how they are checked. Copy for screens not built yet is on the design canvas, not repeated here.

## Decided while building

What the build settled that the sections above don't say, by topic. Each is current behaviour.

### Documents: origin, formats and the export mark

- Stored origins stay in English (`uploaded`, `generated`, `playbook`, `answer`); the translated words appear only on screen. A document's `provenance` (jsonb) says more: for a playbook result the playbook, version and run; for an upload carrying sūveryn's export mark, the mark as found, and who confirmed it and when.
- "Source" is decided in one place, `suveryn_rag.store.SOURCE`: uploaded, and not a noticed upload nobody confirmed. Retrieval, the chat's document check and playbook runs all use it.
- The mark is a visible line rather than document properties or a hash, because it survives conversion to PDF (tested with a Word export saved as PDF, in `packages/rag/tests/fixtures`).
- Uploads can be PDF, Word (.docx), Excel (.xlsx), Markdown (.md) and CSV (`suveryn_rag.formats`). The others are read directly from the file, in the same sandboxed reader, with no OCR or layout model. Older .doc and .xls, macro-enabled and password-protected files are refused with the list of what can be added.
- Where a passage comes from: in Word and Markdown, its section ("Article 2 › Price"); in Excel and CSV, its cells in Excel's notation ("Prices!A2:D31"), the same in every language. Word and Markdown have no pages, so the citation chip shows the file name and the source card the section. Lists show "Word", "Excel", "Markdown" or "CSV" where a PDF shows its pages.
- Excel values are read as last calculated, never as formulas; each sheet's first row is repeated at the top of its passages, so the model sees what the columns are; hidden sheets are read. Word headers and footers and Markdown comments are not passages, but are checked for the export mark. CSV carries no mark.

### Stopping, failing and asking again

- A stopped answer keeps what was written, with "Stopped. This answer is incomplete, and its figures and sources were not checked." Its markers still open their passages, because a grounded answer's passages are sent before its first word (SSE `sources`). Checks run only on a finished answer, and Word export is offered for finished answers only. A stopped answer is saved, but not sent to the model as history.
- Stopping stops the model: the gateway watches the connection from the start and closes its own to llama-server when it closes. Tokens used until then are still recorded. Esc stops wherever the focus is, except in an open menu or dialog, which it closes first; the focus then goes to the question box.
- A cut-off answer (the connection dropped, or the stream ended without its last event) keeps what arrived, unchecked, under "Answer interrupted: the connection dropped." Any other failure shows nothing of the attempt. Both offer *Regenerate* on the last answer: the same question, with the same documents, in its place.
- An answer that stops at its length limit says so; a cut-off answer says it is incomplete. The server logs such a stop by counts only.
- A question asked right after a colleague deleted one of the case's documents: a question about the whole case is asked again at once with the documents there are now; a question about chosen documents says one of them was deleted meanwhile.
- The server-unreachable bar shows after a health check found nothing, not while the first one runs; it counts down to the next check (every 10 seconds) and *Try now* checks at once. Its title is announced once, the countdown isn't. The composer keeps the text and says why it can't send.
- When the database or the sign-in service is down, the gateway's 503s carry a `reason` (`database`, `signin`) so every message can say which part is down. The sign-in page says the database can't be reached, what to do if it stays so, and offers *Try again*. A sign-in service that answers with a server error doesn't sign people out; their session waits. Deleting a document while the saved conversations can't be read is refused in the app with a sentence, and on the server.
- The question being typed is kept for the browser tab (`lib/draft.ts`, sessionStorage) until it is sent, emptied or the person signs out, so it survives signing in again after a restart.

### Saving answers

- What is stored is what builds the Word file, not the file: the question, the answer, its sources with their file names as they were, its checks and the answer's id (`documents.content`). The file is built again in the browser on download, mark included. The question and answer are also stored as text, so search finds them.
- The file is named after the answer's own question, so several answers from one conversation can be told apart. Saving the same answer again gives the document already saved.
- Deleting a document takes its passages and file name out of the answers saved where it was, as out of saved conversations (suveryn-tracker#12); the answer stays.
- The case's manager may delete a saved answer, and so may the contributor who saved it (*Undo*, offered during the visit in which it was saved). *Open* shows Documents filtered on the case. Saving is in the case's access log.

### The column and the overviews

- The navigation rows open their overview. *Recent* shows the eight newest conversations. *New chat* is always personal; in an open case the *New* menu offers *New conversation in case 123* to its contributors.
- Start screen: "Welcome, *first name*" over the question box; *Work in a case* lists the open cases the person is a member of, and *New case*. First use (no conversations, no cases): the two cards and "Personal conversation · only you see this".
- Narrow screens: the drawer is a modal (focus inside, Escape or the scrim closes it, the focus returns to the menu button) and closes once something is chosen. The composer's "+" holds the document, the case's playbooks and the model.
- One table for the three overviews (`ui/table.tsx`, React Aria's `Table`): arrow keys move between rows and cells, Enter opens the row, a cell's own buttons are reached with the arrow keys. 25 rows per page, not virtualised (nothing to gain at that size). The sort is one `Select` per page. The overviews read their lists again whenever one is opened.
- A case's counts are what the person may see, and each opens that overview filtered on the case. An administrator who isn't a member sees that a case exists, not its members. The *From* column shows a colleague's own initials when the member list doesn't name them, never the viewer's.
- Status of a case: *Open*; *Open · n documents to check*; closed with its deletion date, or *kept until deleted*. Status of a document: the case's closure first, then *Not a source* for sūveryn's own output (*Confirmed* for a confirmed playbook result), then *To check* with the pages, or *Ready*.
- Row menus. Cases: *Open*, *Pin*/*Unpin*, *Members*, *Access log*, *Close case*. Documents: *Use in this conversation*, *Download as Word* (a saved answer), *Use as a source anyway* (an upload waiting for a choice), *Delete*, which follows the server's rule (`lib/overviews.ts`). Conversations: *Open*, *Pin* or *Unpin*, *Rename*, *Move to a case*, *Delete*; for one in a case *Pin* is disabled with "Pin the case instead" and *Move* is disabled; for a colleague's shared one everything is. Row actions are always shown on a touch screen (`hover: none`).
- Pinned personal conversations come after the pinned cases and are left out of *Recent*. The five-pinned hint shows once in this browser when a pin takes the count past five; the pin still works.
- The collapsed rail has no separate expand button: the mark expands it (with a title). A pinned case's chevron turns in 150 ms.
- Long columns are truncated at 200 px with the full text as a tooltip, so the row menu stays visible at 1440 px; on a phone the table scrolls inside its box.

### Conversations: renaming, moving, sharing

- `PATCH /v1/conversations/{id}` renames (the owner only), and the title is kept over later saves. `PUT /v1/conversations/{id}/pin` pins a personal conversation (409 for one in a case: it follows its case). `POST /v1/conversations/{id}/move` moves a personal conversation into an open case the owner contributes to or manages (403 for a reader or a closed case, 409 if already in one); it arrives unshared and unpinned, and the access log says `conversation_moved_in`. Its documents stay in the personal space, so its next questions read the case's documents, as the dialog says. Moving the open conversation takes the person to the case.
- Expired conversations are left out of every list at once and deleted by the hourly sweep, not on each request.
- A colleague's shared conversation opened from anywhere is read-only. Where the person can't ask at all (a shared conversation, a closed case, a reader, an administrator outside the case) the question box is read-only and has no placeholder. While the server is unreachable it stays editable.

### The conversation pane

- The case header: the case and its type, the conversation, the members (the manager first; the button opens *Members*), the document count (opens Documents filtered on the case) and the case's menu. The members are read when it opens and after *Members* closes. In a case the pane is `case-surface`, and the case's documents are read again every 30 seconds while the page is visible.
- The composer has no case chip: the header, the placeholder ("Ask about case 123…") and the line under the box name the case.
- Attachments are cards inside the question box (above it on a narrow screen); in the person's turn they are chips. Asking doesn't wait for documents being read: a question goes with what is read, and a document still being read stays in the composer for the next question (`staysInComposer`).
- A card shows the reading's progress: "Recognising text · page 4 of 12" while scanned pages are recognised (the reader reports pages through an OCRmyPDF plugin, `ocr_progress.py`), then "Reading the layout of 12 pages" with a moving bar (Docling reports no pages), then "Storing". Its × cancels: an upload on its way stops in the browser; one waiting is never read; one being read stops at once (the reader is killed); one already being stored finishes. Cancelling is in the access log.
- A failed card says the reason from its code (`password`, `damaged`, `too_many_pages`, `too_large`, `no_text`, `unsupported`, `timeout`, `unreadable`) in the interface's language (`failureText`); the English sentence stays for the API and the log. *Another file* replaces the card.
- The source panel replaces a card under the answer. It is not modal; the focus moves into it when a citation opens it and back when it closes; Esc closes it from inside it. Below 768 px it is a modal drawer from the right. *Open document at p. 3* is not built: sūveryn keeps a document's text, not its file, so the panel offers *Download* next to *Copy passage*.
- The verdict in words: for a marker, whether its sentence's names, dates and figures are in the passage; for a source chip, whether everything the answer takes from that source is; "not checked" for a stopped answer. The active marker and source chip are filled teal with ink text (the chip's former wash failed contrast on `case-surface`, 4.39:1).
- Above every sourced answer a quiet line names the documents it rests on ("Based on akte-verkoop.pdf"): it is the one cue that shows an answer mixing documents.
- The answer's actions are a `Toolbar` after the sources (one Tab stop, arrow keys), with *Copy*: the answer without markers, then its sources.

### Choosing documents (*Ask about*)

- `DocumentPicker` (`ui/picker.tsx`): a popover, or on a narrow screen a sheet with *Done*. "All documents" is pressed when nothing is chosen; the list is a multiple-selection `ListBox` whose Escape closes the picker rather than clearing the choice. The search field shows from nine sources and doesn't take the focus.
- The paperclip is a plain upload button. In a case an upload is chosen once it is read, and removing its card takes it out of the choice. A document opened from the Documents overview is chosen.
- The choice is saved on each question as `about`; deleting a document empties its name there. "Too large to read in full" shows when the server says the passages were a selection (the stream's `complete`).
- With nothing chosen, a question in a case reads its sources, newest first, up to the server's 50 (`lib/questionDocuments.ts`); sūveryn's own output and uploads waiting for a choice are never read. More than 50 sources is an open point.
- **Tried and dropped: guessing the document.** Narrowing a question on the server to the documents it seemed to be about made answers worse than reading the whole case: on ten real documents, right facts fell from 37/40 to 32/40, answers citing another document rose from 7/44 to 10/44, and the wrong document was kept on 9 of 44 questions. With the one document chosen: 15/15. Hence *Ask about*. (A question that names one document by its kind is different: section 10.)

### Downloads

- The download button is two buttons in a group: the word ("Download this answer as a Word document, with its sources") and the chevron, "Other formats", a single-choice menu with the default ticked. Choosing a format downloads it and makes it the default, per kind (answers, tables), kept in this browser (`suveryn.format.answer`, `suveryn.format.table`). While a file is made the buttons stay enabled and a second press is ignored, so the focus isn't lost.
- Markdown: the question as the heading, the date and model, the answer with its markers, *To check*, each cited source with its passage as a quote, the disclaimer, and the export mark as an HTML comment. What the model wrote is escaped, so it can't add headings, links or HTML.
- CSV: UTF-8 with a byte order mark, semicolons and CRLF, as Belgian Excel opens it, with a last column of sources. A cell that starts with `=`, `+`, `-` or `@` and isn't a number gets a leading `'`, so it can't run as a formula. No mark.
- Download names lose a trailing dot.

### Strictly confidential

- Turning the label on also restricts the access, and the access can't be opened while it is on (409); turning it off and opening in one change is allowed. The `UPDATE` itself refuses while the label is on, so two managers changing the case at once can't leave it labelled and open. Unsharing happens in the same request, and the access log's `confidential_on` says how many were unshared.
- Only `GET /v1/conversations?all=true` (Recent, search, the Conversations overview) shields titles; the case's own list keeps them. A shielded title isn't searched.
- Word: the label is Word's own watermark, light grey, with the line in the header and "Strictly confidential" in the export mark. Excel can't get a page header from write-excel-file, so the line is the first and last row of every sheet. Markdown, CSV and the sources' text files: the line first. The playbook result's Word file and a saved answer carry it too; *Copy* doesn't. The watermark is made at each download, with the person's name and the time, in the interface language (`lib/watermark.ts`).
- The switch is in *Members and access* for the manager, with what it changes and how many conversations it will unshare.

### Fast and Thorough

- `ChatRequest.thinking`: for a model that can think (`ModelInfo.thinks`, by family), the request sends llama-server `chat_template_kwargs: {"enable_thinking": …}`, and *Thorough* gets 4,096 tokens on top of the answer's own. The reasoning comes back apart from the answer (`reasoning_content`) or between `<think>` tags, taken out even when split over chunks. The stream sends a `thinking` status, `thinking` events, then the answer; `done` carries `reasoning` and `thought_seconds`. The reasoning is never in the answer, its checks, *Copy* or the downloads, and never goes back to the model.
- When the thinking runs past its 4,096 tokens without an answer, or the answer comes back empty because the thinking used the budget, the question is asked again without thinking, and the answer says "Thorough thought for too long without an answer, so this one was written without thinking. Ask more narrowly to have it thought through." (`done.thinking_cut`). The whole answer at once (`POST /v1/chat` without streaming) does the same, and gives `thought_seconds` as the thinking's share of the call.
- The model chip opens one dialog (`ChipDialog`): the models when there are several, and *Fast* / *Thorough* (`Segmented`). With a model that can't think, *Thorough* is disabled with the reason. On a narrow screen the "+" menu has a *Thinking* submenu.
- The choice belongs to the conversation: each answer records it, and a reopened conversation goes on with it. A new conversation starts with the default under *Settings*, kept in this browser. "Thought for 14 s" opens the reasoning, with "How the model got to its answer. This isn't checked: the answer and its sources are."
- A grounded answer that cites none of its passages is logged by counts only (passages, whole or selected, earlier answers and their markers, answer length, thinking), to study the cause without document text (suveryn-tracker#54).

### Copy decided along the way

- The tagline stays in English in every language, the sign-in screens included: a brand line, not a translation gap.
- Every answer, also one without documents, addresses the person formally (u, uw; vous).

## Open

- **Playbook creation by an administrator**: decide after the third hand-built playbook
  (platform.md).
- **A dark-theme check of artboard 02**: `case-surface` has a dark value, but no dark screen has
  been drawn.
- **The reading budget** (section 10): measure on a GPU machine before raising the whole-document budget.
- *Administration*: see [admin.md](admin.md), *Open*.
