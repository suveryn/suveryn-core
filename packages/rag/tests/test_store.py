"""pgvector store tests against a real PostgreSQL. Skipped unless SUVERYN_TEST_DATABASE_URL is set."""

import os

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("suveryn_rag")
import numpy as np
from suveryn_rag.chunking import Chunk
from suveryn_rag.store import Store

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")
DIM = 1024


def unit(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def test_add_search_and_forget():
    store = Store(URL, DIM)
    chunks = [Chunk(i, f"text of chunk {i}", f"text of chunk {i}", i + 1, i + 1, [f"Artikel {i}"]) for i in range(3)]
    doc = store.add_document("test.pdf", f"sha-{os.getpid()}-{np.random.randint(1 << 30)}", 3, 0,
                             chunks, np.stack([unit(i) for i in range(3)]))
    try:
        hits = store.search(unit(2), k=2, document_id=doc)
        top = hits[0]
        assert top.chunk_index == 2
        assert (top.page_start, top.headings, top.origin, round(top.similarity, 3)) == (3, ["Artikel 2"], "chunker", 1.0)
        assert store.document_status(doc) == ("ok", [])
    finally:
        assert store.delete_document(doc)
        assert store.search(unit(2), k=5, document_id=doc) == []
        store.close()


def test_short_fragments_are_not_vector_hits_and_whole_documents_read_in_order():
    store = Store(URL, DIM)
    code = "1ec0f1aa36eb3d4509c9df83c285c219ffd6e77a"
    chunks = [Chunk(0, "second page text here", "", 2, 2, []),
              Chunk(1, "first page text here", "", 1, 1, []),
              Chunk(2, code, code, 1, 1, [], origin="furniture_restored")]
    doc = store.add_document("short.pdf", f"sha-{os.getpid()}-{np.random.randint(1 << 30)}", 2, 0,
                             chunks, np.stack([unit(5), unit(6), unit(7)]))
    try:
        assert [h.chunk_index for h in store.search(unit(7), k=3, document_id=doc)] != [2]  # not the top vector hit
        assert all(h.chunk_index != 2 for h in store.search(unit(7), k=3, document_id=doc, question="vraag"))
        assert [h.chunk_index for h in store.search(unit(7), k=3, document_id=doc, question=code)][0] == 2  # by keyword
        whole = store.document_chunks([doc], max_chars=10_000, max_chunks=99)
        assert [c.chunk_index for c in whole] == [1, 2, 0]  # page 1 (regular, then restored), then page 2
        assert store.document_chunks([doc], max_chars=20, max_chunks=99) is None
        assert store.document_chunks([doc], max_chars=10_000, max_chunks=2) is None
    finally:
        store.delete_document(doc)
        store.close()
