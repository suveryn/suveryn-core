"""Command-line entry points: ingest, retrieve and forget (development), and fetch-models (set-up).

These print to the terminal of whoever runs them. ``suveryn-retrieve`` prints passages of the
stored documents, i.e. confidential text; don't redirect its output into shared logs.
"""

import argparse
import json
import uuid

from .config import RagSettings


def ingest_main() -> None:
    """``suveryn-ingest file.pdf [...]``: ingest PDFs; print id, status, warnings and timings per file (no text)."""
    ap = argparse.ArgumentParser(prog="suveryn-ingest", description="Extract, chunk, embed and store PDF documents.")
    ap.add_argument("pdf", nargs="+")
    a = ap.parse_args()
    from .pipeline import Rag

    rag = Rag(RagSettings.from_env())
    try:
        for p in a.pdf:
            r = rag.ingest(p)
            print(json.dumps({"document_id": str(r.document_id), "filename": r.filename, "pages": r.pages,
                              "ocr_pages": r.ocr_pages, "mixed_pages": r.mixed_pages, "chunks": r.chunks, "already_present": r.already_present,
                              "status": r.status, "warnings": [{k: w[k] for k in ("page", "kind", "detail")} for w in r.warnings],
                              "timings_s": {k: round(v, 2) for k, v in r.timings.items()}}, ensure_ascii=False))
    finally:
        rag.close()


def retrieve_main() -> None:
    """``suveryn-retrieve "question" [-k 5] [--document id]``: print the best passages as citations (JSON)."""
    ap = argparse.ArgumentParser(prog="suveryn-retrieve", description="Return the chunks most relevant to a question.")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--document", type=uuid.UUID, help="only search this document")
    a = ap.parse_args()
    from .pipeline import Rag

    rag = Rag(RagSettings.from_env(), load_extractor=False)
    try:
        hits = rag.retrieve(a.question, a.k, a.document)
        print(json.dumps([{"score": round(h.score, 4), "filename": h.filename, **h.citation.model_dump()} for h in hits],
                         ensure_ascii=False, indent=1))
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
        print("deleted" if store.delete_document(a.document_id) else "not found")
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
    Embedder(settings.embedding_model, settings.device)
    Chunker(settings.embedding_model, settings.chunk_max_tokens)
    Extractor(settings)
    print(json.dumps({"embedding_model": settings.embedding_model, "docling": "layout and table models",
                      "cache": os.environ.get("HF_HOME", "~/.cache/huggingface")}))
