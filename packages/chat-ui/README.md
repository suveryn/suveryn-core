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

- `npm test`: unit tests (SSE parsing, answer rendering, copy and download, and that the brand files match `suveryn-brand`)
- `npm run brand:sync`: re-copy the brand files from `suveryn-brand` (see below)
- `npm run typecheck`
- `npm run build`: static files in `dist/`, plus `THIRD-PARTY-NOTICES.txt`

## The UI flow

0. **Sign in.** Signed out, the chat goes straight to the office's Keycloak login page (in the interface language), which already has the logo, tagline and language menu, and comes back signed in. Its own sign-in screen appears only when it has something to say: the session ended while working (redirecting then would discard what was being typed), sign-in isn't available (Keycloak unreachable), or the user came back signed out within a minute of being sent to the login page (the Back button, or a sign-in that didn't complete; redirecting again would loop) (`lib/signin.ts`). The sidebar shows the signed-in user and *Sign out*, which also ends the Keycloak session. If a session ends (expired, or ended by an admin), the next request shows the sign-in screen again and the open conversation is closed.
1. **Start.** The empty state shows the tagline, "AI for work that can't leave the premises". The sidebar lists the documents already on the server.
2. **Attach.** The paperclip (or clicking a document in the sidebar) adds a PDF to the next message as an attachment chip. A new upload shows *Uploading…*, *Waiting…*, then *Reading…* while the server extracts it. Sending is paused until every attachment is read.
3. **Ask.** The question appears in the user's bubble, with the attachment chips above it. The answer streams in below, with no bubble, marked by the teal brand mark. Until the first word arrives, three small outlined squares, bouncing in turn, and a line of status text say what the server is actually doing: *Searching your documents…*, *Reading the 6 passages that best match your question…* (or *Reading your documents (n passages)…* when the whole document fits), *Loading Mistral Small 3.2, which can take up to half a minute…* when a switched model isn't in memory yet, or *Writing the answer…*. The squares stay at the end of the text while it streams. With reduced motion turned on, they don't move.
4. **Check the source.** Every `[n]` in the answer becomes a small teal marker. Clicking a marker, or a chip under *Sources*, opens the passage it came from: file name, page, section heading and the stored text. **Copy** in that panel copies the passage with its reference (`[1] file.pdf, p. 3 · Artikel 2` and the text below it); **Copy sources** copies every cited passage of the answer, numbered like the markers. **Download** next to each offers **Text (.txt)** or **Markdown (.md)** (one source: `source-1_akte_p3.txt`/`.md`; all sources: `sources_<question>.txt`/`.md`, headed by the question and the date). In Markdown the reference is a heading and the passage a block quote; the passage text is never altered. Both happen in the browser; nothing is sent to the server. Copied or downloaded passages are confidential and leave sūveryn's control: they sit on the clipboard or in the Downloads folder until the user deletes them. The answer can also show these notices:
   - *No source is cited…* when documents were used but nothing was cited;
   - *Not based on your documents…* when no documents were attached;
   - *Check …: these figures aren't in the documents and weren't calculated by sūveryn…* when the answer contains a figure in no source and no server calculation (`unverified_figures`); each such figure is underlined (wavy, in accent-ink) in the answer;
   - *Calculated by sūveryn, not read from the documents…* under an answer with a total or other calculation, which the server computed exactly from figures in the sources (with a warning if a figure isn't in them).
4b. **Choose the model.** The model badge in the composer is a menu of the models installed on this appliance (from `GET /v1/models`), each marked *Ready* or *Loads when chosen*. The choice holds for the conversation. A model that isn't loaded makes the next answer wait while it loads (up to about half a minute), and the note under the composer says that other people's questions wait too, because the GPU holds one model at a time. With one installed model the badge is a plain tag.
5. **Follow up.** Later questions in the same conversation automatically use every document attached so far. Each question is sent with the earlier questions and answers that completed; a question whose answer failed is left out. *New chat* starts over. Deleting a document from the sidebar asks for confirmation first.
6. **Come back to it.** After each answer the whole conversation is saved on the server, where only you can see it (suveryn-tracker#5). *Conversations* in the sidebar lists them, newest first, named after their first question; clicking one opens it again and you can carry on. A document deleted since is left out of follow-up questions. The bin icon deletes a conversation after confirmation. Nothing is written to browser storage. Without a database on the server, the sidebar says that conversations aren't saved and the conversation lasts as long as the page.
7. **Sign out.** With saved conversations, *Sign out* asks *Keep your chat history?*. *Keep and sign out* is the default and has the focus; *Delete history and sign out* deletes every saved conversation first (and stays signed in if that fails); *Cancel* or Escape stays signed in. Without saved conversations it signs out at once.

If the model is starting or unreachable, the composer says so and sending is disabled. If an answer breaks off, the partial text is discarded and a notice asks you to try again.

## Token usage

The sidebar shows the signed-in user's own token count for today (*1.2k tokens today*); clicking it opens **Your usage**: requests and input, output and total tokens over the last hour, day, week or month, or chosen whole days, with a bar chart and a split by kind (suveryn-tracker#7). Only the user's own usage is shown, never a colleague's. Administrators (Keycloak role `suveryn-admin`) also get **Administration**: the office's usage in total and **per user**, the notional cost on a cloud API at editable rates per million input and output tokens (default $3 and $15), and who last changed them. Rolling periods end at the server's clock, not the browser's. Usage is informational only: nothing is ever limited because of it.

## Languages

English (UK), Dutch and French (suveryn-tracker#8). Every string the interface shows is in a table per language in [`src/i18n/`](src/i18n/): [`en.ts`](src/i18n/en.ts) defines the keys, and [`nl.ts`](src/i18n/nl.ts) and [`fr.ts`](src/i18n/fr.ts) must have all of them. TypeScript checks that, so a missing translation fails the build, and a test checks that no text is empty. Components use `useT()`; plain functions use `t()`. No i18n library is used.

- **Which language:** the one chosen in the language menu (sidebar foot, the sign-in screen when shown, and Keycloak's own menu on its login page; remembered in this browser), else the browser's preferred language when it is one of the three, else English. `<html lang>` follows it. Keycloak's login page opens in the same language (`/auth/login?lang=nl` → `ui_locales=nl`).
- **Dutch is formal** (*u/uw*); a test fails on *je/jij/jouw*. **French** uses *vous*.
- **sūveryn** stays lower case except at the start of a sentence (also tested).
- **The tagline** stays in English in every language, as on the website and the login page.
- **Dates** follow the language (`en-GB`, `nl-BE`, `fr-BE`), also in downloaded sources.
- **What stays English:** messages that come from the server (error details, a calculation's error) and model names. Answers are in the language of the question, whatever the interface language.

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
- `src/brand/`, `public/favicon.svg` and `public/apple-touch-icon.png` hold the Sūveryn brand mark, which is **not** AGPL; see [src/brand/README.md](src/brand/README.md) and the [trademark policy](https://github.com/suveryn/suveryn-brand/blob/main/TRADEMARK_POLICY.md).
- The fonts (`src/fonts/`, from `suveryn-brand`) are SIL Open Font Licence 1.1.
- Bundled third-party software (React, Lucide, the fonts) is listed with its licence texts in [public/THIRD-PARTY-NOTICES.txt](public/THIRD-PARTY-NOTICES.txt), which `npm run build` regenerates.
