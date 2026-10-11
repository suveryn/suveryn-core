"""Ingestion and retrieval, wired together.

Retrieved chunks come back as the engine's ``Citation`` objects, so they can go straight
into ``ChatResponse.citations`` with ``source`` filled in (document, page, location).
"""

import hashlib
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from suveryn_engine import Citation, SourceRef
from suveryn_engine.audit import audit
from suveryn_engine.guard import instruction_like

from .chunking import Chunker, location_label
from .config import RagSettings
from .embed import Embedder
from .integrity import (
    LINE_BREAK_HYPHEN,
    IntegrityWarning,
    misdecoding,
    ocr_noise,
    repair_characters,
    words,
)
from .isolation import make_extractor
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


# Uploading the same file again normally returns the stored copy. It is read again when that copy was
# read poorly: in review, or most of its text came from the text-layer recovery instead of the layout
# model (reported 2026-10-11: a document read while the GPU was full, uploaded again, stayed garbled).
REREAD_RECOVERED_SHARE = 0.5


def misread(text: str) -> bool:
    """Whether stored text still shows a misread encoding or line-break hyphens (stored before they were put right)."""
    return misdecoding(text) is not None or LINE_BREAK_HYPHEN in text


def should_read_again(status: str, recovered_share: float, misdecoded: bool = False) -> bool:
    """Whether an upload of a file already stored should read it again instead of returning the stored copy:
    also when it was stored with characters read in the wrong encoding, line-break hyphens (``misread``) or
    recovered OCR noise, from before those were handled."""
    return status == "needs_review" or recovered_share > REREAD_RECOVERED_SHARE or misdecoded


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
        # Uploaded PDFs are read in a separate process, away from secrets and other users' data (``isolation``).
        self._extractor = make_extractor(self.settings) if load_extractor else None
        self._chunker = Chunker(self.settings.embedding_model, self.settings.chunk_max_tokens) if load_extractor else None

    def close(self) -> None:
        """Close the database connection and stop the PDF reader process."""
        self.store.close()
        if hasattr(self._extractor, "close"):
            self._extractor.close()

    def ingest(self, pdf: Path, filename: str | None = None, owner: str | None = None) -> IngestResult:
        """Extract, chunk, embed and store one PDF; return its id, status and warnings.

        Idempotent per file content: a PDF whose SHA-256 is already stored is not processed
        again, unless the stored copy was read poorly (``should_read_again``): then it is read again
        and replaced in place, keeping its id. The document is stored in one transaction, so a failure leaves nothing behind.
        A ``needs_review`` status means text may be missing (see ``integrity``); the document is
        still stored and searchable. ``filename`` is the name to show for the document; it defaults
        to the file's own name (uploads are stored under a random name).
        """
        pdf = Path(pdf)
        name = filename or pdf.name
        digest = sha256_of(pdf)
        existing = self.store.find_by_sha256(digest, owner)  # the owner's own copy only
        if existing:
            status, warnings = self.store.document_status(existing)
            vocabulary = words(self.store.document_text(existing, recovered=False))
            noisy = any(ocr_noise(line, vocabulary) for line in self.store.document_text(existing, recovered=True).splitlines())
            if not should_read_again(status, self.store.recovered_share(existing),
                                     misread(self.store.document_text(existing)) or noisy):
                return IngestResult(existing, name, 0, 0, 0, True, {}, status, warnings)
            # The same file again, and the stored copy was read poorly: read it again, in place (same id).
        ex = self._extractor.extract(pdf)
        t = time.perf_counter()
        result = self._chunker.chunk(ex.document, ex.page_texts)
        chunks = result.chunks
        # Characters read with the wrong encoding ("ŽŽn" for "één", "ÒwoordÓ"), and line-break hyphens: put right
        # for the whole document, the encoding only when it clearly shows (see integrity.misdecoding).
        how = misdecoding(" ".join(c.text + " " + " ".join(c.headings) for c in chunks))
        chunks = [replace(c, text=repair_characters(c.text, how), embed_text=repair_characters(c.embed_text, how),
                          headings=[repair_characters(h, how) for h in c.headings]) for c in chunks]
        # Text addressed to an AI ("ignore the instructions…"): a signal for the reader, not a block
        # (suveryn-tracker#21). It doesn't change the status: the text isn't missing.
        # Pages the layout model couldn't read (suveryn-tracker: GPU out of memory, 2026-10-11): their text
        # comes only from the text-layer recovery, without structure; the document needs review.
        result.warnings += [IntegrityWarning(page, "layout_failed", "the layout model couldn't read this page; "
                                             "its text was recovered from the PDF text layer") for page in ex.layout_failed_pages]
        suspicious = {page: kinds for page, text in enumerate(ex.page_texts, 1) if (kinds := instruction_like(text))}
        result.warnings += [IntegrityWarning(page, "instruction_like_text", "text addressed to an AI: " + ", ".join(kinds))
                            for page, kinds in suspicious.items()]
        ex.timings["chunk"] = time.perf_counter() - t
        t = time.perf_counter()
        vectors = self.embedder.embed([c.embed_text for c in chunks])
        ex.timings["embed"] = time.perf_counter() - t
        t = time.perf_counter()
        if existing:
            doc_id = self.store.replace_document(existing, name, ex.pages, ex.ocr_pages, chunks, vectors, result.warnings)
        else:
            doc_id = self.store.add_document(name, digest, ex.pages, ex.ocr_pages, chunks, vectors, result.warnings, owner)
        if suspicious:
            audit("instruction_like_document", user=owner, document=str(doc_id), pages=sorted(suspicious),
                  kinds=sorted({k for kinds in suspicious.values() for k in kinds}))
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
        passages that happen to rank well. Larger documents get as much as the same budget allows:
        their best-matching passages (at least ``k``), in reading order (``Store.best_chunks``).
        Before, they got only the ``k`` best hits: a 58-page deed showed the model 6 passages,
        about 4% of its text, and broad questions found nothing.
        """
        whole = self.store.document_chunks(document_ids, WHOLE_DOCUMENT_CHARS, WHOLE_DOCUMENT_CHUNKS)
        if whole:
            return [_hit(r) for r in whole], True
        query = self.embedder.embed([question])[0]
        best = self.store.best_chunks(query, question, document_ids, WHOLE_DOCUMENT_CHARS, WHOLE_DOCUMENT_CHUNKS, k)
        return [_hit(r) for r in best], False

    def forget(self, document_id: uuid.UUID) -> bool:
        """Delete a document and all its chunks. Returns False if it didn't exist.

        PostgreSQL keeps deleted rows on disk until vacuumed (and in its write-ahead log for a
        while); see ``Store.delete_document``.
        """
        return self.store.delete_document(document_id)
