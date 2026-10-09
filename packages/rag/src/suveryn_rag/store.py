"""PostgreSQL + pgvector storage for documents and their chunks, with hybrid retrieval.

PostgreSQL itself is provisioned outside suveryn-core (suveryn-appliance); this module only
connects to it and creates or upgrades its own tables.

Retrieval combines two rankings with Reciprocal Rank Fusion:
- vector similarity (bge-m3 embeddings, HNSW index), good at meaning and paraphrase;
- keyword match (PostgreSQL full-text, 'simple' configuration so Dutch, French and English
  words and numbers are matched as written), good at exact terms such as "huurachterstand",
  "vierde rang" or "1563" that the vector ranking can bury under boilerplate.
Query words that occur in a large share of the chunks are left out of the keyword query, so
common words don't drown out the rare, specific ones.
"""

import json
import uuid
from dataclasses import dataclass

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from .chunking import Chunk
from .integrity import IntegrityWarning, query_terms

RRF_K = 60            # standard Reciprocal Rank Fusion constant
CANDIDATES = 30       # candidates taken from each ranking before fusion
MAX_TERM_SHARE = 0.2  # keyword terms found in more than this share of chunks are ignored
# Chunks of one or two words (a reference code, a stray header) are too short to carry meaning, yet
# their embeddings can sit close to a vague question. They stay findable by keyword, not by vector.
MIN_WORDS_FOR_VECTOR = r"\S+\s+\S+\s+\S"


def schema_sql(dim: int) -> str:
    """Idempotent DDL: creates the tables and indexes, and adds columns introduced later (ADD COLUMN IF NOT EXISTS)."""
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    text NOT NULL,
    sha256      text NOT NULL UNIQUE,
    pages       integer NOT NULL,
    ocr_pages   integer NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ok';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS warnings jsonb NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS chunks (
    id           bigserial PRIMARY KEY,
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    text         text NOT NULL,
    page_start   integer,
    page_end     integer,
    headings     text[] NOT NULL DEFAULT '{{}}',
    embedding    vector({dim}) NOT NULL,
    UNIQUE (document_id, chunk_index)
);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'chunker';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector;
CREATE INDEX IF NOT EXISTS chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING gin (tsv);
"""


@dataclass
class StoredChunk:
    """One search hit as read from the database."""

    document_id: uuid.UUID
    filename: str
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None
    headings: list[str]
    origin: str
    score: float       # fused rank score (higher is better), only comparable within one query
    similarity: float  # cosine similarity to the question, 1.0 = identical direction


class Store:
    """One database connection (autocommit; explicit transactions where several writes belong together).

    Creates or upgrades its tables on connect, so it needs CREATE rights on the database. The
    pgvector extension must be available on the server (installed by suveryn-appliance).
    """

    def __init__(self, database_url: str, dim: int):
        if not database_url:
            raise ValueError("SUVERYN_DATABASE_URL is not set")
        self._conn = psycopg.connect(database_url, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._conn)
        self._conn.execute(schema_sql(dim))

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def find_by_sha256(self, sha256: str) -> uuid.UUID | None:
        """Id of the document with this content hash, if it was ingested before."""
        row = self._conn.execute("SELECT id FROM documents WHERE sha256 = %s", (sha256,)).fetchone()
        return row[0] if row else None

    def add_document(self, filename: str, sha256: str, pages: int, ocr_pages: int, chunks: list[Chunk],
                     embeddings: np.ndarray, warnings: list[IntegrityWarning] | None = None) -> uuid.UUID:
        """Store a document and its chunks in one transaction (all or nothing).

        Status is ``needs_review`` if any warning means text may be missing; recovered or
        restored text alone keeps it ``ok``. The file name is stored too and may itself be
        personal data (e.g. a client's name).
        """
        warnings = warnings or []
        status = "needs_review" if any(w.needs_review for w in warnings) else "ok"
        with self._conn.transaction():
            doc_id = self._conn.execute(
                "INSERT INTO documents (filename, sha256, pages, ocr_pages, status, warnings)"
                " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (filename, sha256, pages, ocr_pages, status,
                 json.dumps([{"page": w.page, "kind": w.kind, "detail": w.detail} for w in warnings]))).fetchone()[0]
            with self._conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, text, page_start, page_end, headings, origin,"
                    " embedding, tsv) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, to_tsvector('simple', %s))",
                    [(doc_id, c.index, c.text, c.page_start, c.page_end, c.headings, c.origin, e,
                      c.text + " " + " ".join(c.headings))
                     for c, e in zip(chunks, embeddings, strict=True)])
        return doc_id

    def list_documents(self) -> list[dict]:
        """All stored documents, newest first: id, file name, pages, OCR'd pages, status, warnings, chunks, created."""
        rows = self._conn.execute(
            "SELECT d.id, d.filename, d.pages, d.ocr_pages, d.status, d.warnings, d.created_at,"
            "       (SELECT count(*) FROM chunks c WHERE c.document_id = d.id)"
            "  FROM documents d ORDER BY d.created_at DESC").fetchall()
        keys = ("id", "filename", "pages", "ocr_pages", "status", "warnings", "created_at", "chunks")
        return [dict(zip(keys, r)) for r in rows]

    def document_status(self, document_id: uuid.UUID) -> tuple[str, list[dict]] | None:
        """(status, warnings) of a stored document, or None if it doesn't exist."""
        row = self._conn.execute("SELECT status, warnings FROM documents WHERE id = %s", (document_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def delete_document(self, document_id: uuid.UUID) -> bool:
        """Delete a document; its chunks go with it (ON DELETE CASCADE).

        Review note: this makes the text unreachable, not unrecoverable. PostgreSQL keeps dead
        rows in the table files until VACUUM rewrites them, and changes stay in the write-ahead
        log for a while. Secure deletion (encryption at rest, crypto-shredding or a scheduled
        VACUUM FULL) is an open design item (development context §11.5).
        """
        return self._conn.execute("DELETE FROM documents WHERE id = %s", (document_id,)).rowcount > 0

    def _keyword_query(self, question: str, docs: list[uuid.UUID] | None) -> str | None:
        """OR-query of the question's specific terms, leaving out terms that occur in many chunks."""
        terms = query_terms(question)
        if not terms:
            return None
        scope, params = ("WHERE document_id = ANY(%s)", [docs]) if docs else ("", [])
        counts = ", ".join("count(*) FILTER (WHERE tsv @@ to_tsquery('simple', %s))" for _ in terms)
        row = self._conn.execute(f"SELECT count(*), {counts} FROM chunks {scope}", [*terms, *params]).fetchone()
        total, shares = row[0], row[1:]
        kept = [t for t, n in zip(terms, shares) if total and 0 < n <= max(1, MAX_TERM_SHARE * total)]
        return " | ".join(kept) or None

    def search(self, query: np.ndarray, k: int, document_id: uuid.UUID | None = None,
               question: str | None = None, document_ids: list[uuid.UUID] | None = None) -> list[StoredChunk]:
        """Hybrid search: up to ``CANDIDATES`` hits from each ranking, fused, best ``k`` returned.

        A chunk's score is 1/(60 + rank) summed over the rankings it appears in, so a chunk
        found by both rises to the top. Without ``question`` this is plain vector search.
        ``document_id`` (one) or ``document_ids`` (several) restrict the search; neither: all documents.

        Chunks with fewer than three words are left out of the vector ranking (see
        ``MIN_WORDS_FOR_VECTOR``); the keyword ranking still finds them.

        Review notes:
        - The SQL is assembled with f-strings, but only from constants and fixed fragments;
          the question vector, document id, keyword query and k are always bound parameters.
          Keyword terms are ``\\w+`` tokens (``query_terms``), also passed as parameters.
        - With ``document_id`` set, pgvector's HNSW index filters *after* its approximate
          search; in a large multi-document database a small document can then return fewer
          than ``CANDIDATES`` vector hits. The keyword ranking is exact. Revisit (e.g. raise
          ``hnsw.ef_search`` or use iterative scans) when databases grow.
        """
        docs = [document_id] if document_id else (list(document_ids) if document_ids else None)
        scope = "AND c.document_id = ANY(%(docs)s)" if docs else ""
        tsq = self._keyword_query(question, docs) if question else None
        keyword_cte = (f"""kw AS (
              SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q) DESC) AS r
                FROM chunks c, to_tsquery('simple', %(tsq)s) q
               WHERE c.tsv @@ q {scope}
               ORDER BY ts_rank_cd(c.tsv, q) DESC LIMIT {CANDIDATES})"""
                       if tsq else "kw AS (SELECT NULL::bigint AS id, NULL::bigint AS r WHERE false)")
        rows = self._conn.execute(f"""
            WITH vec AS (
              SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(q)s) AS r
                FROM chunks c WHERE c.text ~ %(min_words)s {scope}
               ORDER BY c.embedding <=> %(q)s LIMIT {CANDIDATES}),
            {keyword_cte}
            SELECT c.document_id, d.filename, c.chunk_index, c.text, c.page_start, c.page_end, c.headings, c.origin,
                   COALESCE(1.0 / ({RRF_K} + vec.r), 0) + COALESCE(1.0 / ({RRF_K} + kw.r), 0) AS score,
                   1 - (c.embedding <=> %(q)s) AS similarity
              FROM chunks c
              JOIN documents d ON d.id = c.document_id
              LEFT JOIN vec ON vec.id = c.id
              LEFT JOIN kw ON kw.id = c.id
             WHERE vec.id IS NOT NULL OR kw.id IS NOT NULL
             ORDER BY score DESC, similarity DESC
             LIMIT %(k)s""", {"q": query, "docs": docs, "tsq": tsq, "k": k,
                                                  "min_words": MIN_WORDS_FOR_VECTOR}).fetchall()
        return [StoredChunk(r[0], r[1], r[2], r[3], r[4], r[5], list(r[6] or []), r[7], float(r[8]), float(r[9]))
                for r in rows]

    def document_chunks(self, document_ids: list[uuid.UUID], max_chars: int, max_chunks: int) -> list[StoredChunk] | None:
        """Every chunk of the documents in reading order, or None if they are larger than the limits.

        Reading order: documents in the order given, then by first page, then chunk index (text
        recovered by the integrity checks follows the regular chunks of its page). ``score`` and
        ``similarity`` are 0: nothing was ranked.
        """
        size, count = self._conn.execute(
            "SELECT coalesce(sum(length(text)), 0), count(*) FROM chunks WHERE document_id = ANY(%s)",
            (document_ids,)).fetchone()
        if size > max_chars or count > max_chunks:
            return None
        rows = self._conn.execute(
            "SELECT c.document_id, d.filename, c.chunk_index, c.text, c.page_start, c.page_end, c.headings, c.origin"
            "  FROM chunks c JOIN documents d ON d.id = c.document_id"
            " WHERE c.document_id = ANY(%(docs)s)"
            " ORDER BY array_position(%(docs)s, c.document_id), c.page_start NULLS LAST, c.chunk_index",
            {"docs": document_ids}).fetchall()
        return [StoredChunk(r[0], r[1], r[2], r[3], r[4], r[5], list(r[6] or []), r[7], 0.0, 0.0) for r in rows]
