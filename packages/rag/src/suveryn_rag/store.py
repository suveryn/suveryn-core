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
    sha256      text NOT NULL,
    pages       integer NOT NULL,
    ocr_pages   integer NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ok';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS warnings jsonb NOT NULL DEFAULT '[]';
-- Every document belongs to one user (the Keycloak "sub"). Documents stored before owners existed
-- have owner NULL and are visible to no one (fail closed); see docs/architecture.md.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner text;
-- A file is de-duplicated per owner only: the same PDF uploaded by two users is two documents, so
-- an upload can never return another user's document.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS documents_owner_sha256 ON documents (owner, sha256);
CREATE INDEX IF NOT EXISTS documents_owner ON documents (owner);
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
        self._url = database_url
        self._conn = psycopg.connect(database_url, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._conn)
        self._conn.execute(schema_sql(dim))

    def reconnect(self) -> None:
        """Replace the connection with a new one (after PostgreSQL restarted or dropped it)."""
        try:
            self._conn.close()
        except psycopg.Error:
            pass
        self._conn = psycopg.connect(self._url, autocommit=True)
        register_vector(self._conn)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def find_by_sha256(self, sha256: str, owner: str | None) -> uuid.UUID | None:
        """Id of this owner's document with this content hash, if they ingested it before.

        Never another owner's document: de-duplication is per owner. ``owner=None`` matches only
        documents without an owner (operator tools).
        """
        row = self._conn.execute("SELECT id FROM documents WHERE sha256 = %s AND owner IS NOT DISTINCT FROM %s",
                                 (sha256, owner)).fetchone()
        return row[0] if row else None

    def add_document(self, filename: str, sha256: str, pages: int, ocr_pages: int, chunks: list[Chunk],
                     embeddings: np.ndarray, warnings: list[IntegrityWarning] | None = None,
                     owner: str | None = None) -> uuid.UUID:
        """Store a document and its chunks in one transaction (all or nothing), owned by ``owner``.

        Status is ``needs_review`` if any warning means text may be missing; recovered or
        restored text alone keeps it ``ok``. The file name is stored too and may itself be
        personal data (e.g. a client's name).
        """
        warnings = warnings or []
        status = "needs_review" if any(w.needs_review for w in warnings) else "ok"
        with self._conn.transaction():
            doc_id = self._conn.execute(
                "INSERT INTO documents (filename, sha256, pages, ocr_pages, status, warnings, owner)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (filename, sha256, pages, ocr_pages, status,
                 json.dumps([{"page": w.page, "kind": w.kind, "detail": w.detail} for w in warnings]), owner)).fetchone()[0]
            with self._conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, text, page_start, page_end, headings, origin,"
                    " embedding, tsv) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, to_tsvector('simple', %s))",
                    [(doc_id, c.index, c.text, c.page_start, c.page_end, c.headings, c.origin, e,
                      c.text + " " + " ".join(c.headings))
                     for c, e in zip(chunks, embeddings, strict=True)])
        return doc_id

    def list_documents(self, owner: str) -> list[dict]:
        """The owner's documents, newest first: id, file name, pages, OCR'd pages, status, warnings, chunks, created."""
        rows = self._conn.execute(
            "SELECT d.id, d.filename, d.pages, d.ocr_pages, d.status, d.warnings, d.created_at,"
            "       (SELECT count(*) FROM chunks c WHERE c.document_id = d.id)"
            "  FROM documents d WHERE d.owner = %s ORDER BY d.created_at DESC", (owner,)).fetchall()
        keys = ("id", "filename", "pages", "ocr_pages", "status", "warnings", "created_at", "chunks")
        return [dict(zip(keys, r)) for r in rows]

    def document_status(self, document_id: uuid.UUID) -> tuple[str, list[dict]] | None:
        """(status, warnings) of a stored document, or None if it doesn't exist."""
        row = self._conn.execute("SELECT status, warnings FROM documents WHERE id = %s", (document_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def owned(self, document_ids: list[uuid.UUID], owner: str) -> set[uuid.UUID]:
        """Which of these documents belong to ``owner`` (the others don't exist or are someone else's)."""
        rows = self._conn.execute("SELECT id FROM documents WHERE id = ANY(%s) AND owner = %s",
                                  (list(document_ids), owner)).fetchall()
        return {r[0] for r in rows}

    def delete_document(self, document_id: uuid.UUID, owner: str | None = None) -> bool:
        """Delete a document (only the owner's when ``owner`` is given); its chunks go with it (ON DELETE CASCADE).

        Review note: this makes the text unreachable, not unrecoverable. PostgreSQL keeps dead
        rows in the table files until VACUUM rewrites them, and changes stay in the write-ahead
        log for a while. Secure deletion (encryption at rest, crypto-shredding or a scheduled
        VACUUM FULL) is an open item (docs/architecture.md §6).
        """
        if owner is None:  # operator tools (suveryn-forget)
            return self._conn.execute("DELETE FROM documents WHERE id = %s", (document_id,)).rowcount > 0
        return self._conn.execute("DELETE FROM documents WHERE id = %s AND owner = %s",
                                  (document_id, owner)).rowcount > 0

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

    def best_chunks(self, query: np.ndarray, question: str, document_ids: list[uuid.UUID], max_chars: int,
                    max_chunks: int, min_chunks: int) -> list[StoredChunk]:
        """The documents' best-matching chunks that fit the limits, in reading order.

        For documents too large to give whole: instead of a handful of search hits, the model gets
        as much of the documents as the whole-document budget allows, chosen by relevance.

        Every chunk of the documents is ranked exactly (no ``CANDIDATES`` cut-off and no HNSW
        index, so no post-filtering loss): by vector similarity and by keyword match, fused as in
        ``search``. Chunks are then taken best first while they fit ``max_chars`` and
        ``max_chunks``; the best ``min_chunks`` are always taken. The result is returned in reading
        order (as ``document_chunks``), with the fused score kept on each chunk.

        Review note: the f-string interpolates constants only; query, documents and terms are
        bound parameters. ``+ 0`` in the vector ordering keeps PostgreSQL from using the HNSW
        index, whose approximate search would return only ``hnsw.ef_search`` rows.
        """
        tsq = self._keyword_query(question, document_ids)
        keyword = ("COALESCE(1.0 / ({k} + (SELECT r FROM kw WHERE kw.id = c.id)), 0)".format(k=RRF_K)
                   if tsq else "0")
        kw_cte = ("""kw AS (SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q) DESC) AS r
                              FROM chunks c, to_tsquery('simple', %(tsq)s) q
                             WHERE c.document_id = ANY(%(docs)s) AND c.tsv @@ q),""" if tsq else "")
        rows = self._conn.execute(f"""
            WITH {kw_cte}
            vec AS (SELECT c.id, row_number() OVER (ORDER BY (c.embedding <=> %(q)s) + 0) AS r
                      FROM chunks c WHERE c.document_id = ANY(%(docs)s) AND c.text ~ %(min_words)s)
            SELECT c.document_id, d.filename, c.chunk_index, c.text, c.page_start, c.page_end, c.headings, c.origin,
                   COALESCE(1.0 / ({RRF_K} + (SELECT r FROM vec WHERE vec.id = c.id)), 0) + {keyword} AS score,
                   1 - (c.embedding <=> %(q)s) AS similarity
              FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE c.document_id = ANY(%(docs)s)
             ORDER BY score DESC, similarity DESC""",
            {"q": query, "docs": document_ids, "tsq": tsq, "min_words": MIN_WORDS_FOR_VECTOR}).fetchall()
        chosen, size = [], 0
        for r in rows:
            if len(chosen) >= max_chunks:
                break
            if len(chosen) >= min_chunks and size + len(r[3]) > max_chars:
                continue  # a smaller, lower-ranked chunk may still fit
            chosen.append(r)
            size += len(r[3])
        order = {d: i for i, d in enumerate(document_ids)}
        chosen.sort(key=lambda r: (order[r[0]], r[4] if r[4] is not None else 1 << 30, r[2]))
        return [StoredChunk(r[0], r[1], r[2], r[3], r[4], r[5], list(r[6] or []), r[7], float(r[8]), float(r[9]))
                for r in chosen]

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
