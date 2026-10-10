# suveryn-core architecture

This document is for people reviewing or extending `suveryn-core`. It covers:

- what is built so far
- where confidential data goes
- which rules the code must keep
- which decisions were made, and on what evidence
- what is known to be incomplete
- how to verify a change, with a review checklist

Related repositories:

- [suveryn-docs](https://github.com/suveryn/suveryn-docs): installation and administration documentation, and the [October 2026 hardware benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md) that the model, OCR and sizing decisions below rely on.
- [suveryn-appliance](https://github.com/suveryn/suveryn-appliance): the OS image and the runtime services this repository uses but doesn't bundle (PostgreSQL with pgvector, Keycloak, the model server).
- [suveryn-brand](https://github.com/suveryn/suveryn-brand): the mark, fonts and design tokens the chat UI copies in (see [packages/chat-ui](../packages/chat-ui/README.md#brand-elements)).

## 1. What exists today

| Package | State | Responsibility |
|---|---|---|
| [`packages/engine`](../packages/engine/README.md) | Built | Model server client; request, answer, citation and calculation schema |
| [`packages/api-gateway`](../packages/api-gateway/README.md) | Built | HTTP API: `POST /v1/chat`, `/v1/documents` (upload, list, delete, job status), `GET /health`; sign-in with Keycloak (`/auth/...`) gating every `/v1` request |
| [`packages/rag`](../packages/rag/README.md) | Built | Ingestion (extraction, chunking, embeddings, storage) and retrieval |
| [`packages/chat`](../packages/chat/README.md) | Built | Grounded answers: passages → numbered excerpts → answer citing `[n]`; server-side calculations |
| [`packages/chat-ui`](../packages/chat-ui/README.md) | Built | React/TypeScript chat interface (light theme). Builds to static files in `dist/`; in development Vite proxies `/v1` and `/health` to the gateway. How the static files are served in production (on the same origin as the API) is decided by suveryn-appliance |
| `packages/mcp-host`, `connectors`, `playbooks` | Placeholders | Later phases |

Runtime services are **not** part of this repository. PostgreSQL with pgvector, Keycloak and the model server ([llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server`) are installed and configured by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance). This repository only contains clients for them. For development, [packages/api-gateway/keycloak](../packages/api-gateway/keycloak/README.md) describes a local Keycloak with the `suveryn` realm.

Chat requests with `document_ids` are grounded in those documents and cite their passages. Answers are not yet *checked* against their sources (see §6); the UI therefore marks unsourced answers and lets the user open every cited passage.

## 2. Data flow

```
                       ┌──────────────────────── packages/rag ────────────────────────┐
PDF ──► extract.py ──► chunking.py + integrity.py ──► embed.py ──► store.py (PostgreSQL + pgvector)
        │ ocr_fast: OCR    │ HybridChunker, page numbers,     │ bge-m3      │ documents, chunks,
        │ pages <50 chars  │ headings; completeness, footer   │ 1024-dim    │ HNSW + full-text index
        │ or ≥10% images,  │ rule, text-layer recovery,       │             │
        │ OCRmyPDF in      │ page coverage → status and       │             ▼
        │ parallel, Docling│ warnings                         │      Rag.passages(question, documents)
        │ layout on GPU    │                                  │      ≤ 48,000 chars and ≤ 99 chunks: every chunk, reading order
        ▼                                                     │      else: hybrid search, 6 best → Citation
   private work dir (0700), deleted after each document              {text, source: {document_id, page, location}}

browser (chat-ui) ──► api-gateway ──► POST /v1/documents ──► DocumentService queue ──► one worker: rag.ingest
                                    └─► POST /v1/chat {messages, document_ids}
                                          └─► chat.ChatService ──► Rag.passages ──► numbered excerpts ("complete text" or "best matches")
                                                              ──► engine.LlamaServerClient ──► llama-server (Qwen3.8-27B)
                                                              ──► chat.calc: [[calc: …]] markers replaced by exact results as the answer streams
                                          ◄── SSE: delta… then done {answer with [n], citations[n-1], calculations} | error
```

Sign-in (OpenID Connect, [`auth.py`](../packages/api-gateway/src/suveryn_api_gateway/auth.py)):

```
browser ──► GET /auth/login ──► gateway: state, nonce, PKCE verifier (memory) ──► 303 to Keycloak login (local accounts | LDAP, optional TOTP)
browser ◄── Keycloak 302 /auth/callback?code&state ──► gateway: state = login cookie? code + verifier + client secret ──► Keycloak token endpoint
                                                       validate ID token (JWKS signature, issuer, audience, expiry, nonce) ──► session (memory)
browser ◄── 303 + HttpOnly session cookie;  every /v1 request: session (refreshed via Keycloak) or bearer token, else 401
```

All model libraries run offline: importing `suveryn_rag` sets `HF_HUB_OFFLINE` and the telemetry opt-outs ([`offline.py`](../packages/rag/src/suveryn_rag/offline.py)); models are put in the local cache once at set-up with `suveryn-fetch-models`.

## 3. Where confidential data lives

Deeds contain personal data (names, national register numbers, addresses, amounts). Every place it can exist:

| Place | What | Lifetime | Protection today | Open item |
|---|---|---|---|---|
| Original PDF | Whole document | Owned by the caller; `rag` only reads it | none needed by rag | — |
| Private work directory (`SUVERYN_WORK_DIR/doc-*`) | Searchable PDF and OCR work files | During one document's extraction; leftovers of a crash are deleted when the document service starts | `0700`; deleted on success and on error; `TMPDIR`/`tempfile` redirected so nothing goes to `/tmp` | — |
| Gateway temp folder (`SUVERYN_WORK_DIR/tmp/<pid>`) | Uploads while they are received (Starlette spools files over 1 MB to a temporary file) | During the request; removed on exit; folders of processes no longer running are removed on start | `0700`; `TMPDIR`/`tempfile` point here instead of `/tmp`, also when the app runs under bare `uvicorn` ([`main.py`](../packages/api-gateway/src/suveryn_api_gateway/main.py)) | — |
| Upload folder (`SUVERYN_WORK_DIR/uploads`) | Uploaded PDFs waiting for ingestion | Until their job ends (deleted on success and failure); the folder is removed on shutdown and on start (crash leftovers) | `0700` folder, `0600` files, random names | — |
| Process memory | Docling document, page texts; upload jobs (file names, status, error text up to 200 characters) | During ingestion; finished jobs for one hour, all jobs until restart | — | — |
| Prompts sent to llama-server | The question, the history, and the excerpts: up to 48,000 characters of whole documents per question | During the request, then in the prompt cache (below) | Loopback connection | — |
| llama-server prompt cache (GPU memory + RAM, `-cram`) | Prompts incl. document text | Until evicted or restart | none | Retention and encryption |
| PostgreSQL `documents` | File name (may contain a client's name), hash, status, warnings, owner (the uploader's Keycloak user id) | Until deleted | Database access control | Encryption at rest, retention |
| PostgreSQL `chunks` | Document text, embeddings | Until deleted | Database access control | `DELETE` leaves data in table files until VACUUM and in the WAL for a while; secure deletion (crypto-shredding) is open |
| Gateway memory: sessions | Per signed-in browser: user id, username, display name, ID/access/refresh tokens | Until logout, expiry, or a gateway restart | Never sent to the browser (it only holds an opaque, HttpOnly session id); not logged | A shared, encrypted session store if the gateway ever runs as several processes |
| Keycloak database | User accounts, password hashes, TOTP secrets, sessions, login events | Managed by Keycloak | Keycloak's own (suveryn-appliance configures it; development uses `start-dev` with an H2 file) | Backup and encryption are appliance concerns |
| Browser memory (chat UI) | The conversation, cited passages | Until the tab is closed or *New chat* | Not written to browser storage | Server-side conversation history, if ever added, needs a retention design |
| User's clipboard and Downloads folder | Passages copied or downloaded (`.txt`/`.md`) from the chat UI | Until the user deletes them | Outside sūveryn's control; done only on the user's click | Consider a notice in the UI |
| Logs | Gateway: method, path, status; unexpected stream errors by exception type only. rag: none | — | No document text is logged | Keep it that way |
| Terminal output of `suveryn-retrieve` | Passages | Developer's terminal | — | Don't pipe into shared logs |

Integrity warnings contain counts and lengths, never document text. They can be shown to administrators safely.

## 4. Invariants (what must stay true)

Reviewers: check changes against these.

1. **No intermediate document file outside the private work directory.** Anything that writes temp files during extraction must run inside `private_workdir()`; uploads are spooled only to the gateway's private temp folder.
2. **No silent text loss.** Every body text item ends up in a chunk. Header/footer text is only dropped when it is a page number or really repeats. Text the layout model dropped is recovered from the PDF text layer. A page whose stored text still falls short of its text layer puts the document in `needs_review` (`integrity.py`).
3. **Chunks carry their page.** `source.page` is what lets a person verify an answer. Docling gives every chunk its page in practice; a chunk without page provenance is stored with `page: null` and shown without a page (not enforced; see §6).
4. **Unsourced means unverified.** `citations: []` or `source: null` must be shown to users as unverified, never as fact.
5. **No document text in logs or in error messages we generate.** Backend error texts are passed on (truncated to 200 characters); they come from llama-server, not from documents. Unexpected errors during a stream are reported generically.
6. **Nothing in `/v1` without a signed-in user.** Every `/v1` request needs a valid session or bearer token (`auth.py`); state-changing requests with a session cookie must also come from the UI's own origin. Tokens never reach the browser. Only Keycloak's own users (local accounts, optionally LDAP/AD federation and TOTP) can sign in: no social or online identity providers, in any tier or network mode. Sign-in can only be turned off (`SUVERYN_AUTH=off`) on a loopback address.
7. **Users see only their own documents.** Every document, upload and job has an owner (the uploader's Keycloak user id). Listing, job status, deletion and grounded chat check it, and another user's document is answered with 404, like a missing one; the gateway checks before a chat starts and the retriever checks again before reading passages. De-duplication by file hash is per owner, so an upload never returns someone else's document. Documents without an owner (stored before owners existed, or by `suveryn-ingest` without `--owner`) are visible to no user.
8. **No outbound network calls at runtime.** Air-gapped installs must work: no CDN assets (`/docs` is off by default), no telemetry, no model downloads (`suveryn_rag.offline`). The gateway talks only to the local Keycloak. The chat UI bundles its fonts and icons and only calls its own origin.
9. **SQL takes input only as bound parameters.** f-strings in `store.py` interpolate constants and fixed fragments only.
10. **Ingestion is single-threaded per process** (process-wide `TMPDIR` redirection), and heavy work is queued. Two concurrent whole-document summaries failed in the benchmark.
11. **The model's own arithmetic is never shown as a result.** Calculations are written as `[[calc: …]]` and computed by [`chat/calc.py`](../packages/chat/src/suveryn_chat/calc.py) with `Decimal` and a hand-written parser (never `eval`). A calculation that can't be done unambiguously is refused and shown as such, never guessed.
12. **Positional citation contract.** `[n]` in `answer` is `citations[n-1]`. Markers have one or two digits (`grounding._MARKER`, `answer.ts` `MARKER`), so whole-document grounding is capped at 99 chunks (`WHOLE_DOCUMENT_CHUNKS`).

## 5. Decisions and their evidence

| Decision | Evidence |
|---|---|
| Python backend, FastAPI, uv workspace | The validated document pipeline (Docling, OCRmyPDF, sentence-transformers) is Python-native |
| Qwen3.8-27B default, Mistral Small 3.2 24B as the faster alternative; nothing model-specific in code | [Benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md): Qwen made fewer legal errors on real deeds; Mistral is 20–40% faster |
| `ocr_fast`: skip text pages, OCRmyPDF in parallel, Docling on the text layer | [Benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md): 3.7–8× faster than Docling calling Tesseract per page |
| OCR every page with less than 50 characters of text, not OCRmyPDF's `skip_text` | `skip_text` skips a scanned page that carries a thin digital label (copier, e-stamp); its content was lost. Covered by the `scanned-thin-text` regression variant |
| Also OCR born-digital pages whose raster images cover at least 10% of the page, with `redo_ocr` (keeps digital text, reads only the images) | A pasted-in scan's text was never read. Covered by the trap deed's pasted-in soil report; logos/signatures/stamps cover 1–5% (real deed: 2.6%), so they don't trigger OCR |
| bge-m3 embeddings | Multilingual (Dutch, French, English), as Belgian deeds are |
| 384-token chunks with page provenance | Citations must point at a specific passage and page |
| Hybrid retrieval (vector + full-text, RRF), very common query words ignored | Real deeds: right passage at #1 went from 12/19 to 15/19, top 3 from 17/19 to 19/19; a buried tenant arrears went from #9 to #1 |
| Small documents (`WHOLE_DOCUMENT_CHARS` = 48,000 characters together, `WHOLE_DOCUMENT_CHUNKS` = 99) are given to the model whole, in reading order; larger ones as the 6 best search hits | A general question about a short bank statement got 6 near-random passages, one of them a bare reference code, and the model rightly said the answer wasn't there. The benchmark showed whole-document answers work up to ~60 pages. 48,000 characters is ~14k tokens of Dutch or French, which fits a parallel slot's share of the context (`-c 65536 -np 4` with a unified KV cache) with room for history and the answer. The chunk cap keeps markers to two digits |
| The model never does arithmetic: it writes `[[calc: …]]` with figures copied from the excerpts; the server computes it exactly, refuses mixed or ambiguous number styles, and checks each figure (as a whole number) against the passages the answer cites | Asked to add up two sales on a real statement, the model (rightly, under a no-calculation rule) refused; LLM arithmetic is unreliable, so the server does it and the UI marks the result as calculated |
| Chunks of fewer than three words (`MIN_WORDS_FOR_VECTOR`) are left out of the vector ranking (still found by keyword) | Their embeddings sit close to vague questions; a 40-character reference code took a passage slot |
| Completeness check, footer rule, text-layer recovery, page coverage | Real deeds: a closing certification line and 14 short headings and fragments were silently lost before; on a real bank statement the table model dropped 4 words of a table, now recovered from the text layer |
| People choose the model per conversation from the installed ones (llama-server router mode, `--models-max 1`) | Requested in suveryn-tracker#4. A 24 GB card holds one model at a time, so a switch unloads the current model once its running answers finish (measured: a long answer was never cut off; the next model was ready after ~5 s with the file in the page cache, 26–32 s from a network volume). The UI says so before the switch |
| Models load offline only; `suveryn-fetch-models` fills the cache at set-up | Left to their defaults, the Hugging Face libraries download models on first use and contact huggingface.co (with usage data) on every load |
| Brand elements copied from suveryn-brand at a pinned commit, hashes in `brand-lock.json`, a test fails on drift | One source of truth for the mark, fonts and tokens; building must work without internet access |
| NVIDIA's CUDA libraries (installed with PyTorch on the GPU machine) may ship in the appliance image | They are proprietary and redistributed under NVIDIA's licence, separate from the AGPL code; this was reviewed and accepted (October 2026). The appliance with a consumer (GeForce) GPU is for on-premise office use: NVIDIA's GeForce driver licence does not allow datacenter deployment, so a hosted or datacenter installation needs a datacenter-class GPU |
| `/docs` off by default | FastAPI's docs pages load scripts and fonts from public CDNs, which breaks air-gapped installs and contacts third parties |
| Sign-in as a backend-for-frontend: the gateway is a confidential OIDC client (authorization code + PKCE S256), keeps the tokens, and gives the browser an HttpOnly session cookie | Tokens in browser JavaScript can be stolen by any script injection; a server-side session can also be ended at once. The gateway already sits between the UI and every service, and it can keep a client secret (a browser can't) |
| Only Keycloak's own users: local accounts as the baseline, LDAP/AD federation and TOTP as options an admin enables; no social or online identity providers | They need a live third party, which fails air-gapped and undercuts the on-premise promise. Local accounts must work on their own, so neither LDAP nor TOTP is mandatory in code or in the realm. All three checked against a real Keycloak 26.8 (TOTP enrolled and used; LDAP with a test OpenLDAP) |
| PyJWT (with `cryptography`) for token validation, RS256 only | Maintained, MIT-licensed, small; `python-jose` was avoided (little maintenance). Allowing only the realm's signing algorithm rules out `none`/HMAC confusion attacks |
| Gateway binds to 127.0.0.1 by default; uploads limited by `Content-Length` before they are read | On a network the gateway belongs behind the appliance's TLS reverse proxy; an oversized upload must not fill the disk that holds the work folders |

## 6. Known limitations

| Limitation | Impact | Planned |
|---|---|---|
| Text inside small images (under 10% of the page) on born-digital pages is not read, e.g. a stamp image bearing the notary's name | Small amounts of text can be missing; the page coverage check can't see it (the text was never in the text layer) | Lower the threshold per document type once real deeds show what's needed (real born-digital deed: one 2.6% image, page 8) |
| Identifiers are not validated (amounts in words vs figures, check digits, cadastral pattern) | A garbled number would be stored and cited as is | An entities table with validated identifiers |
| Model answers are not checked against sources | The model can misspell names (seen in the benchmark). The UI marks answers without citations as unverified and lets users open every cited passage, but a cited answer can still contain an uncited figure | Answer check: every name, number and date must appear in a cited passage (calculations already do this for their figures) |
| Products in calculations keep at most 6 decimals; divisions are rounded half up to at least 2 | A rounded result is not marked as rounded | Mark rounded results if notaries need it |
| Whole-document grounding is limited in characters, not tokens; a long conversation history adds to it | A very long conversation about a near-limit document could exceed a slot's context share, and llama-server would refuse or truncate | Count tokens with the model's tokenizer |
| Sessions live in the gateway's memory | A gateway restart signs everyone out (Keycloak's own session lets them back in quickly); several gateway processes would not share sessions | A shared session store when needed |
| Revocation takes effect at the next token refresh | A user disabled or logged out in Keycloak keeps access for up to one access-token lifetime (5 minutes) | Keycloak back-channel logout to end sessions immediately |
| Documents belong to their uploader only | No sharing between colleagues and no per-matter or role-based access yet; documents stored before owners existed are hidden from everyone (re-upload them) | Sharing per matter, and roles, once the office's needs are clear |
| `/health` is public and names the model and llama-server URL | Minor information disclosure on a network | Limit the public part to the status code when the appliance exposes it |
| The Keycloak login page uses Keycloak's default theme | Not branded | A sūveryn login theme (suveryn-appliance or a theme package) |
| One model in GPU memory at a time | When people alternate between models, each switch makes the next question (anyone's) wait for a load, and the prompt cache starts empty | A 48 GB card (Heavy profile) can hold both: `--models-max 2` |
| Upload jobs live in memory | After a gateway restart, polling an earlier job returns 404 (the stored document itself is safe) | Persist jobs if needed |
| Chunks without page provenance are allowed (`page: null`) | Such a passage can't be traced to a page | Warn or put the document in `needs_review` |
| Deleted documents remain recoverable until VACUUM | Weak deletion guarantee | Crypto-shredding with encryption at rest |
| The llama-server prompt cache holds document text unencrypted | Readable by anyone with access to the machine's memory | Retention and encryption design |
| HNSW post-filtering when searching within one document | Fewer vector candidates in very large databases | Tune `hnsw.ef_search` or use iterative scans |
| Page coverage threshold (95%) calibrated on 5 documents | May need tuning | Revisit with more real scans |
| Retrieval quality measured on 3 real and a handful of synthetic documents | Numbers are indicative | Grow the regression set |

## 7. How to verify

- **Fast tests, any machine:** `uv sync --locked && uv run pytest`. These are the engine, chat (including calculations) and gateway tests; rag tests are skipped.
- **Chat UI:** `cd packages/chat-ui && npm ci && npm test && npm run typecheck`. Covers SSE parsing, answer rendering, conversation history, copy and download, and the brand-file hash check.
- **Full tests on the GPU machine:** `uv sync --locked --all-packages`, then `SUVERYN_TEST_DATABASE_URL=… uv run pytest`. This adds the rag units (including the offline guard), pgvector storage, and the end-to-end trap deed ([`test_e2e.py`](../packages/rag/tests/test_e2e.py)) as a born-digital PDF, a scan, and a scan with a thin digital text layer.
- **By hand:**
  - `uv run suveryn-gateway`, then `curl` against `/health` and `/v1/chat` (see [the root README](../README.md))
  - `uv run suveryn-ingest`, `suveryn-retrieve`, `suveryn-forget`, `suveryn-fetch-models` (see [`packages/rag/README.md`](../packages/rag/README.md))

## 8. Review checklist

- [ ] Does the change keep the invariants in §4? Especially no temp files outside `private_workdir`, no document text in logs, and bound SQL parameters.
- [ ] If it touches extraction or chunking: does `test_e2e.py` still pass in all three variants (born-digital with a pasted-in scan, scanned, scanned with a thin text layer)?
- [ ] If it changes retrieval: are hit@1/3/5 and page accuracy on the regression set at least as good as before?
- [ ] If it changes grounding limits: do `WHOLE_DOCUMENT_CHARS` and the history still fit a slot's context share, and does the chunk cap keep markers to two digits?
- [ ] If it touches `calc.py`: are mixed or ambiguous number styles refused rather than guessed, does every failure become a visible `[calculation not possible: …]`, and do the streamed and non-streamed paths give the same text?
- [ ] If it touches the UI: is model output still rendered only as React text (no HTML), and is a partial answer discarded after an `error` event?
- [ ] If it adds an endpoint: is it under `/v1` (signed-in only) or deliberately public, does a state-changing endpoint keep the same-origin check, and does anything that touches documents pass the caller's owner (`owner_of`)?
- [ ] If it touches `auth.py`: do the sign-in tests (`test_auth.py`) and `keycloak/live_login_check.py` still pass, and does no token, code or cookie reach the browser or a log?
- [ ] Does anything new reach the network at runtime (including model or tokenizer loads)? Keycloak is the only service the gateway may call besides llama-server and PostgreSQL.
- [ ] Is every new place where document text is stored or written (cache, temp file, download) listed in §3?
- [ ] Are new thresholds and constants explained (why this value, measured on what)?
- [ ] Were brand files changed only through `npm run brand:sync`?
- [ ] Were dependencies changed? Then check `uv.lock`/`package-lock.json` sources stay on PyPI/npm, run `uvx pip-audit` and `npm audit`, and check new licences are AGPL-compatible.
