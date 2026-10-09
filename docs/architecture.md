# suveryn-core architecture

This document is for people reviewing or extending `suveryn-core`. It covers:

- what is built so far
- where confidential data goes
- which rules the code must keep
- which decisions were made, and on what evidence
- what is known to be incomplete

The full product context (editions, network modes, licensing) is in the Sūveryn development context document. The hardware and model evidence is in the [October 2026 benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md).

## 1. What exists today

| Package | State | Responsibility |
|---|---|---|
| `packages/engine` | Built (slice 1) | Model server client, answer and citation schema |
| `packages/api-gateway` | Built (slices 1, 3) | HTTP API: `POST /v1/chat`, `/v1/documents` (upload, list, delete, job status), `GET /health` |
| `packages/rag` | Built (slice 2) | Ingestion (extraction, chunking, embeddings, storage) and retrieval |
| `packages/chat` | Built (slice 3) | Grounded answers: retrieval → numbered excerpts → answer citing `[n]` |
| `packages/chat-ui` | Built (slice 3) | React/TypeScript chat interface (light theme), static build served next to the API |
| `packages/mcp-host`, `connectors`, `playbooks` | Placeholders | Later phases |

Runtime services are **not** part of this repository. PostgreSQL with pgvector, Keycloak and the model server (llama.cpp `llama-server`) are installed and configured by `suveryn-appliance`. This repository only contains clients for them.

Chat requests with `document_ids` are grounded in those documents and cite their passages. Answers are not yet *checked* against their sources (design point 5); the UI therefore marks unsourced answers and lets the user open every cited passage.

## 2. Data flow

```
                       ┌──────────────────────── packages/rag ────────────────────────┐
PDF ──► extract.py ──► chunking.py + integrity.py ──► embed.py ──► store.py (PostgreSQL + pgvector)
        │ ocr_fast: OCR    │ HybridChunker, page numbers,     │ bge-m3      │ documents, chunks,
        │ pages <50 chars  │ headings; completeness, footer   │ 1024-dim    │ HNSW + full-text index
        │ or ≥10% images,  │
        │ OCRmyPDF in      │ rule, page coverage → status     │             │
        │ parallel, Docling│ and warnings                     │             ▼
        │ layout on GPU    │                                  │      pipeline.retrieve(question)
        ▼                                                     │      hybrid search → Citation
   private work dir (0700), deleted after each document           {text, source: {document_id,
                                                                     page, location}}

browser (chat-ui) ──► api-gateway ──► POST /v1/documents ──► DocumentService queue ──► one worker: rag.ingest
                                    └─► POST /v1/chat {messages, document_ids}
                                          └─► chat.ChatService ──► rag retrieve (6 passages) ──► numbered excerpts
                                                              ──► engine.LlamaServerClient ──► llama-server (Qwen3.8-27B)
                                          ◄── SSE: delta… then done {answer with [n], citations[n-1]} | error
```

## 3. Where confidential data lives

Deeds contain personal data (names, national register numbers, addresses, amounts). Every place it can exist:

| Place | What | Lifetime | Protection today | Open item |
|---|---|---|---|---|
| Original PDF | Whole document | Owned by the caller; `rag` only reads it | none needed by rag | — |
| Private work directory (`SUVERYN_WORK_DIR`) | Searchable PDF and OCR work files | During one document's extraction only | `0700`; deleted on success and on error; `TMPDIR`/`tempfile` redirected so nothing goes to `/tmp` | — |
| Gateway temp folder (`SUVERYN_WORK_DIR/tmp`) | Uploads while they are received (Starlette spools files over 1 MB to a temporary file) | During the request; folder emptied on start, removed on exit | `0700`; `TMPDIR`/`tempfile` point here instead of `/tmp` (`api-gateway/main.py`) | — |
| Upload folder (`SUVERYN_WORK_DIR/uploads`) | Uploaded PDFs waiting for ingestion | Until their job ends (deleted on success and failure; folder removed on shutdown) | `0700` folder, `0600` files, random names | — |
| Process memory | Docling document, page texts; upload jobs (file names, status) | During ingestion; jobs until the gateway restarts | — | — |
| Browser memory (chat UI) | The conversation, cited passages | Until the tab is closed or *New chat* | Not written to browser storage | Server-side conversation history, if ever added, needs a retention design |
| PostgreSQL `documents` | File name (may contain a client's name), hash, status, warnings | Until deleted | Database access control | Encryption at rest, retention (§11.5) |
| PostgreSQL `chunks` | Document text, embeddings | Until deleted | Database access control | `DELETE` leaves data in table files until VACUUM and in the WAL for a while; secure deletion (crypto-shredding) is open |
| llama-server prompt cache (GPU memory + RAM, `-cram`) | Prompts incl. document text | Until evicted or restart | none | Retention and encryption (§11.5) |
| Logs | Gateway: method, path, status only; rag: none | — | No document text is logged | Keep it that way |
| Terminal output of `suveryn-retrieve` | Passages | Developer's terminal | — | Don't pipe into shared logs |

Integrity warnings contain counts and lengths, never document text. They can be shown to administrators safely.

## 4. Invariants (what must stay true)

Reviewers: check changes against these.

1. **No intermediate document file outside the private work directory.** Anything that writes temp files during extraction must run inside `private_workdir()`.
2. **No silent text loss.** Every body text item ends up in a chunk. Header/footer text is only dropped when it is a page number or really repeats. A page whose stored text falls short of its text layer puts the document in `needs_review` (`integrity.py`).
3. **Every stored chunk has a page number.** `source.page` is what lets a person verify an answer.
4. **Unsourced means unverified.** `citations: []` or `source: null` must be shown to users as unverified, never as fact.
5. **No document text in logs or in error messages we generate.** Backend error texts are passed on (truncated to 200 characters); they come from llama-server, not from documents.
6. **No outbound network calls at runtime.** Air-gapped installs must work: no CDN assets (`/docs` is off by default), no telemetry. Model weights and the embedding model come from local disk. The chat UI bundles its fonts and icons and only calls its own origin.
7. **SQL takes input only as bound parameters.** f-strings in `store.py` interpolate constants and fixed fragments only.
8. **Ingestion is single-threaded per process** (process-wide `TMPDIR` redirection), and heavy work is queued. Two concurrent whole-document summaries failed in the benchmark.

## 5. Decisions and their evidence

| Decision | Evidence |
|---|---|
| Python backend, FastAPI, uv workspace | Development context §3; the validated document pipeline is Python-native |
| Qwen3.8-27B default, Mistral Small 3.2 24B as the faster alternative; nothing model-specific in code | Benchmark: Qwen made fewer legal errors on real deeds; Mistral is 20–40% faster |
| `ocr_fast`: skip text pages, OCRmyPDF in parallel, Docling on the text layer | Benchmark: 3.7–8× faster than Docling calling Tesseract per page |
| OCR every page with less than 50 characters of text, not OCRmyPDF's `skip_text` | `skip_text` skips a scanned page that carries a thin digital label (copier, e-stamp); its content was lost. Covered by the `scanned-thin-text` regression variant |
| Also OCR born-digital pages whose raster images cover at least 10% of the page, with `redo_ocr` (keeps digital text, reads only the images) | A pasted-in scan's text was never read. Covered by the trap deed's pasted-in soil report; logos/signatures/stamps cover 1–5% (real deed: 2.6%), so they don't trigger OCR |
| bge-m3 embeddings | Multilingual (Dutch, French, English), as Belgian deeds are |
| 384-token chunks with page provenance | Citations must point at a specific passage and page |
| Hybrid retrieval (vector + full-text, RRF), very common query words ignored | Real deeds: right passage at #1 went from 12/19 to 15/19, top 3 from 17/19 to 19/19; a buried tenant arrears went from #9 to #1 |
| Completeness check, footer rule, text-layer recovery, page coverage | Real deeds: a closing certification line and 14 short headings and fragments were silently lost before; on a real bank statement the table model dropped 4 words of a table, now recovered from the text layer |
| `/docs` off by default | FastAPI loads it from public CDNs (development context §1, §8) |
| Gateway binds to 127.0.0.1 | No auth until the Keycloak slice |

## 6. Known limitations

| Limitation | Impact | Planned |
|---|---|---|
| Text inside small images (under 10% of the page) on born-digital pages is not read, e.g. a stamp image bearing the notary's name | Small amounts of text can be missing; the page coverage check can't see it (the text was never in the text layer) | Lower the threshold per document type once real deeds show what's needed (real born-digital deed: one 2.6% image, page 8) |
| Identifiers are not validated (amounts in words vs figures, check digits, cadastral pattern) | A garbled number would be stored and cited as is | Design point 3 (entities table) |
| Model answers are not checked against sources | The model can misspell names or miscalculate (seen in the benchmark). The UI marks answers without citations as unverified and lets users open every cited passage, but a cited answer can still contain an uncited figure | Answer check: every name, number and date must appear in a cited passage |
| Deleted documents remain recoverable until VACUUM | Weak deletion guarantee | Crypto-shredding with encryption at rest (§11.5) |
| HNSW post-filtering when searching within one document | Fewer vector candidates in very large databases | Tune `hnsw.ef_search` or use iterative scans |
| Page coverage threshold (95%) calibrated on 5 documents | May need tuning | Revisit with more real scans |
| Retrieval quality measured on 3 real and a handful of synthetic documents | Numbers are indicative | Grow the regression set |

## 7. How to verify

- **Fast tests, any machine:** `uv sync && uv run pytest`. These are the gateway and engine tests; rag tests are skipped.
- **Full tests on the GPU machine:** `uv sync --all-packages`, then `SUVERYN_TEST_DATABASE_URL=… uv run pytest`. This runs the rag units, pgvector storage and the end-to-end trap deed (`packages/rag/tests/test_e2e.py`) as a born-digital PDF, a scan, and a scan with a thin digital text layer.
- **By hand:**
  - `uv run suveryn-gateway`, then `curl` against `/health` and `/v1/chat` (see the root README)
  - `uv run suveryn-ingest`, `suveryn-retrieve`, `suveryn-forget` (see `packages/rag/README.md`)

## 8. Review checklist

- [ ] Does the change keep the invariants in §4? Especially no temp files outside `private_workdir`, no document text in logs, and bound SQL parameters.
- [ ] If it touches extraction or chunking: does `test_e2e.py` still pass in all three variants (born-digital with a pasted-in scan, scanned, scanned with a thin text layer)?
- [ ] If it changes retrieval: are hit@1/3/5 and page accuracy on the regression set at least as good as before?
- [ ] Does anything new reach the network at runtime?
- [ ] Is every new place where document text is stored listed in §3?
- [ ] Are new thresholds and constants explained (why this value, measured on what)?
