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
| [`packages/api-gateway`](../packages/api-gateway/README.md) | Built | HTTP API: `POST /v1/chat`, `/v1/documents` (upload, list, delete, job status), `/v1/conversations` (saved chat history), `/v1/cases` (cases, suveryn-tracker#10), `/v1/usage` and `/v1/admin/usage` (token usage), `GET /health`; sign-in with Keycloak (`/auth/...`) gating every `/v1` request |
| [`packages/rag`](../packages/rag/README.md) | Built | Ingestion (extraction in an isolated reader process, integrity checks and text repair, chunking, embeddings, storage) and retrieval |
| [`packages/chat`](../packages/chat/README.md) | Built | Grounded answers: passages → numbered excerpts → answer citing `[n]`; server-side calculations; each citation checked against its own passage |
| [`packages/chat-ui`](../packages/chat-ui/README.md) | Built | React/TypeScript chat interface (light theme), and the appliance's first-boot web setup as a second entry (`setup.html`, no sign-in); both on a small component library over React Aria Components (`src/ui`, suveryn-tracker#44). Builds to static files in `dist/`; in development Vite proxies `/v1` and `/health` to the gateway. How the static files are served in production (on the same origin as the API) is decided by suveryn-appliance |
| `packages/mcp-host`, `connectors`, `playbooks` | Placeholders | Later phases; what they will be, and in what order, is in [docs/design/platform.md](design/platform.md) |

Runtime services are **not** part of this repository. PostgreSQL with pgvector, Keycloak and the model server ([llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server`) are installed and configured by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance). This repository only contains clients for them. For development, [packages/api-gateway/keycloak](../packages/api-gateway/keycloak/README.md) describes a local Keycloak with the `suveryn` realm.

Chat requests with `document_ids` are grounded in those documents and cite their passages. Answers are checked against their sources by rule, not by meaning (see §6). Every figure must be in a passage or be a server calculation's result (`unverified_figures`). Every citation's figures, dates and names must be in its own passage (`citation_issues`). The UI flags what fails, marks unsourced answers, and opens every cited passage with the sentence the claim rests on marked.

## 2. Data flow

```
                       ┌──────────────────────── packages/rag ────────────────────────┐
PDF ──► extract.py ──► chunking.py + integrity.py ──► embed.py ──► store.py (PostgreSQL + pgvector)
        │ ocr_fast: OCR    │ HybridChunker, page numbers,     │ bge-m3      │ documents, chunks,
        │ pages <50 chars  │ headings; completeness, footer   │ 1024-dim    │ HNSW + full-text index
        │ or ≥10% images,  │ rule, text-layer recovery,       │             │
        │ OCRmyPDF in      │ page coverage → status and       │             ▼
        │ parallel, Docling│ warnings                         │      Rag.passages(question, documents)
        │ layout on GPU    │ encoding repair, OCR noise left  │      ≤ 48,000 chars and ≤ 99 chunks: every chunk, reading order
        │ (CPU on OOM)     │ out                              │
        ▼                                                     │      else: best matches (exact hybrid ranking) up to the same budget, ≥ 6, reading order → Citation
   private work dir (0700), deleted after each document              {text, source: {document_id, page, location}}

browser (chat-ui) ──► api-gateway ──► POST /v1/documents ──► DocumentService queue ──► one worker: rag.ingest
                                    └─► POST /v1/chat {messages, document_ids}
                                          └─► chat.ChatService ──► Rag.passages ──► numbered excerpts ("complete text" or "best matches")
                                                              ──► engine.LlamaServerClient ──► llama-server (Qwen3.8-27B)
                                                              ──► chat.calc: [[calc: …]] markers replaced by exact results as the answer streams
                                                              ──► chat.support: each claim checked against the passages it cites
                                          ◄── SSE: status… (searching, loading_model, reading, writing), delta… then done {answer with [n], citations[n-1], calculations,
                                                   unverified_figures, citation_issues, instruction_like_sources} | error
```

`extract.py` runs in a separate **PDF reader process** ([`isolation.py`](../packages/rag/src/suveryn_rag/isolation.py)), never in the gateway:
- the reader gets the path of one document and an environment without secrets, and returns validated JSON (never pickle);
- it is replaced when the next document belongs to another owner;
- on an appliance it runs as its own user, without network, under seccomp (suveryn-appliance's `reader-sandbox`, `SUVERYN_EXTRACT_WRAPPER`). Without that wrapper the gateway refuses to read documents unless `SUVERYN_EXTRACT_UNSANDBOXED=1` (development).

Uploads wait in the gateway's private folder; only the document being read is copied into the reader's inbox. A re-upload of a file whose stored copy was read poorly is read again and replaced in place, keeping its id.

Sign-in (OpenID Connect, [`auth.py`](../packages/api-gateway/src/suveryn_api_gateway/auth.py)):

```
browser ──► GET /auth/login ──► gateway: state, nonce, PKCE verifier (sealed in an AES-GCM login cookie) ──► 303 to Keycloak login (local accounts | LDAP, optional TOTP)
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
| Private work directory (`SUVERYN_WORK_DIR/doc-*`) | Searchable PDF, OCR work files, and for PDFs with a form or digital signature a flattened copy | During one document's extraction; leftovers of a crash are deleted when the document service starts | `0700`; deleted on success and on error; `TMPDIR`/`tempfile` redirected so nothing goes to `/tmp` | — |
| Gateway temp folder (`SUVERYN_WORK_DIR/tmp/<pid>`) | Uploads while they are received (Starlette spools files over 1 MB to a temporary file) | During the request; removed on exit; folders of processes no longer running are removed on start | `0700`; `TMPDIR`/`tempfile` point here instead of `/tmp`, also when the app runs under bare `uvicorn` ([`main.py`](../packages/api-gateway/src/suveryn_api_gateway/main.py)) | — |
| Upload folder (`SUVERYN_WORK_DIR/uploads`) | Uploaded PDFs waiting for ingestion (also with a sandboxed reader) | Until their job ends (deleted on success and failure); the folder is removed on shutdown and on start (crash leftovers) | `0700` folder, `0600` files, random names; at most 20 waiting per user and 200 in all | — |
| Reader inbox (`SUVERYN_EXTRACT_INBOX`, sandboxed reader only) | A copy of the one document being read | During its extraction; deleted after it, and on start | Provisioned `2750` folder (owner the gateway, group the reader), `0640` file; never the documents still waiting | — |
| PDF reader process ([`isolation.py`](../packages/rag/src/suveryn_rag/isolation.py)) | The document being read, its Docling document and page texts | During one document's extraction; the process serves one owner's consecutive documents and is replaced for another owner's, after a crash or a time-out | Separate process without the gateway's secrets; no core dumps; killed after `SUVERYN_EXTRACT_TIMEOUT_S`; replaced for another owner's document. On an appliance: its own user, no network, seccomp (`SUVERYN_EXTRACT_WRAPPER`), required unless `SUVERYN_EXTRACT_UNSANDBOXED=1` | Its stderr goes to the gateway's log: check that no library prints document text there |
| Process memory | Docling document, page texts; upload jobs (file names, status, error text up to 200 characters) | During ingestion; finished jobs for one hour, all jobs until restart | The gateway is non-dumpable (`PR_SET_DUMPABLE 0`): other processes of its user can't read its `/proc` environment or memory | — |
| Prompts sent to llama-server | The question, the history, and the excerpts: up to 48,000 characters of the documents per question (whole, or the best-matching passages) | During the request, then in the prompt cache (below) | Loopback connection | — |
| llama-server prompt cache (GPU memory + RAM, `-cram`) | Prompts incl. document text | Until evicted or restart; not cleared when a document is deleted | Only reachable from the machine's memory; named as not covered in the [data lifecycle](https://github.com/suveryn/suveryn-docs/blob/main/administration/data-lifecycle.md) | Clear the slots on delete, or a nightly restart, if an office needs it |
| PostgreSQL `documents` | File name (may contain a client's name), hash, status, warnings, owner (the uploader's Keycloak user id), the case it is in (`case_id`, null for the personal space), origin | Until deleted, or with its case | Database access control; the gateway's scope check (`cases.may`) decides which case a request may see; on the appliance, the encrypted data partition | What deleting guarantees: the [data lifecycle](https://github.com/suveryn/suveryn-docs/blob/main/administration/data-lifecycle.md) |
| PostgreSQL `cases`, `case_members` | The office's file number, a name, the type, a short subject (never a client's name, by design), state, who manages it, its members (Keycloak id, username and name as when added) and their roles | Open cases until deleted; closed cases for the office's keep period (`SUVERYN_CASES_KEEP` as provisioned, changed by an administrator in the dashboard: 6 months, 1 year, 5 years, or until deleted by hand), then deleted with everything in them by the gateway's hourly sweep | Database access control; `cases.may` on every request | — (what deleting guarantees: the [data lifecycle](https://github.com/suveryn/suveryn-docs/blob/main/administration/data-lifecycle.md)) |
| PostgreSQL `case_events` | The access log of each case: who (Keycloak id), when, what (opened, uploaded, asked, deleted a document, members, handover, access), with ids and roles in `detail`, never text | 180 days, then deleted (as the sign-in events); with the case when it is deleted | Database access control; read by the case's manager and the administrators only | — |
| Keycloak admin API (read) | The office's accounts (id, username, name), read by the gateway through the `suveryn-directory` service account (`view-users` only) when a manager adds a colleague | Cached 30 s in the gateway's memory | The client's secret in `gateway-oidc.env` (0600); nothing written to Keycloak | — |
| PostgreSQL `chunks` | Document text, embeddings | Until deleted | Database access control; on the appliance, the encrypted data partition | `DELETE` leaves data in table files until autovacuum reuses the space and in the WAL until it is recycled: unreachable at once, overwritten over time. Crypto-shredding is designed and parked (suveryn-tracker#31) |
| PostgreSQL `token_usage`, `usage_users`, `usage_rates` | Per model call: user id, time, kind, model, token counts (no text); usernames and display names for the administrator's table; the notional-cost rates and who changed them | Kept indefinitely (development context §5.3: one raw-rows table, no rollups) | Database access control; users see only their own usage, administrators (realm role `suveryn-admin`) the office's per user | Retention if an office wants one |
| PostgreSQL `conversations` | Each user's saved chat history: questions, answers, the passages they cite, attachment names, owner (Keycloak user id), the case it is in (`case_id`) | Until the user deletes it (one, or all when signing out); or the office's keep period passes (`SUVERYN_CONVERSATION_MAX_AGE_DAYS`, from the appliance's `--conversations-keep`; counted from the last change, in cases too; none chosen for the office) | Database access control; only the owner can list, read, change or delete them, except a conversation its owner shared with its case (`shared`), which the case's readers can read | As for `chunks`. Deleting a document takes its passages, headings and file name out of them (suveryn-tracker#12); the answer text stays |
| Gateway memory: sessions | Per signed-in browser: user id, username, display name, ID and refresh tokens (the access token is verified, then dropped; only its expiry is kept) | Until logout, expiry, or a gateway restart | Never sent to the browser (it only holds an opaque, HttpOnly session id); not logged | A shared, encrypted session store if the gateway ever runs as several processes |
| Keycloak database | User accounts, password hashes, TOTP secrets, sessions, login events | Managed by Keycloak | Keycloak's own (suveryn-appliance configures it; development uses `start-dev` with an H2 file) | Backup and encryption are appliance concerns |
| Browser memory (chat UI) | The open conversation, cited passages | Until the tab is closed, *New chat* or another conversation is opened (saved on the server after each answer, see `conversations`) | Not written to browser storage | — |
| User's clipboard and Downloads folder | Passages copied or downloaded (`.txt`/`.md`), answers as Word (`.docx`) and tables as Excel (`.xlsx`) from the chat UI | Until the user deletes them | Outside sūveryn's control; done only on the user's click | Consider a notice in the UI |
| Logs | Gateway: method, path, status; unexpected stream errors by exception type only. rag: counts and kinds (e.g. pages the layout model failed on); a failed start-up's error (up to 200 characters, may name the database host). Audit events (`suveryn.audit`): ids, pages and kinds | — | No document text is logged; `/health` gives states only, no addresses or error texts | Keep it that way |
| Terminal output of `suveryn-retrieve` | Passages | Developer's terminal | — | Don't pipe into shared logs |

Integrity warnings contain counts and lengths, never document text. They can be shown to administrators safely.

## 4. Invariants (what must stay true)

Reviewers: check changes against these.

1. **No intermediate document file outside the private work directory.** Anything that writes temp files during extraction must run inside `private_workdir()`; uploads are spooled only to the gateway's private temp folder.
2. **No silent text loss.** Every body text item ends up in a chunk. Header/footer text is only dropped when it is a page number or really repeats. Text the layout model dropped is recovered from the PDF text layer. A page whose stored text still falls short of its text layer puts the document in `needs_review` (`integrity.py`).
3. **Chunks carry their page.** `source.page` is what lets a person verify an answer. Docling gives every chunk its page in practice; a chunk without page provenance is stored with `page: null` and shown without a page (not enforced; see §6).
4. **Unsourced means unverified.** `citations: []` or `source: null` must be shown to users as unverified, never as fact.
5. **No document text in logs or in error messages we generate.** Backend error texts are passed on (truncated to 200 characters); they come from llama-server, not from documents. Unexpected errors during a stream are reported generically. The public `/health` gives states only: no addresses or error texts.
6. **Nothing in `/v1` without a signed-in user.** Every `/v1` request needs a valid session or bearer token (`auth.py`); state-changing requests with a session cookie must also come from the UI's own origin. Tokens never reach the browser. Only Keycloak's own users (local accounts, optionally LDAP/AD federation and TOTP) can sign in: no social or online identity providers, in any tier or network mode. Sign-in can only be turned off (`SUVERYN_AUTH=off`) on a loopback address.
7. **Users see only the scope they may see.** Every document, upload, job and conversation is in one scope (`suveryn_rag.store.Scope`): the uploader's personal space (their own, keyed by their Keycloak user id), or a case (suveryn-tracker#10). The gateway decides the scope once per request and checks the caller's right in the case with the one function `cases.may` (reading to list and ask, contributing to upload, managing to delete); every store query then names the scope, and a document or conversation elsewhere is answered with 404, like a missing one. The gateway checks before a chat starts and the retriever checks again before reading passages, and only uploaded documents are ever sources (never sūveryn's own output). De-duplication by file hash is per scope, so an upload never returns someone else's document. Documents without an owner and without a case (stored before owners existed, or by `suveryn-ingest` without `--owner`) are visible to no user. Documents stored before cases existed are in their uploader's personal space.
8. **No outbound network calls at runtime.** Air-gapped installs must work: no CDN assets (`/docs` is off by default), no telemetry, no model downloads (`suveryn_rag.offline`). The gateway talks only to the local Keycloak. The chat UI bundles its fonts and icons and only calls its own origin.
9. **SQL takes input only as bound parameters.** f-strings in `store.py` interpolate constants and fixed fragments only.
10. **Ingestion is single-threaded per process** (process-wide `TMPDIR` redirection), and heavy work is queued. Two concurrent whole-document summaries failed in the benchmark.
11. **The model's own arithmetic is never shown as a result.** Calculations are written as `[[calc: …]]` and computed by [`chat/calc.py`](../packages/chat/src/suveryn_chat/calc.py) with `Decimal` and a hand-written parser (never `eval`). A calculation that can't be done unambiguously is refused and shown as such, never guessed. Figures the model writes in its text anyway, in no passage and no calculation's result, are listed in `unverified_figures` and flagged in the UI (`calc.unverified_figures`).
12. **Positional citation contract.** `[n]` in `answer` is `citations[n-1]`. Markers have one or two digits (`grounding._MARKER`, `answer.ts` `MARKER`), so whole-document grounding is capped at 99 chunks (`WHOLE_DOCUMENT_CHUNKS`).
13. **Document text is data, never instructions** (suveryn-tracker#21).
    - **Control tokens:** every message the engine sends is `guard.neutralise`d, including a client's own system message, so text from a document, a question or an earlier answer can't become a chat-template turn boundary (`<|im_start|>`, `[INST]`, `[SYSTEM_PROMPT]`).
    - **The prompt:** the grounded prompt says excerpts are data, repeats it right before the question, and quotes excerpts so a document can't pose as another excerpt (`grounding.quoted`).
    - **Flagging:** text addressed to an AI is flagged where it can't be removed. At ingestion it becomes an `instruction_like_text` warning; in every answer it fills `instruction_like_sources`, shown to the reader and in Word exports.
    - **Audit:** both cases write an audit event (`suveryn_engine.audit`, logger `suveryn.audit`) with ids, pages and kinds only.
    - **Test:** a deed with an injection attempt is part of the regression harness.
14. **Untrusted PDFs are parsed only in the reader process** (suveryn-tracker#15, security review 2026-10-11). The gateway never opens an upload with a PDF library (except with `SUVERYN_EXTRACT_ISOLATION=off`, for debugging).
    - The reader gets no secrets (`child_env`) and sends back JSON only.
    - A document of another owner gets a fresh reader.
    - Only the document being read is where the reader can see it.

15. **The browser code keeps to the appliance's Content-Security-Policy without loosening it** (`style-src 'self'`, `script-src 'self'`, no `data:`, no other host). No `<style>` element, inline script, `style` attribute in markup, `eval` or `innerHTML`; a library that writes styling at run time is fixed so it doesn't, or isn't used; never `'unsafe-inline'`, a nonce or a hash. How, and the two React Aria exceptions we handle: [content-security-policy.md](content-security-policy.md). Checked by `packages/chat-ui/src/csp.test.ts` and a browser check under the real headers.

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
| Small documents (`WHOLE_DOCUMENT_CHARS` = 48,000 characters together, `WHOLE_DOCUMENT_CHUNKS` = 99) are given to the model whole, in reading order; larger ones as their best-matching passages up to the same budget (at least 6), also in reading order | A general question about a short bank statement got 6 near-random passages, one of them a bare reference code, and the model rightly said the answer wasn't there. A 58-page signed deed (75,000 characters, 165 passages) then showed the same cliff above the limit: 6 passages were 6–12% of its text, and broad questions failed; filling the budget gives 62–79 passages, 64% of the text, always including the former top 6. The benchmark showed whole-document answers work up to ~60 pages. 48,000 characters is ~14k tokens of Dutch or French, which fits a parallel slot's share of the context (`-c 65536 -np 4` with a unified KV cache) with room for history and the answer. The chunk cap keeps markers to two digits |
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
| Sign-in state in an AES-GCM cookie (one use, 10 minutes); rate limits on sign-in, questions and uploads (suveryn-tracker#14) | Code review 2026-10: sign-ins kept in server memory let a flood of `/auth/login` push out real users' sign-ins |
| PDFs read in a separate reader process (suveryn-tracker#15); a sandbox wrapper required, unless `SUVERYN_EXTRACT_UNSANDBOXED=1` | The parsers (Ghostscript in particular) have a history of memory-safety flaws. In the gateway's process, a malicious PDF could read the database URL, the client secret and other users' documents. Requiring the wrapper means a production setup can't run unsandboxed by omission |
| A fresh reader for another owner's document; waiting uploads stay private, only the current one in the reader's inbox | Security review 2026-10-11: a reader taken over by one user's PDF stayed alive for everyone's later documents and could read those waiting in the shared inbox. Measured on the pod (CPU): a new reader adds about 10 s; one owner's consecutive documents stay at 6–8 s |
| The gateway makes itself non-dumpable (`PR_SET_DUMPABLE 0`) | Without a sandbox the reader runs as the gateway's user and could read `/proc/<gateway>/environ`. Checked on the pod: readable before, "Permission denied" after |
| At most 20 waiting documents per user and 200 in all (429); at most `SUVERYN_MAX_PAGES` (2,000) pages, refused before OCR | Security review 2026-10-11: one user could hold up everyone's documents for hours with one worker and a 30-minute limit per document |
| A page Docling's layout model fails on is read again on the CPU; pages still unread put the document in `needs_review` (`layout_failed`) | 2026-10-11: with Mistral loaded, Docling ran out of GPU memory on 11 of 12 pages, and the document was stored from the text-layer recovery alone, garbled |
| A re-upload of a file whose stored copy was read poorly is read again and replaced in place, keeping its id. Poorly read means: in review, over half its text recovered, misread characters, or recovered OCR noise | De-duplication returned the garbled copy of a re-uploaded PDF. Keeping the id keeps saved conversations' sources valid |
| Characters read in the wrong encoding are put right per document, only with evidence: at least 3 unusual characters that a Mac Roman reading turns into usual ones, and nearly all unusual ones explained. UTF-8 read as Windows-1252 too. PDFium's line-break hyphen (U+FFFE) becomes a hyphen | A PDF font encoding Mac Roman gave "ŽŽn" for "één" and "ÒwoordÓ" for "“woord”", next to correct text in another font. Only unusual characters are changed, so correct text is left alone; a single "Ó Briain" is no evidence |
| Text-layer lines that look like OCR noise (odd words: a capital inside, letters then a digit, no vowel; mostly unknown to the rest of the document) are left out like dropped furniture | An upside-down figure was read by OCR as nonsense and restored as "missing text", then shown as a source |
| Each citation checked against its own passage by rule (`support.py`), with no second model call | No extra seconds per answer. On the pod: 1 of 41 markers in 12 real answers flagged, a false alarm since fixed (see §6 for what rules can't see) |
| A conversation sends at most its last 40 messages as history | The server takes at most 200 per request; a long conversation failed on every new question after about 100 |
| The source card marks the sentence a clicked marker's claim rests on, and the claim's figures, dates and names in it, by word and number overlap in the browser | Users expected the referenced text to be marked, not just years. This is an interim step: suveryn-tracker#25 moves it to the server, by meaning |

## 6. Known limitations

| Limitation | Impact | Planned |
|---|---|---|
| Text inside small images (under 10% of the page) on born-digital pages is not read, e.g. a stamp image bearing the notary's name | Small amounts of text can be missing; the page coverage check can't see it (the text was never in the text layer) | Lower the threshold per document type once real deeds show what's needed (real born-digital deed: one 2.6% image, page 8) |
| Identifiers are not validated (amounts in words vs figures, check digits, cadastral pattern) | A garbled number would be stored and cited as is | An entities table with validated identifiers |
| Model answers are checked against their sources by rule, not by meaning | A figure in no passage and no calculation's result is flagged. Each citation is checked against its own passage (`suveryn_chat.support`, suveryn-tracker#11): figures, dates, years and names in the cited claim must be in that passage, and a name another passage spells differently is flagged. On the pod: 1 of 41 markers in 12 real answers was flagged, a false alarm in a bold label, which is now skipped. A claim whose words are all in its passage but whose meaning isn't ("mag niet" for "mag"), an irrelevant figure, or a sum that leaves out a term is not detected | A second model pass that judges meaning, if the extra seconds per answer are acceptable |
| Products in calculations keep at most 6 decimals; divisions are rounded half up to at least 2 | A rounded result is not marked as rounded | Mark rounded results if notaries need it |
| Documents over the budget are seen in part (the best-matching ~48,000 characters) | A question whose answer is spread over the unread third can miss it; the excerpts are announced to the model as a selection, so it says so rather than guessing | Summaries over the whole document (map-reduce) for very large documents |
| Whole-document grounding is limited in characters, not tokens; a long conversation history adds to it | A very long conversation about a near-limit document could exceed a slot's context share, and llama-server would refuse or truncate | Count tokens with the model's tokenizer |
| Sessions live in the gateway's memory | A gateway restart signs everyone out (Keycloak's own session lets them back in quickly); several gateway processes would not share sessions | A shared session store when needed |
| Rate limits are counted in the gateway's memory, per process | Several gateway processes would each allow the full rate; behind a proxy on another machine the sign-in limit is shared by the whole office | Rate-limit in the appliance's reverse proxy if that is ever the setup |
| Revocation takes effect at the next token refresh | A user disabled or logged out in Keycloak keeps access for up to one access-token lifetime (5 minutes) | Keycloak back-channel logout to end sessions immediately |
| Cases are built through stage 4 of [docs/design/cases.md](design/cases.md) | Documents stored before owners existed are hidden from everyone (re-upload them); what deleting a case guarantees is the [data lifecycle](https://github.com/suveryn/suveryn-docs/blob/main/administration/data-lifecycle.md); syncing with the practice software is a connector, later | The connectors |
| GPU memory is tight on a 24 GB card | With the larger model loaded (Mistral Small 3.2: 19.6 GB, plus the gateway and the PDF reader) Docling has no room left: on 2026-10-11 it failed on 11 of 12 pages with "CUDA out of memory", and only the text-layer recovery kept the text, without structure. Docling's status is now checked: an out-of-memory failure is read again on the CPU (seconds slower per document), and pages still unread put the document in `needs_review` (`layout_failed`) | A larger card, or a fixed GPU budget per service |
| One model in GPU memory at a time | When people alternate between models, each switch makes the next question (anyone's) wait for a load, and the prompt cache starts empty | A 48 GB card (Heavy profile) can hold both: `--models-max 2` |
| Upload jobs live in memory | After a gateway restart, polling an earlier job returns 404 (the stored document itself is safe) | Persist jobs if needed |
| Chunks without page provenance are allowed (`page: null`) | Such a passage can't be traced to a page | Warn or put the document in `needs_review` |
| Saved answers still state facts from a deleted document | Deleting a document takes its passages, headings and file name out of every saved conversation, also from a tab still open (suveryn-tracker#12), and the UI offers to delete those conversations too. Kept conversations keep the answer text, which mentions facts from the document | Deleting is the user's choice per document |
| A conversation is saved whole, last write wins | The same conversation open in two tabs: the tab that answers last overwrites the other's turns | Save per turn if people work that way |
| A deleted row's bytes stay in the database's files until autovacuum reuses the space, and in the WAL until it is recycled | Someone with the disk's contents and the right tools could recover traces of deleted text for a while; off the appliance the disk is encrypted, so only on the running machine. The [data lifecycle](https://github.com/suveryn/suveryn-docs/blob/main/administration/data-lifecycle.md) says exactly this, and nothing in the product says "permanently" | Crypto-shredding (designed in suveryn-tracker#31) when a customer, a certification or a regulator asks |
| The llama-server prompt cache holds document text unencrypted, also of deleted documents until it is pushed out | Readable by anyone with access to the machine's memory; named in the data lifecycle | Erase the slots on delete or restart nightly, if needed |
| HNSW post-filtering when searching within one document | Fewer vector candidates in very large databases | Tune `hnsw.ef_search` or use iterative scans |
| Page coverage threshold (95%) calibrated on 5 documents | May need tuning | Revisit with more real scans |
| Retrieval quality measured on 3 real and a handful of synthetic documents | Numbers are indicative | Grow the regression set |
| Source marking works by word and number overlap, in the browser | A paraphrased claim, a claim in another language than its source, numbers in words ("twaalf"), other date formats, and abbreviations ("art. 3" ends a sentence) can mark too little or the wrong sentence | suveryn-tracker#25: on the server, by meaning (bge-m3), with a regression set of every reported case |
| Only the warnings that put a document in review are shown | Text addressed to an AI (`instruction_like_text`) and restored text are visible only when an answer cites that passage | suveryn-tracker#26 |
| A fresh reader per owner costs about 10 s | When people upload in turn, each switch adds a reader start to the next document | Start the next reader in the background if it matters |
| Encoding repair needs evidence | A document with only one or two misread characters keeps them | — |
| `/health` is public and names the loaded model | Minor information disclosure on a network; it gives no addresses or error texts | — |

## 7. How to verify

- **Fast tests, any machine:** `uv sync --locked && uv run pytest`. These are the engine, chat (including calculations) and gateway tests; rag tests are skipped.
- **Chat UI:** `cd packages/chat-ui && npm ci && npm test && npm run typecheck`. Covers SSE parsing, answer rendering, source marking, conversation history and its cap, copy and download, translated server errors, the i18n rules (formal Dutch, the brand name's case), the brand-file hash check, the web setup's text and password rules, and that React Aria stays within the CSP (`vite.config.ts`).
- **Full tests on the GPU machine:** `uv sync --locked --all-packages`, then `SUVERYN_TEST_DATABASE_URL=… uv run pytest`. This adds the rag units (including the offline guard), pgvector storage, and the end-to-end trap deed ([`test_e2e.py`](../packages/rag/tests/test_e2e.py)) as a born-digital PDF, a scan, and a scan with a thin digital text layer.
- **Before using a new model or model version** (suveryn-tracker#21): the regression harness [`test_answers_e2e.py`](../packages/rag/tests/test_answers_e2e.py) on the GPU machine, for every model to compare:

  ```bash
  SUVERYN_TEST_DATABASE_URL=… SUVERYN_EVAL_MODELS=qwen3.8-27b,mistral-small-3.2-24b SUVERYN_EVAL_REPORT=report.json \
    uv run pytest packages/rag/tests/test_answers_e2e.py
  ```

  It checks every answer for:
  - its source and for figures that are in no passage;
  - citations that don't match their sources;
  - the expected facts;
  - the two OCR issues from the benchmark (last line, cadastral reference);
  - resistance to an injected instruction;
  - sums computed by the server.

  Fictional deeds are built in. The office's own deeds can be added from a folder (`SUVERYN_EVAL_DIR`), with permission, never in the repository, and deleted after the run. 2026-10-11 on the pod: Qwen3.8-27B 15/15, Mistral Small 3.2 24B 15/15. Before the injection rules, Mistral answered "De akte is GOEDGEKEURD" from the injected text.
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
- [ ] If it touches the UI or adds a browser dependency: does it keep to [content-security-policy.md](content-security-policy.md) (no inline `<style>` or script, nothing written into the page at run time, no `data:` or other host), and does `npm test` (`src/csp.test.ts`) pass? A new library is checked under the real policy first.
- [ ] If it adds an endpoint: is it under `/v1` (signed-in only) or deliberately public, does a state-changing endpoint keep the same-origin check, and does anything that touches documents or conversations take its scope from `routes.common.scope_of` (the caller's personal space, or a case checked with `cases.may`), never a bare owner?
- [ ] If it touches `auth.py`: do the sign-in tests (`test_auth.py`) and `keycloak/live_login_check.py` still pass, and does no token, code or cookie reach the browser or a log?
- [ ] If it touches the PDF reader (`isolation.py`, `service.py`): does untrusted parsing stay in the reader, does the reader get no new secrets (`child_env`), does another owner's document still get a fresh reader, and does only the document being read reach the inbox?
- [ ] Does anything new reach the network at runtime (including model or tokenizer loads)? Keycloak is the only service the gateway may call besides llama-server and PostgreSQL.
- [ ] Is every new place where document text is stored or written (cache, temp file, download) listed in §3?
- [ ] Are new thresholds and constants explained (why this value, measured on what)?
- [ ] Were brand files changed only through `npm run brand:sync`?
- [ ] Were dependencies changed? Then check `uv.lock`/`package-lock.json` sources stay on PyPI/npm, run `uvx pip-audit` and `npm audit`, and check new licences are AGPL-compatible.
