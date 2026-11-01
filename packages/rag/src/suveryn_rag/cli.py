"""Command-line entry points: ingest and forget (development: ``scripts/intake-benchmark``), and
fetch-models (set-up). They print no document text.
"""

import argparse
import json
import uuid

from .config import RagSettings


def ingest_main() -> None:
    """``suveryn-ingest file.pdf [...]``: ingest PDF, Word, Excel, Markdown or CSV files; print id, status, warnings and timings per file (no text)."""
    ap = argparse.ArgumentParser(prog="suveryn-ingest", description="Extract, chunk, embed and store documents (PDF, .docx, .xlsx, .md, .csv).")
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--owner", help="Keycloak user id (sub) the documents belong to; without it they are "
                                    "visible to no user in the chat, only to these operator tools")
    a = ap.parse_args()
    from .pipeline import Rag

    rag = Rag(RagSettings.from_env())
    try:
        for p in a.pdf:
            r = rag.ingest(p, owner=a.owner)
            print(json.dumps({"document_id": str(r.document_id), "filename": r.filename, "pages": r.pages,
                              "ocr_pages": r.ocr_pages, "mixed_pages": r.mixed_pages, "chunks": r.chunks, "already_present": r.already_present,
                              "status": r.status, "warnings": [{k: w[k] for k in ("page", "kind", "detail")} for w in r.warnings],
                              "timings_s": {k: round(v, 2) for k, v in r.timings.items()}}, ensure_ascii=False))
    finally:
        rag.close()


def forget_main() -> None:
    """``suveryn-forget <document-id>``: delete a document and its chunks (see ``Store.delete_document`` caveat)."""
    ap = argparse.ArgumentParser(prog="suveryn-forget", description="Delete a document and all of its chunks.")
    ap.add_argument("document_id", type=uuid.UUID)
    a = ap.parse_args()
    from .store import Store

    s = RagSettings.from_env()
    store = Store(s.database_url, s.embedding_dim)  # the configured dimension; only used to create tables if missing
    try:
        deleted = store.delete_document(a.document_id)
        print("deleted" if deleted else "not found")
        if deleted:
            from .journal import flush_journal
            flush_journal(s.database_url)  # the journal that still holds its text (journal.py)
    finally:
        store.close()


def fetch_models_main() -> None:
    """``suveryn-fetch-models``: download the embedding model and Docling's models into the local cache.

    Run once when a machine is set up (needs internet access); everything else runs offline (see
    ``offline``). Loads each model the same way the pipeline does, so exactly the files it needs
    end up in ``HF_HOME``. Prints no document data; it reads no documents.
    """
    import os

    from . import offline

    os.environ["SUVERYN_ALLOW_DOWNLOADS"] = "1"
    offline.enforce()
    argparse.ArgumentParser(prog="suveryn-fetch-models", description=fetch_models_main.__doc__.splitlines()[0]).parse_args()
    from .chunking import Chunker
    from .embed import Embedder
    from .extract import Extractor

    settings = RagSettings.from_env()
    Embedder(settings.embedding_model, settings.device, settings.embed_batch_size)
    Chunker(settings.embedding_model, settings.chunk_max_tokens)
    Extractor(settings)
    print(json.dumps({"embedding_model": settings.embedding_model, "docling": "layout and table models",
                      "cache": os.environ.get("HF_HOME", "~/.cache/huggingface")}))
