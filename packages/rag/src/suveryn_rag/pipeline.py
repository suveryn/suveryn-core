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
    document_id: uuid.UUID
    filename: str
    pages: int
    ocr_pages: int
    chunks: int
    already_present: bool
    timings: dict[str, float]
    status: str = "ok"  # "ok" or "needs_review"
    warnings: list[dict] = field(default_factory=list)


@dataclass
class RetrievedChunk:
    citation: Citation
    score: float
    filename: str


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Rag:
    def __init__(self, settings: RagSettings | None = None, *, load_extractor: bool = True):
        self.settings = settings or RagSettings.from_env()
        self.embedder = Embedder(self.settings.embedding_model, self.settings.device)
        self.store = Store(self.settings.database_url, self.embedder.dim)
        self._extractor = Extractor(self.settings) if load_extractor else None
        self._chunker = Chunker(self.settings.embedding_model, self.settings.chunk_max_tokens) if load_extractor else None

    def close(self) -> None:
        self.store.close()

    def ingest(self, pdf: Path) -> IngestResult:
        pdf = Path(pdf)
        digest = sha256_of(pdf)
        existing = self.store.find_by_sha256(digest)
        if existing:
            status, warnings = self.store.document_status(existing)
            return IngestResult(existing, pdf.name, 0, 0, 0, True, {}, status, warnings)
        ex = self._extractor.extract(pdf)
        t = time.perf_counter()
        result = self._chunker.chunk(ex.document, ex.page_texts)
        chunks = result.chunks
        ex.timings["chunk"] = time.perf_counter() - t
        t = time.perf_counter()
        vectors = self.embedder.embed([c.embed_text for c in chunks])
        ex.timings["embed"] = time.perf_counter() - t
        t = time.perf_counter()
        doc_id = self.store.add_document(pdf.name, digest, ex.pages, ex.ocr_pages, chunks, vectors, result.warnings)
        ex.timings["store"] = time.perf_counter() - t
        status, warnings = self.store.document_status(doc_id)
        return IngestResult(doc_id, pdf.name, ex.pages, ex.ocr_pages, len(chunks), False, ex.timings, status, warnings)

    def retrieve(self, question: str, k: int = 5, document_id: uuid.UUID | None = None) -> list[RetrievedChunk]:
        query = self.embedder.embed([question])[0]
        return [
            RetrievedChunk(
                citation=Citation(text=r.text, source=SourceRef(
                    document_id=str(r.document_id), page=r.page_start,
                    location=location_label(r.page_start, r.page_end, r.headings))),
                score=r.score, filename=r.filename)
            for r in self.store.search(query, k, document_id, question=question)
        ]

    def forget(self, document_id: uuid.UUID) -> bool:
        return self.store.delete_document(document_id)
