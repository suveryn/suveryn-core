# chat-ui

The sūveryn chat interface: React, TypeScript and Vite, light theme. It talks only to the gateway on the same origin and loads nothing from the internet: fonts and icons are bundled.

## Run it

```bash
npm ci               # exactly the versions in package-lock.json
npm run dev          # http://localhost:5173, proxies /auth, /v1 and /health to the gateway
```

Open it at **http://localhost:5173**: the gateway's `SUVERYN_PUBLIC_URL` and Keycloak's redirect URI use `localhost`. The gateway address defaults to `http://127.0.0.1:8000`; override it with `SUVERYN_API=http://host:port npm run dev`. In development the gateway usually runs on the GPU machine and is reached through an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 -L 8180:127.0.0.1:8180 root@<gpu-host> -p <ssh-port>   # gateway and Keycloak
```

Other commands:

- `npm test`: unit tests (SSE parsing, answer rendering, copy and download, that the brand files match `suveryn-brand`, the web setup's text and rules, and the Content-Security-Policy rules: `src/csp.test.ts`)
- `npm run brand:sync`: re-copy the brand files from `suveryn-brand` (see below)
- `npm run typecheck`
- `npm run build`: static files in `dist/` (the chat, `index.html`, and the appliance's web setup, `setup.html`), plus `THIRD-PARTY-NOTICES.txt`

The web setup also runs on the dev server, at **http://localhost:5173/setup.html**, with example network settings when no appliance answers.

## The UI flow

0. **Sign in.** Signed out, the chat goes straight to the office's Keycloak login page (in the interface language), which already has the logo, tagline and language menu, and comes back signed in. Its own sign-in screen appears only when it has something to say: the session ended while working (redirecting then would discard what was being typed), sign-in isn't available (Keycloak unreachable), or the user came back signed out within a minute of being sent to the login page (the Back button, or a sign-in that didn't complete; redirecting again would loop) (`lib/signin.ts`). The sidebar shows the signed-in user and *Sign out*, which also ends the Keycloak session. If a session ends (expired, or ended by an admin), the next request shows the sign-in screen again and the open conversation is closed.
1. **Start.** The empty state shows the tagline, "AI for work that can't leave the premises". The sidebar lists the documents already on the server.
2. **Attach.** The paperclip (or clicking a document in the sidebar) adds a PDF to the next message as an attachment chip. A new upload shows *Uploading…*, *Waiting…*, then *Reading…* while the server extracts it. Sending is paused until every attachment is read.
3. **Ask.** The question appears in the user's bubble, with the attachment chips above it. The answer streams in below, with no bubble, marked by the teal brand mark. Until the first word arrives, three small outlined squares, bouncing in turn, and a line of status text say what the server is actually doing: *Searching your documents…*, *Reading the 6 passages that best match your question…* (or *Reading your documents (n passages)…* when the whole document fits), *Loading Mistral Small 3.2, which can take up to half a minute…* when a switched model isn't in memory yet, or *Writing the answer…*. The squares stay at the end of the text while it streams. With reduced motion turned on, they don't move.
4. **Check the source.** Every `[n]` in the answer becomes a small teal marker. Clicking a marker, or a chip under *Sources*, opens the passage it came from: file name, page, section heading and the stored text. The sentence the claim rests on is marked lightly, its figures, dates and names more strongly, and the passage scrolls to it (`lib/answer.ts`): for a marker, the claim before that marker; for a chip, every claim citing the source. **Copy** in that panel copies the passage with its reference (`[1] file.pdf, p. 3 · Artikel 2` and the text below it); **Copy sources** copies every cited passage of the answer, numbered like the markers. **Download** next to each offers **Text (.txt)** or **Markdown (.md)** (one source: `source-1_akte_p3.txt`/`.md`; all sources: `sources_<question>.txt`/`.md`, headed by the question and the date). In Markdown the reference is a heading and the passage a block quote; the passage text is never altered. Both happen in the browser; nothing is sent to the server. Copied or downloaded passages are confidential and leave sūveryn's control: they sit on the clipboard or in the Downloads folder until the user deletes them. The answer can also show these notices:
   - *No source is cited…* when documents were used but nothing was cited;
   - *Not based on your documents…* when no documents were attached;
   - *Check …: these figures aren't in the documents and weren't calculated by sūveryn…* when the answer contains a figure in no source and no server calculation (`unverified_figures`); each such figure is underlined (wavy, in accent-ink) in the answer;
   - *Calculated by sūveryn, not read from the documents…* under an answer with a total or other calculation, which the server computed exactly from figures in the sources (with a warning if a figure isn't in them).
4b. **Choose the model.** The model badge in the composer is a menu of the models installed on this appliance (from `GET /v1/models`), each marked *Ready* or *Loads when chosen*. It works from the keyboard (Enter opens it, the arrow keys move, Escape closes it) and is a menu of radio items for screen readers (the component library's `MenuButton`). The choice holds for the conversation. A model that isn't loaded makes the next answer wait while it loads (up to about half a minute), and the note under the composer says that other people's questions wait too, because the GPU holds one model at a time. With one installed model the badge is a plain tag.
5. **Follow up.** Later questions in the same conversation automatically use every document attached so far. Each question is sent with the earlier questions and answers that completed; a question whose answer failed is left out. *New chat* starts over. Deleting a document from the sidebar asks for confirmation first.
6. **Come back to it.** After each answer the whole conversation is saved on the server, where only you can see it (suveryn-tracker#5). *Conversations* in the sidebar lists them, newest first, named after their first question; clicking one opens it again and you can carry on. A document deleted since is left out of follow-up questions. The bin icon deletes a conversation after confirmation. Nothing is written to browser storage. Without a database on the server, the sidebar says that conversations aren't saved and the conversation lasts as long as the page.
7. **Sign out.** With saved conversations, *Sign out* asks *Keep your chat history?*. *Keep and sign out* is the default and has the focus; *Delete history and sign out* deletes every saved conversation first (and stays signed in if that fails); *Cancel* or Escape stays signed in. Without saved conversations it signs out at once.

If the model is starting or unreachable, the composer says so and sending is disabled. If an answer breaks off, the partial text is discarded and a notice asks you to try again.

## Tables, Word and Excel

- **Tables:** a Markdown table in an answer is shown as a real table (`lib/answer.ts`), so copy and paste into Excel or Word keeps the columns. The model is told to answer with one when asked for a table, an overview or an Excel or Word file (suveryn-chat's `GROUNDED_INSTRUCTIONS`).
- **Word:** every complete answer has a *Word (.docx)* button. The document holds:
  - the question and the date;
  - the answer, with its tables and lists;
  - what to check (calculations, figures, citations);
  - every cited source with its passage, or "Source deleted".
- **Excel:** every table has an *Excel (.xlsx)* button.
  - **The table sheet** has a frozen header and a last column naming each row's sources. Unambiguous amounts become numbers (`EUR 1.275.000,00` → 1275000 in euro format). Dates, references and anything ambiguous (`1.275`, `0123`) stay text. A column the model filled with source markers only is left out.
  - **The other sheets:** a sources sheet, and a sheet of what to check.
- **How the files are made:** in the browser (`lib/office.ts`) with [docx](https://github.com/dolanmiu/docx) and [write-excel-file](https://gitlab.com/catamphetamine/write-excel-file), both MIT. They load on the first download only, about 540 kB, and the chat itself stays about 9 kB larger. Nothing is sent anywhere. Their licences, and those of what they bundle, are in `THIRD-PARTY-NOTICES.txt` (`npm run notices`).

## Components (suveryn-tracker#44)

Screens are built from a small component library in [`src/ui/`](src/ui/), shared by the chat and the web setup. It sits on [React Aria Components](https://react-spectrum.adobe.com/react-aria/) (Adobe, Apache-2.0), which gives keyboard use, focus handling and screen-reader semantics, and has no look of its own; the look is `src/ui/ui.css`, from the brand tokens, through React Aria's `data-*` states (`[data-selected]`, `[data-focus-visible]`, …). Product screens use only `src/ui`, never React Aria directly.

| Component | For |
|---|---|
| `Button` | primary, secondary or quiet |
| `TextField`, `PasswordField` | label, hint and error tied to the field; a show/hide toggle |
| `Form` | errors shown on submit only (React 19 action), focus to the first field in error |
| `RadioCards`, `RadioList` | one choice of a few, with the arrow keys |
| `Select` | one value from a list (the language menu) |
| `MenuButton` | a menu that acts at once (the model menu) |
| `Card`, `Steps`, `Note`, `Facts`, `Chips` | layout, no behaviour |

**The CSP.** How this UI keeps to the appliance's Content-Security-Policy, what to check before adding a library and what to do when the build stops with a CSP error: [docs/content-security-policy.md](../../docs/content-security-policy.md). `src/csp.test.ts` checks the source against its rules. In short: the appliance sends `style-src 'self'` without `'unsafe-inline'`. React Aria writes two `<style>` elements of its own, which the browser would refuse (and report): `src/ui/csp.ts` makes it skip the first (pressable elements), and a build step in `vite.config.ts` replaces the second (iPhone and iPad, while a menu is open) with an attribute; `ui.css` carries both rules instead. The build fails if a React Aria update changes that code. Style properties React Aria sets through the DOM (a popover's position) are allowed.

**Forms** use React 19's `useActionState`, started from `onSubmit`: given the form's `action`, React resets the form after each submit, and React Aria's fields follow the reset, which wiped every answer when Continue found an error. Fields don't use React Aria's built-in validation (`isRequired`, the browser's own `type="email"` check), whose messages come from the browser, in its language, and can appear while typing. Errors come from the screen's check, in the interface language, when the form is submitted.

React Aria's own strings (e.g. "selected") are kept for English, Dutch and French only (`@react-aria/optimize-locales-plugin`). The spike's measurements: [`docs/spikes/react-aria/`](../../docs/spikes/react-aria/README.md).

## The web setup (setup.html)

The appliance's first-boot setup in the browser (suveryn-tracker#37; design in suveryn-appliance `docs/design/first-boot-setup/`). Its own entry and bundle: `setup.html` and [`src/setup/`](src/setup/). It shares the component library, fonts and tokens with the chat and nothing else: no sign-in (setup creates the first account, so it can't depend on Keycloak), no chat code. The appliance serves it only until setup finishes.

- Laid out like the Keycloak login: the lockup and tagline, a 560 px card, the language menu in the card's top-right corner, the same focus ring.
- It asks the appliance `GET setup/v1/state` for what the console installer set (name, address, language).
- Steps so far: 1 Network (Connected with approved destinations or everything, or Air-gapped) and 2 Administrator account (at least 15 characters, not a common password, not the name, email address or appliance name; errors on Continue only). Welcome and steps 3 to 6, and saving the answers, follow in #37.
- Its text is in [`src/setup/text.ts`](src/setup/text.ts), in English, Dutch (formal) and French (vous); the language starts as the one chosen at installation.

## Token usage

The sidebar shows the signed-in user's own token count for today (*1.2k tokens today*); clicking it opens **Your usage**: requests and input, output and total tokens over the last hour, day, week or month, or chosen whole days, with a bar chart and a split by kind (suveryn-tracker#7). Only the user's own usage is shown, never a colleague's. Administrators (Keycloak role `suveryn-admin`) also get **Administration**: the office's usage in total and **per user**, the notional cost on a cloud API at editable rates per million input and output tokens (default $3 and $15), and who last changed them. Rolling periods end at the server's clock, not the browser's. Usage is informational only: nothing is ever limited because of it.

## Languages

English (UK), Dutch and French (suveryn-tracker#8). Every string the interface shows is in a table per language in [`src/i18n/`](src/i18n/): [`en.ts`](src/i18n/en.ts) defines the keys, and [`nl.ts`](src/i18n/nl.ts) and [`fr.ts`](src/i18n/fr.ts) must have all of them. TypeScript checks that, so a missing translation fails the build, and a test checks that no text is empty. Components use `useT()`; plain functions use `t()`. No i18n library is used.

- **Which language:** the one chosen in the language menu (sidebar foot, the sign-in screen when shown, and Keycloak's own menu on its login page; remembered in this browser), else the browser's preferred language when it is one of the three, else English. `<html lang>` follows it. Keycloak's login page opens in the same language (`/auth/login?lang=nl` → `ui_locales=nl`).
- **Dutch is formal** (*u/uw*); a test fails on *je/jij/jouw*. **French** uses *vous*.
- **sūveryn** stays lower case except at the start of a sentence (also tested).
- **The tagline** stays in English in every language, as on the website and the login page.
- **Dates** follow the language (`en-GB`, `nl-BE`, `fr-BE`), also in downloaded sources.
- **What stays English:** most messages that come from the server (a calculation's error, a model server's error) and model names. The errors people meet most (too many requests, too large, not found, no permission, unavailable, an invalid request) are shown in the interface language by HTTP status (`httpErrorText` in `api.ts`). Answers are in the language of the question, whatever the interface language.

To add a string: add it to `en.ts`, then to `nl.ts` and `fr.ts` (the build tells you where).

## Brand elements

[suveryn-brand](https://github.com/suveryn/suveryn-brand) is the single source of the mark, favicon, fonts and design tokens. `scripts/brand-sync.mjs` copies them in at a pinned commit and generates `src/styles/tokens.css` from [`tokens/tokens.json`](https://github.com/suveryn/suveryn-brand/blob/main/tokens/tokens.json):

```bash
npm run brand:sync                 # re-sync at the commit in src/brand/brand-lock.json
npm run brand:sync -- <commit>     # move to a newer brand commit
```

The copies are committed, so building never needs the internet. `src/brand/brand-lock.json` records the commit and a hash of each file, and `npm test` fails if one is edited by hand. Never edit `tokens.css` or the brand files directly; change `suveryn-brand` and re-sync.

## Brand rules this UI keeps

From the [brand guidelines](https://github.com/suveryn/suveryn-brand/blob/main/guidelines/brand-guidelines.md):

- Light theme tokens only (`src/styles/tokens.css`, generated from `suveryn-brand`).
- Only the user's turn has a bubble. The assistant's reply is marked by the teal brand-mark outline.
- Attachment chips (outlined, on the user's turn) and citation chips (teal, on the reply) are different components.
- Text and icons on the accent colour use `--on-accent`, never white.
- IBM Plex Mono is used only for the wordmark. Headings use Space Grotesk, everything else Inter.
- Icons come from Lucide. The model tag in the composer is neutral, a name with no vendor logo.
- UI copy is in UK English.

## Licences

- The code is AGPL-3.0-or-later, like the rest of `suveryn-core`.
- `src/brand/`, `public/favicon.svg` and `public/apple-touch-icon.png` hold the sūveryn brand mark, which is **not** AGPL; see [src/brand/README.md](src/brand/README.md) and the [trademark policy](https://github.com/suveryn/suveryn-brand/blob/main/TRADEMARK_POLICY.md).
- The fonts (`src/fonts/`, from `suveryn-brand`) are SIL Open Font Licence 1.1.
- Bundled third-party software (React, React Aria, Lucide, the fonts) is listed with its licence texts in [public/THIRD-PARTY-NOTICES.txt](public/THIRD-PARTY-NOTICES.txt), which `npm run build` regenerates.
