"""PostgreSQL + pgvector storage for documents and their chunks.

PostgreSQL itself is provisioned outside suveryn-core (suveryn-appliance); this module only
connects to it and creates its own tables if they don't exist yet.
"""

import uuid
from dataclasses import dataclass

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from .chunking import Chunk


def schema_sql(dim: int) -> str:
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
CREATE INDEX IF NOT EXISTS chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
"""


@dataclass
class StoredChunk:
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None
    headings: list[str]
    score: float  # cosine similarity, 1.0 = identical direction


class Store:
    def __init__(self, database_url: str, dim: int):
        if not database_url:
            raise ValueError("SUVERYN_DATABASE_URL is not set")
        self._conn = psycopg.connect(database_url, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._conn)
        self._conn.execute(schema_sql(dim))

    def close(self) -> None:
        self._conn.close()

    def find_by_sha256(self, sha256: str) -> uuid.UUID | None:
        row = self._conn.execute("SELECT id FROM documents WHERE sha256 = %s", (sha256,)).fetchone()
        return row[0] if row else None

    def add_document(self, filename: str, sha256: str, pages: int, ocr_pages: int,
                     chunks: list[Chunk], embeddings: np.ndarray) -> uuid.UUID:
        with self._conn.transaction():
            doc_id = self._conn.execute(
                "INSERT INTO documents (filename, sha256, pages, ocr_pages) VALUES (%s, %s, %s, %s) RETURNING id",
                (filename, sha256, pages, ocr_pages)).fetchone()[0]
            with self._conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, text, page_start, page_end, headings, embedding)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(doc_id, c.index, c.text, c.page_start, c.page_end, c.headings, e)
                     for c, e in zip(chunks, embeddings, strict=True)])
        return doc_id

    def delete_document(self, document_id: uuid.UUID) -> bool:
        return self._conn.execute("DELETE FROM documents WHERE id = %s", (document_id,)).rowcount > 0

    def search(self, query: np.ndarray, k: int, document_id: uuid.UUID | None = None) -> list[StoredChunk]:
        where, params = ("WHERE c.document_id = %s", [document_id]) if document_id else ("", [])
        rows = self._conn.execute(
            f"SELECT c.document_id, d.filename, c.chunk_index, c.text, c.page_start, c.page_end, c.headings,"
            f"       1 - (c.embedding <=> %s) AS score"
            f"  FROM chunks c JOIN documents d ON d.id = c.document_id {where}"
            f" ORDER BY c.embedding <=> %s LIMIT %s",
            [query, *params, query, k]).fetchall()
        return [StoredChunk(*r[:6], list(r[6] or []), float(r[7])) for r in rows]
