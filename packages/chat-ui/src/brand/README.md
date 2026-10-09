# Brand assets: not covered by this repository's AGPL licence

`suveryn-icon.svg` (here), `../../public/favicon.svg` and `../../public/apple-touch-icon.png` are copies of the Sūveryn brand mark from the `suveryn-brand` repository, made by `scripts/brand-sync.mjs` at the commit recorded in `brand-lock.json`. The mark is all rights reserved and governed by `suveryn-brand`'s `TRADEMARK_POLICY.md`; it is **not** licensed under AGPL-3.0 with the rest of `suveryn-core`.

Forks and redistributions must replace these files with their own mark unless the trademark policy allows otherwise. The UI degrades gracefully: the wordmark is plain text, and these are the only brand files. (The fonts in `../fonts/` come from `suveryn-brand` too, but are SIL Open Font Licence, not restricted.)

Do not edit or recolour the files; `brand.test.ts` fails if they differ from the locked brand commit. To update them, change `suveryn-brand` and run `npm run brand:sync -- <commit>`. The assistant marker in the chat (`components/AssistantMark.tsx`) draws the same geometry in teal outline, as specified by the Design System's `ChatMessage` component.
