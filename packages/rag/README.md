# rag

Document ingestion and retrieval: extraction, chunking, embeddings, the vector store and retrieval.

## Pipeline

1. **Extraction (`extract.py`)** uses the `ocr_fast` approach from the [October 2026 benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md#document-extraction):
   - Pages with a usable text layer (at least 50 characters) and no large images are not OCR'd; their exact text is kept.
   - [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) (Tesseract, `nld+fra+eng`) runs in parallel, in `redo_ocr` mode, on:
     - scans, including scans with a thin digital layer such as a copier label or e-stamp, which OCRmyPDF's `skip_text` would wrongly skip;
     - born-digital pages whose images cover at least 10% of the page, such as a pasted-in scan.

     `redo_ocr` keeps visible digital text exactly and reads only what is drawn as an image. Small images (logos, signatures, stamps; 1–5% of a page) don't trigger OCR, so text inside them is not read.
   - [Docling](https://github.com/docling-project/docling) then reads the text layer with `do_ocr=False`, running only its layout and table models on the GPU.
2. **Chunking (`chunking.py`)** uses Docling's HybridChunker (384 tokens). Each chunk keeps the pages it comes from (`page_start`, `page_end`) and its section headings.
3. **Embeddings (`embed.py`)** use [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) (1024 dimensions, multilingual), in fp16 on the GPU.
4. **Storage (`store.py`)** uses PostgreSQL with [pgvector](https://github.com/pgvector/pgvector): the tables `documents` and `chunks`, with an HNSW cosine index and a full-text index. Deleting a document deletes its chunks.
5. **Retrieval (`store.py`, `pipeline.py`)** is hybrid. Vector similarity is merged with PostgreSQL keyword search through Reciprocal Rank Fusion. Query words found in more than 20% of the chunks are left out of the keyword part, so specific terms ("huurachterstand", "vierde rang", "1563") outweigh boilerplate. Results come back as the engine's `Citation` objects, with `source = {document_id, page, location}`. `location` reads like `p. 3-4 · Artikel 2 - Koopprijs`. Chunks of fewer than three words (a reference code, a stray header) are left out of the vector ranking; keyword search still finds them. For answering, `Rag.passages` gives small documents whole, in reading order (up to `WHOLE_DOCUMENT_CHARS`), and falls back to search for larger ones.

## No silent text loss (`integrity.py`)

Real deeds showed that text can disappear between the PDF and the stored chunks. Four safeguards prevent that, or make it visible:

| Safeguard | What it catches | Result |
|---|---|---|
| Completeness | Body text the chunker left out, e.g. a closing heading with nothing after it ("Voor eensluidend afschrift") | Kept as a separate chunk (`origin = text_recovered`) |
| Footer rule | Content the layout model labelled as header/footer | Only page numbers and text that repeats on at least half the pages are dropped; the rest is kept (`origin = furniture_restored`) |
| Text-layer recovery | Text the layout or table model dropped, e.g. table cells it couldn't place (seen on a real bank statement) | The page's text-layer lines holding 3+ missing words are kept as a chunk (`origin = text_layer_recovered`); taken verbatim from the PDF, nothing reworded |
| Page coverage | Any loss that remains after recovery: each page's PDF text layer is compared with the stored text for that page | Below 95% of the page's words: a `page_coverage_low` warning, and status `needs_review` |

Every document gets a `status` (`ok` or `needs_review`) and a list of `warnings` (page, kind, detail). `suveryn-ingest` prints both.

PostgreSQL and pgvector are provisioned outside this repository (by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance)). This package only connects to them, and creates its own tables.

## Confidential data

- Intermediate files (searchable PDFs, OCR work files) are written only to a private `0700` directory under `SUVERYN_WORK_DIR`. They are deleted as soon as a document is processed, also on errors. While a document is processed, both `tempfile` and `TMPDIR` point there, so OCRmyPDF and its subprocesses do not use `/tmp`.
- Uploads and work folders left behind by a crash are deleted when the document service starts.
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
uv run suveryn-ingest deed.pdf
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
| `HF_HOME` | `~/.cache/huggingface` (the local model cache) |
| `SUVERYN_ALLOW_DOWNLOADS` | unset; `1` only for `suveryn-fetch-models` |

## Tests

```bash
SUVERYN_TEST_DATABASE_URL=$SUVERYN_DATABASE_URL uv run pytest packages/rag
```

- `test_integrity.py` and `test_units.py` are fast unit tests (`test_units.py` also checks the offline guard).
- `test_store.py` checks storage and search against a real pgvector database.
- `test_e2e.py` is the regression bar. It generates a fictional deed with the traps seen so far (`trap_deed.py`): a running header and page numbers, a content line in the footer area, a closing heading, a cadastral reference, and a tenant in arrears buried in boilerplate. It also includes a soil report that exists only as a pasted-in image. It runs that deed through the full pipeline as a born-digital PDF, as a scan, and as a scan with a thin digital label on each page. It requires:
  - no lost text, and dropped furniture
  - an intact cadastral reference
  - the right passage with the right page in the top 5 for every question, and the buried arrears in the top 3
  - the pasted-in scan's text read, with only that page OCR'd in the born-digital variant
  - an empty work directory and status `ok`

The database and end-to-end tests are skipped without `SUVERYN_TEST_DATABASE_URL`. All rag tests are skipped where this package is not installed (plain `uv sync` installs only the gateway).
