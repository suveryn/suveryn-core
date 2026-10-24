# rag

Document ingestion and retrieval: extraction, chunking, embeddings, the vector store and retrieval.

## Pipeline

A **.zip** upload (`DocumentService.accept_archive`) becomes a document per PDF, Word, Excel, Markdown or
CSV file inside it, read as below; the rest is listed with a reason. Every entry is checked on upload (read
through, nothing written, the entries (1,000) and the bytes actually unpacked (300 MB) bounded, so a zip
bomb stops at the limit). The archive is then kept, and each entry is unpacked only when its turn comes:
only its bytes, never to a path the archive names. An archive counts as one upload in the queue limits,
however many documents it holds.

**The queue takes uploaders in turns** (`FairQueue`): one document from each uploader in turn, each
uploader's own in the order they came. A colleague's one deed is read next, even behind a data room.

PDFs go through the steps below. **Word (.docx), Excel (.xlsx), Markdown (.md) and CSV** files are read
directly ([`formats.py`](src/suveryn_rag/formats.py)), in the same sandboxed reader: their text and structure
are in the file, so there is no OCR, layout model or page check. Each passage keeps its place: the section
(the headings above it) in Word and Markdown, the cells in Excel notation (`Prices!A2:D31`) in a
spreadsheet. Excel values are read as last calculated, never as formulas; a sheet's first row is repeated in
every passage of that sheet; a long Word table is split by rows. Word headers and footers and Markdown
comments are not stored, only checked for sūveryn's export mark ([`marks.py`](src/suveryn_rag/marks.py)).
Limits: 300 MB unpacked for an Office file, 250,000 filled cells, 5 million characters.

1. **Extraction (`extract.py`)** uses the `ocr_fast` approach from the [October 2026 benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md#document-extraction):
   - Pages with a usable text layer (at least 50 characters) and no large images are not OCR'd; their exact text is kept.
   - [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) (Tesseract, `nld+fra+eng`) runs in parallel, in `redo_ocr` mode, on:
     - scans, including scans with a thin digital layer such as a copier label or e-stamp, which OCRmyPDF's `skip_text` would wrongly skip;
     - born-digital pages whose images cover at least 10% of the page, such as a pasted-in scan.

     `redo_ocr` keeps visible digital text exactly and reads only what is drawn as an image. Small images (logos, signatures, stamps; 1–5% of a page) don't trigger OCR, so text inside them is not read.
   - **Digitally signed PDFs and PDFs with form fields** (common for deeds) are OCR'd from a private copy with the form flattened: each field's visible content stays on the page, the form and the signature are dropped from that copy. OCRmyPDF refuses such files otherwise. The uploaded original is never changed, and sūveryn does not check signatures.
   - [Docling](https://github.com/docling-project/docling) then reads the text layer with `do_ocr=False`, running only its layout and table models on the GPU.
2. **Chunking (`chunking.py`)** uses Docling's HybridChunker (384 tokens). Each chunk keeps the pages it comes from (`page_start`, `page_end`) and its section headings.
3. **Embeddings (`embed.py`)** use [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) (1024 dimensions, multilingual), in fp16 on the GPU.
4. **Storage (`store.py`)** uses PostgreSQL with [pgvector](https://github.com/pgvector/pgvector): the tables `documents` and `chunks`, with a full-text index. There is no vector index: answers compare the question with every chunk of the chosen documents exactly, and keeping an HNSW index up to date made storing a document a hundred times slower. Deleting a document deletes its chunks.
5. **Retrieval (`store.py`, `pipeline.py`)** is hybrid. Vector similarity is merged with PostgreSQL keyword search through Reciprocal Rank Fusion. Query words found in more than 20% of the chunks are left out of the keyword part, so specific terms ("huurachterstand", "vierde rang", "1563") outweigh boilerplate. Results come back as the harness's `Citation` objects, with `source = {document_id, page, location}`. `location` reads like `p. 3-4 · Artikel 2 - Koopprijs`. Chunks of fewer than three words (a reference code, a stray header) are left out of the vector ranking; keyword search still finds them. For answering, `Rag.passages` gives small documents whole, in reading order (up to `WHOLE_DOCUMENT_CHARS`), and for larger ones the best-matching passages that fit the same budget, also in reading order (`Store.best_chunks`, an exact ranking of every chunk of those documents, in one scan: a case of 6,500 passages is ranked in under half a second).

## No silent text loss (`integrity.py`)

Real deeds showed that text can disappear between the PDF and the stored chunks. These safeguards prevent that, or make it visible:

| Safeguard | What it catches | Result |
|---|---|---|
| Completeness | Body text the chunker left out, e.g. a closing heading with nothing after it ("Voor eensluidend afschrift") | Kept as a separate chunk (`origin = text_recovered`) |
| Footer rule | Content the layout model labelled as header/footer | Only page numbers and text that repeats on at least half the pages are dropped; the rest is kept (`origin = furniture_restored`) |
| Text-layer recovery | Text the layout or table model dropped, e.g. table cells it couldn't place (seen on a real bank statement) | The page's text-layer lines holding 3+ missing words are kept as a chunk (`origin = text_layer_recovered`); taken verbatim from the PDF, nothing reworded. Lines that look like OCR noise (an upside-down figure read as letters: odd words, mostly unknown to the rest of the document, `ocr_noise`) are not text that went missing and are left out |
| Layout failure | Pages Docling's layout model couldn't read, e.g. out of GPU memory | Read again on the CPU; pages still unread get a `layout_failed` warning, and status `needs_review` |
| Page coverage | Any loss that remains after recovery: each page's PDF text layer is compared with the stored text for that page | Below 95% of the page's words: a `page_coverage_low` warning, and status `needs_review` |

Every document gets a `status` (`ok` or `needs_review`) and a list of `warnings` (page, kind, detail). `suveryn-ingest` prints both.

**Text repair** (`integrity.misdecoding`, `repair_characters`): characters a PDF font encodes in another character set are put right for the whole document, only when it clearly shows them.
- Mac Roman read as Windows-1252 gives "ŽŽn" for "één" and "ÒwoordÓ" for "“woord”".
- UTF-8 read as Windows-1252 gives "Ã©" for "é".

Only characters unusual in Dutch, French, English or German are changed, and only with at least 3 such repairs explaining nearly all of them, so correct text next to them is left alone. PDFium's line-break hyphen (U+FFFE) always becomes a hyphen.

**Uploading the same file again** returns the stored copy (de-duplicated by SHA-256 per scope: a personal space or a case), unless that copy was read poorly: in review, over half its text recovered from the text layer, misread characters, or recovered OCR noise. Then it is read again and replaced in place, keeping its id, so saved conversations still point to it (`should_read_again`).

Every document is in one **scope** (`store.Scope`): its uploader's personal space (`owner`, the Keycloak user id, and no case), or a **case** (`case_id`; suveryn-tracker#10). The document service lists, retrieves and deletes within the scope the gateway passes (the gateway has checked the caller may see it), and de-duplicates by file hash per scope. Each document records its `origin` (`uploaded`, `generated`, `playbook`); only uploaded documents are ever retrieved as sources for an answer. `suveryn-retrieve` and `suveryn-forget` are operator tools on the server and are not limited by scope.

PostgreSQL and pgvector are provisioned outside this repository (by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance)). This package only connects to them, and creates its own tables.

## Confidential data

- Intermediate files (searchable PDFs, OCR work files) are written only to a private `0700` directory under `SUVERYN_WORK_DIR`. They are deleted as soon as a document is processed, also on errors. While a document is processed, both `tempfile` and `TMPDIR` point there, so OCRmyPDF and its subprocesses do not use `/tmp`.
- Uploads and work folders left behind by a crash are deleted when the document service starts.
- **Uploaded files are read in a separate process** ([`isolation.py`](src/suveryn_rag/isolation.py)), Word and Excel files too. The PDF parsers (pypdfium2, qpdf, Ghostscript, Tesseract, Docling) run there, without the database URL, the sign-in settings or anything named like a secret in its environment, and with no core dumps. Only JSON comes back (validated, never pickle). A crash or a document that takes longer than `SUVERYN_EXTRACT_TIMEOUT_S` fails that document only: the reader and everything it started are killed, and a fresh one reads the next. A document of another user also gets a fresh reader, so a reader taken over by one user's PDF never sees another's. Waiting uploads stay in the gateway's private folder; only the document being read is in the reader's inbox. A separate user, no network and seccomp are for the appliance to add through `SUVERYN_EXTRACT_WRAPPER`; without it the gateway refuses to read documents unless `SUVERYN_EXTRACT_UNSANDBOXED=1` (development). At most 20 documents per user (200 in all) wait at once, and a PDF over `SUVERYN_MAX_PAGES` pages is refused. While it reads, the reader reports how far it has got (`reading.Progress`: text recognition page by page, through an OCRmyPDF progress plugin, `ocr_progress.py`; then the layout, which Docling reports as a whole; then storing), and a cancelled upload stops it at once: the reader is killed and a fresh one reads the next. A document it can't read fails with a code (`reading.Unreadable`: a password, damaged, too many pages, too large, no text, a time-out) that the interface says in its own language. The reader has its own copy of Docling's models, and on a GPU its own CUDA context (about 0.9 GB of GPU memory, measured on an RTX 4090).
- Extracted text and file names are stored in PostgreSQL. Encryption at rest and retention are open items (see [known limitations](../../docs/architecture.md#6-known-limitations)).

## Models stay offline

Importing `suveryn_rag` switches the Hugging Face libraries (and so sentence-transformers and Docling) to offline mode and turns their telemetry off (`offline.py`). Models load only from the local cache in `HF_HOME`; nothing is downloaded and huggingface.co is never contacted at runtime. Put the models in the cache once, when the machine is set up and has internet access:

```bash
HF_HOME=/path/to/model-cache uv run suveryn-fetch-models
```

It loads bge-m3, its tokenizer and Docling's layout and table models exactly as the pipeline does. A missing model then fails at startup instead of being downloaded silently. The models, their sources and licences are listed in [models/manifest.json](../../models/manifest.json).

## Use (on the GPU machine)

```bash
uv sync --locked --all-packages
export SUVERYN_DATABASE_URL=postgresql://user:password@127.0.0.1:5432/suveryn
uv run suveryn-ingest deed.pdf --owner <keycloak-user-id>   # without --owner: visible to no chat user
uv run suveryn-retrieve "In welke rang wordt de hypotheek gevestigd?" -k 5 [--document <id>]
uv run suveryn-forget <document-id>
```

## Settings

Settings come from environment variables:

| Variable | Default |
|---|---|
| `SUVERYN_DATABASE_URL` | none (required) |
| `SUVERYN_EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `SUVERYN_RAG_DEVICE` | `cuda` |
| `SUVERYN_OCR_LANGUAGES` | `nld+fra+eng` |
| `SUVERYN_OCR_JOBS` | all available cores |
| `SUVERYN_CHUNK_MAX_TOKENS` | `384` |
| `SUVERYN_WORK_DIR` | `~/.local/state/suveryn/work` |
| `SUVERYN_EXTRACT_TIMEOUT_S` | `1800`: the longest one document may take to read |
| `SUVERYN_EXTRACT_WRAPPER` | unset; a command prefix for the PDF reader process, e.g. a sandbox (suveryn-appliance's `reader-sandbox`). Required, unless `SUVERYN_EXTRACT_UNSANDBOXED=1` |
| `SUVERYN_EXTRACT_UNSANDBOXED` | unset; `1` lets the reader run without a wrapper, as the gateway's user with network access (development only) |
| `SUVERYN_MAX_PAGES` | `2000`: a PDF with more pages is refused before OCR |
| `SUVERYN_EXTRACT_INBOX` | unset: uploads wait in `SUVERYN_WORK_DIR/uploads` (0700). Set when the reader runs as its own user: a provisioned folder, owner the gateway, group the reader, mode 2750; uploads in it are 0640 |
| `SUVERYN_EXTRACT_WORK_DIR` | unset: `SUVERYN_WORK_DIR`. The reader's own folder for OCR intermediate files and temporary files (0700), when it runs as its own user |
| `SUVERYN_EXTRACT_ISOLATION` | on; `off` reads PDFs inside the gateway process (debugging only) |
| `HF_HOME` | `~/.cache/huggingface` (the local model cache) |
| `SUVERYN_ALLOW_DOWNLOADS` | unset; `1` only for `suveryn-fetch-models` |

## Tests

```bash
SUVERYN_TEST_DATABASE_URL=$SUVERYN_DATABASE_URL uv run pytest packages/rag
```

- `test_integrity.py` and `test_units.py` are fast unit tests (`test_units.py` also checks the offline guard).
- `test_isolation.py` checks the separate reader with a fake one (`fake_reader.py`): no secrets in its environment, JSON only, a crash, a hang and garbage fail only that document, progress arrives before the answer, a cancel stops the reader at once, and a reason comes with its code.
- `test_formats.py` checks the Word, Excel, Markdown and CSV readers: sections, cell ranges, tables, content controls and tracked changes, nothing left out, the limits, and the mark in the chat's own Word and Excel exports (`fixtures/marked-answer.docx`, `fixtures/marked-table.xlsx`).
- `test_store.py` checks storage and search against a real pgvector database.
- `test_answers_e2e.py` is the harness for model updates (suveryn-tracker#21): answers through the whole pipeline, per model, against the citation requirement, the expected facts, the two OCR issues, an injected instruction and server-side sums. See its docstring and `docs/architecture.md` §7. Pages the layout model couldn't read (after a CPU retry when the GPU ran out of memory, `extract.convert_with_fallback`) get a `layout_failed` warning and put the document in `needs_review`. Ingestion adds an `instruction_like_text` warning on pages with text addressed to an AI; it doesn't change the document's status.
- `test_e2e.py` is the regression bar. It generates a fictional deed with the traps seen so far (`trap_deed.py`): a running header and page numbers, a content line in the footer area, a closing heading, a cadastral reference, and a tenant in arrears buried in boilerplate. It also includes a soil report that exists only as a pasted-in image. It runs that deed through the full pipeline as a born-digital PDF, as a scan, and as a scan with a thin digital label on each page. It requires:
  - no lost text, and dropped furniture
  - an intact cadastral reference
  - the right passage with the right page in the top 5 for every question, and the buried arrears in the top 3
  - the pasted-in scan's text read, with only that page OCR'd in the born-digital variant
  - an empty work directory and status `ok`

The database and end-to-end tests are skipped without `SUVERYN_TEST_DATABASE_URL`. All rag tests are skipped where this package is not installed (plain `uv sync` installs only the gateway).
