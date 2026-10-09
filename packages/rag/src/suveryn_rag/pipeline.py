"""Ingestion and retrieval, wired together.

Retrieved chunks come back as the engine's ``Citation`` objects, so they can go straight
into ``ChatResponse.citations`` with ``source`` filled in (document, page, location).
"""

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from suveryn_engine import Citation, SourceRef

from .chunking import Chunker, location_label
from .config import RagSettings
from .embed import Embedder
from .extract import Extractor
from .store import Store


@dataclass
class IngestResult:
    """What happened to one document. ``warnings`` say where text was recovered or may be missing."""

    document_id: uuid.UUID
    filename: str
    pages: int
    ocr_pages: int
    chunks: int
    already_present: bool  # the same file (by SHA-256) was ingested before; nothing was redone
    timings: dict[str, float]
    status: str = "ok"  # "ok" or "needs_review"
    warnings: list[dict] = field(default_factory=list)
    mixed_pages: int = 0  # of the OCR'd pages: digital text plus large images (e.g. a pasted-in scan)


@dataclass
class RetrievedChunk:
    """One search hit: the passage as a citation, its fused rank score and the document's file name."""

    citation: Citation
    score: float  # only meaningful for ordering within one query
    filename: str


# Whole-document grounding limits. ~48,000 characters is ~14k tokens of Dutch or French: about 15-20
# pages of a deed, leaving room in the shared 64k context for history, answer and parallel users.
# The chunk cap keeps excerpt numbers within the two digits that citation markers ([n]) use.
WHOLE_DOCUMENT_CHARS = 48_000
WHOLE_DOCUMENT_CHUNKS = 99


def _hit(r) -> RetrievedChunk:
    """A stored chunk as a citation with its file name."""
    return RetrievedChunk(
        citation=Citation(text=r.text, source=SourceRef(
            document_id=str(r.document_id), page=r.page_start,
            location=location_label(r.page_start, r.page_end, r.headings))),
        score=r.score, filename=r.filename)


def sha256_of(path: Path) -> str:
    """Content hash used to recognise a document that was already ingested."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Rag:
    """Entry point for ingestion and retrieval.

    Loads the embedding model (and, unless ``load_extractor=False``, Docling and the chunker
    tokenizer) on construction; that takes ~20-40 s, so create one instance per process and
    reuse it. Retrieval-only processes pass ``load_extractor=False`` to skip Docling.
    Not thread-safe for ingestion (see ``Extractor``).
    """

    def __init__(self, settings: RagSettings | None = None, *, load_extractor: bool = True,
                 embedder: Embedder | None = None):
        self.settings = settings or RagSettings.from_env()
        # Pass an existing embedder to share one model between instances (it is thread-safe).
        self.embedder = embedder or Embedder(self.settings.embedding_model, self.settings.device)
        self.store = Store(self.settings.database_url, self.embedder.dim)
        self._extractor = Extractor(self.settings) if load_extractor else None
        self._chunker = Chunker(self.settings.embedding_model, self.settings.chunk_max_tokens) if load_extractor else None

    def close(self) -> None:
        """Close the database connection."""
        self.store.close()

    def ingest(self, pdf: Path, filename: str | None = None) -> IngestResult:
        """Extract, chunk, embed and store one PDF; return its id, status and warnings.

        Idempotent per file content: a PDF whose SHA-256 is already stored is not processed
        again. The document is stored in one transaction, so a failure leaves nothing behind.
        A ``needs_review`` status means text may be missing (see ``integrity``); the document is
        still stored and searchable. ``filename`` is the name to show for the document; it defaults
        to the file's own name (uploads are stored under a random name).
        """
        pdf = Path(pdf)
        name = filename or pdf.name
        digest = sha256_of(pdf)
        existing = self.store.find_by_sha256(digest)
        if existing:
            status, warnings = self.store.document_status(existing)
            return IngestResult(existing, name, 0, 0, 0, True, {}, status, warnings)
        ex = self._extractor.extract(pdf)
        t = time.perf_counter()
        result = self._chunker.chunk(ex.document, ex.page_texts)
        chunks = result.chunks
        ex.timings["chunk"] = time.perf_counter() - t
        t = time.perf_counter()
        vectors = self.embedder.embed([c.embed_text for c in chunks])
        ex.timings["embed"] = time.perf_counter() - t
        t = time.perf_counter()
        doc_id = self.store.add_document(name, digest, ex.pages, ex.ocr_pages, chunks, vectors, result.warnings)
        ex.timings["store"] = time.perf_counter() - t
        status, warnings = self.store.document_status(doc_id)
        return IngestResult(doc_id, name, ex.pages, ex.ocr_pages, len(chunks), False, ex.timings, status, warnings,
                            ex.mixed_pages)

    def retrieve(self, question: str, k: int = 5, document_id: uuid.UUID | None = None,
                 document_ids: list[uuid.UUID] | None = None) -> list[RetrievedChunk]:
        """Return the ``k`` passages most relevant to ``question``, best first.

        ``document_id`` (one) or ``document_ids`` (several) restrict the search. ``source.page`` is the first page
        of the passage; ``source.location`` gives the full page range and section heading.
        Callers that generate answers should pass several hits to the model, not only the
        first: on real deeds the right passage was at #1 for 15 of 19 questions and in the
        top 3 for all 19.
        """
        query = self.embedder.embed([question])[0]
        return [_hit(r) for r in self.store.search(query, k, document_id, question=question, document_ids=document_ids)]

    def passages(self, question: str, document_ids: list[uuid.UUID], k: int) -> tuple[list[RetrievedChunk], bool]:
        """Passages to ground an answer on, and whether they are the documents' complete text.

        Documents that together fit ``WHOLE_DOCUMENT_CHARS`` are given whole, in reading order:
        a general question ("what is this deed about?") then sees everything instead of a few
        passages that happen to rank well. Larger documents fall back to the ``k`` best search hits.
        """
        whole = self.store.document_chunks(document_ids, WHOLE_DOCUMENT_CHARS, WHOLE_DOCUMENT_CHUNKS)
        if whole:
            return [_hit(r) for r in whole], True
        return self.retrieve(question, k=k, document_ids=document_ids), False

    def forget(self, document_id: uuid.UUID) -> bool:
        """Delete a document and all its chunks. Returns False if it didn't exist.

        PostgreSQL keeps deleted rows on disk until vacuumed (and in its write-ahead log for a
        while); see ``Store.delete_document``.
        """
        return self.store.delete_document(document_id)
