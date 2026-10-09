# chat-ui

The Sūveryn chat interface: React, TypeScript and Vite, light theme. It talks only to the gateway on the same origin and loads nothing from the internet: fonts and icons are bundled.

## Run it

```bash
npm install
npm run dev          # http://127.0.0.1:5173, proxies /v1 and /health to the gateway
```

The gateway address defaults to `http://127.0.0.1:8000`; override it with `SUVERYN_API=http://host:port npm run dev`. In development the gateway usually runs on the GPU machine and is reached through an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 root@<gpu-host> -p <ssh-port>
```

Other commands:

- `npm test`: unit tests (SSE parsing, answer rendering, model names)
- `npm run typecheck`
- `npm run build`: static files in `dist/`, plus `THIRD-PARTY-NOTICES.txt`

## The UI flow

1. **Start.** The empty state shows the tagline, "AI for work that can't leave the premises". The sidebar lists the documents already on the server.
2. **Attach.** The paperclip (or clicking a document in the sidebar) adds a PDF to the next message as an attachment chip. A new upload shows *Uploading…*, *Waiting…*, then *Reading…* while the server extracts it. Sending is paused until every attachment is read.
3. **Ask.** The question appears in the user's bubble, with the attachment chips above it. The answer streams in below, with no bubble, marked by the teal brand mark.
4. **Check the source.** Every `[n]` in the answer becomes a small teal marker. Clicking a marker, or a chip under *Sources*, opens the passage it came from: file name, page, section heading and the stored text. The answer also shows a notice when it has no citations:
   - *No source is cited…* when documents were used but nothing was cited;
   - *Not based on your documents…* when no documents were attached.
5. **Follow up.** Later questions in the same conversation automatically use every document attached so far. *New chat* starts over. Deleting a document from the sidebar asks for confirmation first.

If the model is starting or unreachable, the composer says so and sending is disabled. If an answer breaks off, the partial text is discarded and a notice asks you to try again.

## Design System rules this UI keeps

- Light theme tokens only (`src/styles/tokens.css`, copied from the Design System).
- Only the user's turn has a bubble. The assistant's reply is marked by the teal brand-mark outline.
- Attachment chips (outlined, on the user's turn) and citation chips (teal, on the reply) are different components.
- Text and icons on the accent colour use `--on-accent`, never white.
- IBM Plex Mono is used only for the wordmark. Headings use Space Grotesk, everything else Inter.
- Icons come from Lucide. The model tag in the composer is neutral, a name with no vendor logo.
- UI copy is in UK English.

## Licences

- The code is AGPL-3.0, like the rest of `suveryn-core`.
- `src/brand/` and `public/favicon.svg` hold the Sūveryn brand mark, which is **not** AGPL; see `src/brand/README.md`.
- Bundled third-party software (React, Lucide, the fonts) is listed with its licence texts in `public/THIRD-PARTY-NOTICES.txt`, which `npm run build` regenerates.
