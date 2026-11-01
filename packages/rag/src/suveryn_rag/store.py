"""PostgreSQL + pgvector storage for documents and their chunks, with hybrid retrieval.

PostgreSQL itself is provisioned outside suveryn-core (suveryn-appliance); this module only
connects to it and creates or upgrades its own tables.

Retrieval combines two rankings with Reciprocal Rank Fusion:
- vector similarity (bge-m3 embeddings, compared exactly: no vector index), good at meaning and paraphrase;
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
MAX_TERM_SHARE = 0.2  # keyword terms found in more than this share of chunks are ignored
# Chunks of one or two words (a reference code, a stray header) are too short to carry meaning, yet
# their embeddings can sit close to a vague question. They stay findable by keyword, not by vector.
MIN_WORDS_FOR_VECTOR = r"\S+\s+\S+\s+\S"


def schema_sql(dim: int) -> str:
    """Idempotent DDL: creates the tables and indexes."""
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    text NOT NULL,
    sha256      text NOT NULL,
    pages       integer NOT NULL,
    ocr_pages   integer NOT NULL,
    status      text NOT NULL DEFAULT 'ok',
    warnings    jsonb NOT NULL DEFAULT '[]',
    -- Who uploaded it (the Keycloak "sub"), for a document in its uploader's personal space. A document
    -- with neither owner nor case (``suveryn-ingest`` without ``--owner``) is visible to no one (fail closed).
    owner       text,
    -- The case it belongs to (docs/design/cases.md), or NULL for its uploader's personal space. The case
    -- decides who may read it; the gateway checks that and passes a Scope. Cases live in the gateway's own
    -- table, so there is no foreign key here (separate connections).
    case_id     uuid,
    -- Where it came from: uploaded, generated (by sūveryn: an export, a draft) or playbook. Only uploaded
    -- documents are sources for answers: the AI never cites its own earlier output.
    origin      text NOT NULL DEFAULT 'uploaded',
    -- More about where it came from (docs/design/chat-ui.md §6): for a playbook result the playbook and its
    -- version; for an upload that carries sūveryn's own export mark, what was noticed ("noticed") and, once a
    -- person chose to use it as a source anyway, who and when ("confirmed").
    provenance  jsonb,
    -- What sūveryn made, as the UI needs it to rebuild the file (docs/design/chat-ui.md §5): a saved answer's
    -- question, text, sources and checks. Not in the lists; read one document at a time. Its sources'
    -- passages are taken out when their document is deleted (``delete_document``).
    content     jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
-- A file is de-duplicated within its scope only: the same PDF in two personal spaces, or in two cases, is
-- two documents, so an upload can never return a document from elsewhere.
CREATE UNIQUE INDEX IF NOT EXISTS documents_personal_sha256 ON documents (owner, sha256) WHERE case_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS documents_case_sha256 ON documents (case_id, sha256) WHERE case_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS documents_owner ON documents (owner);
CREATE INDEX IF NOT EXISTS documents_case ON documents (case_id);
CREATE TABLE IF NOT EXISTS chunks (
    id           bigserial PRIMARY KEY,
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    text         text NOT NULL,
    page_start   integer,
    page_end     integer,
    headings     text[] NOT NULL DEFAULT '{{}}',
    embedding    vector({dim}) NOT NULL,
    origin       text NOT NULL DEFAULT 'chunker',
    tsv          tsvector,
    place        text,  -- a spreadsheet passage's cells, e.g. 'Prices!A2:D31' (formats.py); NULL for everything else
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS chunks_document_id ON chunks (document_id);
-- No vector index: answers rank every chunk of the documents exactly (``best_chunks``); keeping an HNSW index
-- up to date made storing a document some hundred times slower (2,500 chunks: 51 s against 0.4 s).
CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING gin (tsv);
"""


def without(content: dict, document_id: str) -> dict:
    """A saved answer's content without a deleted document's passages and file name, as the chat UI cleans a
    conversation (``withoutDocument``): the citation keeps its page and is marked ``removed``; the answer stays."""
    out = dict(content)
    out["citations"] = [
        {"text": "", "source": {"document_id": document_id, "page": (c.get("source") or {}).get("page"), "location": None},
         "removed": True}
        if isinstance(c, dict) and (c.get("source") or {}).get("document_id") == document_id else c
        for c in content.get("citations") or []]
    if isinstance(content.get("filenames"), dict):
        out["filenames"] = {k: v for k, v in content["filenames"].items() if k != document_id}
    return out


# A source for answers (cases.md decision 7): uploaded, and not sūveryn's own export coming back
# unless a person chose to use it anyway (docs/design/chat-ui.md §6). Constants only, no input.
SOURCE = ("d.origin = 'uploaded' AND NOT (coalesce(d.provenance, '{}') ? 'noticed'"
          " AND NOT coalesce(d.provenance, '{}') ? 'confirmed')")


@dataclass(frozen=True)
class Scope:
    """Whose documents a request may see: one user's personal space (``owner``, no case), or one case
    (``case_id``; the gateway has checked the user may read it). ``Scope(None, None)`` is the
    operator tools' scope: documents without an owner or a case."""

    owner: str | None = None
    case_id: uuid.UUID | None = None

    @classmethod
    def personal(cls, owner: str | None) -> "Scope":
        return cls(owner=owner)

    @classmethod
    def case(cls, case_id: uuid.UUID) -> "Scope":
        return cls(case_id=case_id)

    def where(self, alias: str = "") -> tuple[str, tuple]:
        """SQL that keeps the documents in this scope, and its parameters."""
        col = f"{alias}." if alias else ""
        if self.case_id is not None:
            return f"{col}case_id = %s", (self.case_id,)
        return f"{col}case_id IS NULL AND {col}owner IS NOT DISTINCT FROM %s", (self.owner,)


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
    place: str | None = None  # a spreadsheet passage's cells (formats.py)


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

    def find_by_sha256(self, sha256: str, scope: Scope) -> uuid.UUID | None:
        """Id of the document with this content hash in this scope (a personal space or a case), if it
        was ingested there before. Never one from another scope: de-duplication is per scope."""
        where, params = scope.where()
        row = self._conn.execute(f"SELECT id FROM documents WHERE sha256 = %s AND {where}", (sha256, *params)).fetchone()
        return row[0] if row else None

    def recovered_share(self, document_id: uuid.UUID) -> float:
        """Share of a document's text that came from the text-layer recovery rather than the layout model."""
        total, recovered = self._conn.execute(
            "SELECT coalesce(sum(length(text)), 0), coalesce(sum(length(text)) FILTER (WHERE origin = 'text_layer_recovered'), 0)"
            " FROM chunks WHERE document_id = %s", (document_id,)).fetchone()
        return recovered / total if total else 0.0

    def replace_document(self, document_id: uuid.UUID, filename: str, pages: int, ocr_pages: int, chunks: list[Chunk],
                         embeddings: np.ndarray, warnings: list[IntegrityWarning] | None = None) -> uuid.UUID:
        """Read again: the document keeps its id (saved conversations still point to it), its chunks, status
        and warnings are replaced, in one transaction."""
        warnings = warnings or []
        status = "needs_review" if any(w.needs_review for w in warnings) else "ok"
        with self._conn.transaction():
            self._conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            self._conn.execute(
                "UPDATE documents SET filename = %s, pages = %s, ocr_pages = %s, status = %s, warnings = %s WHERE id = %s",
                (filename, pages, ocr_pages, status,
                 json.dumps([{"page": w.page, "kind": w.kind, "detail": w.detail} for w in warnings]), document_id))
            self._insert_chunks(document_id, chunks, embeddings)
        return document_id

    def add_document(self, filename: str, sha256: str, pages: int, ocr_pages: int, chunks: list[Chunk],
                     embeddings: np.ndarray, warnings: list[IntegrityWarning] | None = None,
                     owner: str | None = None, case_id: uuid.UUID | None = None, origin: str = "uploaded",
                     provenance: dict | None = None, content: dict | None = None) -> uuid.UUID:
        """Store a document and its chunks in one transaction (all or nothing), uploaded by ``owner``
        into the case ``case_id`` (or their personal space), with its ``origin``.

        Status is ``needs_review`` if any warning means text may be missing; recovered or
        restored text alone keeps it ``ok``. The file name is stored too and may itself be
        personal data (e.g. a client's name).
        """
        warnings = warnings or []
        status = "needs_review" if any(w.needs_review for w in warnings) else "ok"
        with self._conn.transaction():
            doc_id = self._conn.execute(
                "INSERT INTO documents (filename, sha256, pages, ocr_pages, status, warnings, owner, case_id, origin,"
                " provenance, content) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (filename, sha256, pages, ocr_pages, status,
                 json.dumps([{"page": w.page, "kind": w.kind, "detail": w.detail} for w in warnings]), owner, case_id,
                 origin, json.dumps(provenance) if provenance else None,
                 json.dumps(content) if content is not None else None)).fetchone()[0]
            self._insert_chunks(doc_id, chunks, embeddings)
        return doc_id

    def _insert_chunks(self, doc_id: uuid.UUID, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, text, page_start, page_end, headings, origin,"
                " embedding, tsv, place) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, to_tsvector('simple', %s), %s)",
                [(doc_id, c.index, c.text, c.page_start, c.page_end, c.headings, c.origin, e,
                  " ".join([c.text, *c.headings, c.place or ""]), c.place)
                 for c, e in zip(chunks, embeddings, strict=True)])

    def list_documents(self, scope: Scope) -> list[dict]:
        """The scope's documents, newest first: id, file name, pages, OCR'd pages, status, warnings,
        created, origin, who uploaded it. Not the number of chunks: nothing showed it, and counting them
        on every listing (polled while uploads are read) cost 0.4 s for 1,000 documents."""
        where, params = scope.where("d")
        rows = self._conn.execute(
            "SELECT d.id, d.filename, d.pages, d.ocr_pages, d.status, d.warnings, d.created_at,"
            "       d.origin, d.owner, d.provenance,"
            f"       ({SOURCE})"
            f"  FROM documents d WHERE {where} ORDER BY d.created_at DESC", params).fetchall()
        keys = ("id", "filename", "pages", "ocr_pages", "status", "warnings", "created_at", "origin", "uploaded_by",
                "provenance", "source")
        return [dict(zip(keys, r)) for r in rows]

    def list_documents_many(self, owner: str, case_ids: list[uuid.UUID]) -> list[dict]:
        """The owner's personal documents and every document of the cases given (the sidebar's
        "Documents", docs/design/chat-ui.md), newest first, with ``case_id``."""
        rows = self._conn.execute(
            "SELECT d.id, d.filename, d.pages, d.ocr_pages, d.status, d.warnings, d.created_at,"
            "       d.origin, d.owner, d.case_id, d.provenance,"
            f"       ({SOURCE})"
            "  FROM documents d WHERE (d.case_id IS NULL AND d.owner IS NOT DISTINCT FROM %s) OR d.case_id = ANY(%s)"
            " ORDER BY d.created_at DESC LIMIT 1000", (owner, case_ids)).fetchall()
        keys = ("id", "filename", "pages", "ocr_pages", "status", "warnings", "created_at", "origin", "uploaded_by", "case_id",
                "provenance", "source")
        return [dict(zip(keys, r)) for r in rows]

    def document_status(self, document_id: uuid.UUID) -> tuple[str, list[dict]] | None:
        """(status, warnings) of a stored document, or None if it doesn't exist."""
        row = self._conn.execute("SELECT status, warnings FROM documents WHERE id = %s", (document_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def in_scope(self, document_ids: list[uuid.UUID], scope: Scope, sources_only: bool = False) -> set[uuid.UUID]:
        """Which of these documents are in ``scope`` (the others don't exist or are elsewhere). With
        ``sources_only``, only sources count (``SOURCE``): never sūveryn's own output as a source."""
        where, params = scope.where("d")
        only = f" AND ({SOURCE})" if sources_only else ""
        rows = self._conn.execute(f"SELECT d.id FROM documents d WHERE d.id = ANY(%s) AND {where}{only}",
                                  (list(document_ids), *params)).fetchall()
        return {r[0] for r in rows}

    def confirm_source(self, document_id: uuid.UUID, scope: Scope, by: str) -> dict | None:
        """A person chose to use a noticed upload as a source anyway: record who and when; the mark
        that was noticed, or None if the document isn't in ``scope`` or wasn't noticed. Idempotent."""
        where, params = scope.where()
        row = self._conn.execute(
            "UPDATE documents SET provenance = provenance || jsonb_build_object('confirmed',"
            "       jsonb_build_object('by', %s::text, 'at', now()))"
            f" WHERE id = %s AND {where} AND provenance ? 'noticed' RETURNING provenance -> 'noticed'",
            (by, document_id, *params)).fetchone()
        return row[0] if row else None

    def withdraw(self, document_id: uuid.UUID, scope: Scope, by: str, reason: str = "") -> bool:
        """A playbook's result whose run was cancelled (docs/design/playbooks.md): the document stays,
        marked ``withdrawn`` in its provenance (who, when, why), never deleted. Only sūveryn's own
        output can be withdrawn, never an upload. Idempotent; False if there is no such document."""
        where, params = scope.where()
        return self._conn.execute(
            "UPDATE documents SET provenance = coalesce(provenance, '{}') || jsonb_build_object('withdrawn',"
            "       jsonb_build_object('by', %s::text, 'at', now(), 'reason', %s::text))"
            f" WHERE id = %s AND {where} AND origin <> 'uploaded'",
            (by, reason, document_id, *params)).rowcount == 1

    def saved_answer(self, scope: Scope, message: str) -> tuple[uuid.UUID, str] | None:
        """(id, file name) of the answer ``message`` already saved in the scope (docs/design/chat-ui.md §5), or None."""
        where, params = scope.where()
        row = self._conn.execute(f"SELECT id, filename FROM documents WHERE origin = 'answer' AND {where}"
                                 " AND provenance->>'message' = %s ORDER BY created_at LIMIT 1", (*params, message)).fetchone()
        return (row[0], row[1]) if row else None

    def content(self, document_id: uuid.UUID, scope: Scope) -> tuple[str, str, dict] | None:
        """(file name, origin, content) of a document in the scope that sūveryn made with content, or None."""
        where, params = scope.where()
        row = self._conn.execute(f"SELECT filename, origin, content FROM documents WHERE id = %s AND {where}"
                                 " AND content IS NOT NULL", (document_id, *params)).fetchone()
        return (row[0], row[1], row[2]) if row else None

    def delete_document(self, document_id: uuid.UUID, scope: Scope | None = None) -> bool:
        """Delete a document (only one in ``scope`` when given); its chunks go with it (ON DELETE CASCADE).
        Saved answers in the same scope that cite it lose its passages and its file name (``without``),
        in the same transaction, as saved conversations do (suveryn-tracker#12).

        Review note: this makes the text unreachable, not unrecoverable. PostgreSQL keeps dead
        rows in the table files until VACUUM rewrites them, and changes stay in the write-ahead
        log (the WAL) until it lets them go. The gateway (and ``suveryn-forget``) flush the WAL a few
        seconds after a deletion (``journal.flush_journal``; VM regression 03c8f74, finding 3), so
        that window is seconds rather than hours on the appliance. Backups keep the text until they
        roll over. Secure deletion (encryption at rest, crypto-shredding or a scheduled VACUUM FULL)
        is an open item (docs/architecture.md §6).
        """
        if scope is None:  # operator tools (suveryn-forget)
            where, params = "true", ()
        else:
            where, params = scope.where()
        with self._conn.transaction():
            gone = self._conn.execute(f"DELETE FROM documents WHERE id = %s AND {where} RETURNING case_id, owner",
                                      (document_id, *params)).fetchone()
            if gone is None:
                return False
            # the answers saved where it was (the same case, or the same personal space)
            near = Scope.case(gone[0]) if gone[0] is not None else Scope.personal(gone[1])
            near_where, near_params = near.where()
            for other, content in self._conn.execute(
                    f"SELECT id, content FROM documents WHERE content IS NOT NULL AND {near_where}"
                    " AND content::text LIKE %s", (*near_params, f"%{document_id}%")).fetchall():
                self._conn.execute("UPDATE documents SET content = %s WHERE id = %s",
                                   (json.dumps(without(content, str(document_id))), other))
        return True

    def delete_scope(self, scope: Scope) -> int:
        """Delete every document in a scope (a case being deleted), chunks with them; how many."""
        where, params = scope.where()
        return self._conn.execute(f"DELETE FROM documents WHERE {where}", params).rowcount

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

    def best_chunks(self, query: np.ndarray, question: str, document_ids: list[uuid.UUID], max_chars: int,
                    max_chunks: int, min_chunks: int) -> list[StoredChunk]:
        """The documents' best-matching chunks that fit the limits, in reading order.

        For documents too large to give whole: instead of a handful of search hits, the model gets
        as much of the documents as the whole-document budget allows, chosen by relevance.

        Every chunk of the documents is ranked exactly (no cut-off and no vector index, so nothing
        approximate): by vector similarity and by keyword match, fused by reciprocal rank (``RRF_K``).
        Chunks are then taken best first while they fit ``max_chars`` and ``max_chunks``; the best
        ``min_chunks`` are always taken. The result is returned in reading order (as ``document_chunks``),
        with the fused score kept on each chunk.

        Review note: the f-string interpolates constants only; query, documents and terms are
        bound parameters. Every chunk's distance is computed (there is no vector index). Both rankings come
        from one scan of the documents' chunks (window functions), so the time grows with the number
        of chunks, not with its square, whatever plan PostgreSQL picks.
        """
        tsq = self._keyword_query(question, document_ids)
        # Both rankings in one pass over the documents' chunks, by window functions: no join for the
        # planner to get wrong. Looking each chunk up in the rankings by a subquery made this grow with
        # the square of the chunks, 6 minutes for a case of 6,500 (VM check of adccf00); a join can do
        # the same when the statistics are stale, as right after an upload. Only the ranking comes back
        # here, and the text only for the chunks chosen.
        keyword = "c.tsv @@ to_tsquery('simple', %(tsq)s)" if tsq else "false"
        rank = "ts_rank_cd(c.tsv, to_tsquery('simple', %(tsq)s))" if tsq else "0"
        ranked = self._conn.execute(f"""
            SELECT id, length, distance, document_id,
                   CASE WHEN vector THEN row_number() OVER (PARTITION BY vector ORDER BY distance, id) END,
                   CASE WHEN keyword THEN row_number() OVER (PARTITION BY keyword ORDER BY rank DESC, id) END
              FROM (SELECT c.id, c.document_id, length(c.text) AS length, c.embedding <=> %(q)s AS distance,
                           c.text ~ %(min_words)s AS vector, {keyword} AS keyword, {rank} AS rank
                      FROM chunks c WHERE c.document_id = ANY(%(docs)s)) AS c""",
            {"q": query, "docs": document_ids, "tsq": tsq, "min_words": MIN_WORDS_FOR_VECTOR}).fetchall()
        scored = sorted(((cid, length, (1.0 / (RRF_K + vr) if vr else 0.0) + (1.0 / (RRF_K + kr) if kr else 0.0),
                          1.0 - float(distance)) for cid, length, distance, _doc, vr, kr in ranked),
                        key=lambda r: (-r[2], -r[3]))
        chosen, size = {}, 0
        # Every document's closest passage by meaning first, the closest documents first, up to a third of the
        # passages: a French deed among Dutch ones matches a Dutch question by meaning but by none of its words,
        # and the fused ranking left it out altogether (VM regression 03c8f74, finding 2).
        if len(document_ids) > 1:
            best: dict = {}
            for cid, length, distance, doc, vr, _kr in ranked:
                if vr and (doc not in best or distance < best[doc][2]):
                    best[doc] = (cid, length, distance)
            score_of = {r[0]: r[2] for r in scored}
            for cid, length, distance in sorted(best.values(), key=lambda b: b[2])[:max(1, max_chunks // 3)]:
                if size + length <= max_chars or not chosen:
                    chosen[cid] = (float(score_of[cid]), 1.0 - float(distance))
                    size += length
        for chunk_id, length, score, similarity in scored:
            if len(chosen) >= max_chunks:
                break
            if chunk_id in chosen:
                continue
            if len(chosen) >= min_chunks and size + length > max_chars:
                continue  # a smaller, lower-ranked chunk may still fit
            chosen[chunk_id] = (float(score), float(similarity))
            size += length
        rows = self._conn.execute(
            "SELECT c.id, c.document_id, d.filename, c.chunk_index, c.text, c.page_start, c.page_end, c.headings,"
            "       c.origin, c.place"
            "  FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(%s)",
            (list(chosen),)).fetchall()
        order = {d: i for i, d in enumerate(document_ids)}
        rows.sort(key=lambda r: (order[r[1]], r[5] if r[5] is not None else 1 << 30, r[3]))
        return [StoredChunk(r[1], r[2], r[3], r[4], r[5], r[6], list(r[7] or []), r[8], *chosen[r[0]], r[9]) for r in rows]

    def document_samples(self, document_ids: list[uuid.UUID], chars: int = 3000) -> dict[str, tuple[str, str]]:
        """Each document's file name and the start of its text (its first passages, up to ``chars``): enough to
        tell its kind and language (``naming``)."""
        rows = self._conn.execute(
            "SELECT d.id, d.filename, coalesce((SELECT string_agg(x.text, ' ') FROM (SELECT c.text FROM chunks c"
            "  WHERE c.document_id = d.id ORDER BY c.page_start NULLS LAST, c.chunk_index LIMIT 4) x), '')"
            "  FROM documents d WHERE d.id = ANY(%s)", (document_ids,)).fetchall()
        return {str(r[0]): (r[1], r[2][:chars]) for r in rows}

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
            "SELECT c.document_id, d.filename, c.chunk_index, c.text, c.page_start, c.page_end, c.headings, c.origin,"
            "       c.place"
            "  FROM chunks c JOIN documents d ON d.id = c.document_id"
            " WHERE c.document_id = ANY(%(docs)s)"
            " ORDER BY array_position(%(docs)s, c.document_id), c.page_start NULLS LAST, c.chunk_index",
            {"docs": document_ids}).fetchall()
        return [StoredChunk(r[0], r[1], r[2], r[3], r[4], r[5], list(r[6] or []), r[7], 0.0, 0.0, r[8]) for r in rows]
