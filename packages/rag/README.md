# rag

Document ingestion and retrieval: extraction, chunking, embeddings, the vector store and retrieval.

## Pipeline

1. **Extraction (`extract.py`)** uses the `ocr_fast` approach from the October 2026 benchmark:
   - Pages that already have a text layer are not OCR'd.
   - Scanned pages are OCR'd in parallel by OCRmyPDF (Tesseract, `nld+fra+eng`).
   - Docling then reads the text layer with `do_ocr=False`, running only its layout and table models on the GPU.
2. **Chunking (`chunking.py`)** uses Docling's HybridChunker (384 tokens). Each chunk keeps the pages it comes from (`page_start`, `page_end`) and its section headings.
3. **Embeddings (`embed.py`)** use `BAAI/bge-m3` (1024 dimensions, multilingual), in fp16 on the GPU.
4. **Storage (`store.py`)** uses PostgreSQL with pgvector: the tables `documents` and `chunks`, with an HNSW cosine index. Deleting a document deletes its chunks.
5. **Retrieval (`pipeline.py`)** returns the closest chunks as the engine's `Citation` objects, with `source = {document_id, page, location}`. `location` reads like `p. 3-4 · Artikel 2 - Koopprijs`.

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

The pgvector test is skipped without a database. All rag tests are skipped where this package is not installed (plain `uv sync` installs only the gateway).
