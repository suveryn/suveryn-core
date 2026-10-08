# rag

Document ingestion and retrieval: extraction, chunking, embeddings, the vector store and retrieval.

## Pipeline

1. **Extraction (`extract.py`)** uses the `ocr_fast` approach from the October 2026 benchmark:
   - Pages with a usable text layer (at least 50 characters) are not OCR'd; their exact text is kept.
   - Every other page is OCR'd in parallel by OCRmyPDF (Tesseract, `nld+fra+eng`). This includes scans with a thin digital layer such as a copier label or e-stamp, which OCRmyPDF's `skip_text` would wrongly skip.
   - Docling then reads the text layer with `do_ocr=False`, running only its layout and table models on the GPU.
2. **Chunking (`chunking.py`)** uses Docling's HybridChunker (384 tokens). Each chunk keeps the pages it comes from (`page_start`, `page_end`) and its section headings.
3. **Embeddings (`embed.py`)** use `BAAI/bge-m3` (1024 dimensions, multilingual), in fp16 on the GPU.
4. **Storage (`store.py`)** uses PostgreSQL with pgvector: the tables `documents` and `chunks`, with an HNSW cosine index and a full-text index. Deleting a document deletes its chunks.
5. **Retrieval (`store.py`, `pipeline.py`)** is hybrid. Vector similarity is merged with PostgreSQL keyword search through Reciprocal Rank Fusion. Query words found in more than 20% of the chunks are left out of the keyword part, so specific terms ("huurachterstand", "vierde rang", "1563") outweigh boilerplate. Results come back as the engine's `Citation` objects, with `source = {document_id, page, location}`. `location` reads like `p. 3-4 · Artikel 2 - Koopprijs`.

## No silent text loss (`integrity.py`)

Real deeds showed that text can disappear between the PDF and the stored chunks. Three safeguards prevent that, or make it visible:

| Safeguard | What it catches | Result |
|---|---|---|
| Completeness | Body text the chunker left out, e.g. a closing heading with nothing after it ("Voor eensluidend afschrift") | Kept as a separate chunk (`origin = text_recovered`) |
| Footer rule | Content the layout model labelled as header/footer | Only page numbers and text that repeats on at least half the pages are dropped; the rest is kept (`origin = furniture_restored`) |
| Page coverage | Any other loss: each page's PDF text layer is compared with the stored text for that page | Below 95% of the page's words: a `page_coverage_low` warning, and status `needs_review` |

Every document gets a `status` (`ok` or `needs_review`) and a list of `warnings` (page, kind, detail). `suveryn-ingest` prints both.

PostgreSQL and pgvector are provisioned outside this repository (by `suveryn-appliance`). This package only connects to them, and creates its own tables.

## Confidential data

- Intermediate files (searchable PDFs, OCR work files) are written only to a private `0700` directory under `SUVERYN_WORK_DIR`. They are deleted as soon as a document is processed, also on errors. While a document is processed, both `tempfile` and `TMPDIR` point there, so OCRmyPDF and its subprocesses do not use `/tmp`.
- Extracted text and file names are stored in PostgreSQL. Encryption at rest and retention are open design items (development context §11.5).

## Use (on the GPU machine)

```bash
uv sync --all-packages
export SUVERYN_DATABASE_URL=postgresql://user:password@127.0.0.1:5432/suveryn
uv run suveryn-ingest deed.pdf
uv run suveryn-retrieve "In welke rang wordt de hypotheek gevestigd?" -k 5 [--document <id>]
uv run suveryn-forget <document-id>
```

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

## Tests

```bash
SUVERYN_TEST_DATABASE_URL=$SUVERYN_DATABASE_URL uv run pytest packages/rag
```

- `test_integrity.py` and `test_units.py` are fast unit tests.
- `test_store.py` checks storage and search against a real pgvector database.
- `test_e2e.py` is the regression bar. It generates a fictional deed with the traps seen so far (`trap_deed.py`): a running header and page numbers, a content line in the footer area, a closing heading, a cadastral reference, and a tenant in arrears buried in boilerplate. It runs that deed through the full pipeline as a born-digital PDF, as a scan, and as a scan with a thin digital label on each page. It requires:
  - no lost text, and dropped furniture
  - an intact cadastral reference
  - the right passage with the right page in the top 5 for every question, and the buried arrears in the top 3
  - an empty work directory and status `ok`

The database and end-to-end tests are skipped without `SUVERYN_TEST_DATABASE_URL`. All rag tests are skipped where this package is not installed (plain `uv sync` installs only the gateway).
