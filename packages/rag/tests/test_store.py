"""pgvector store tests against a real PostgreSQL. Skipped unless SUVERYN_TEST_DATABASE_URL is set."""

import os

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("suveryn_rag")
import numpy as np  # noqa: E402
from suveryn_rag.chunking import Chunk  # noqa: E402
from suveryn_rag.store import Store  # noqa: E402

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")
DIM = 1024


def unit(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def test_add_search_and_forget():
    store = Store(URL, DIM)
    chunks = [Chunk(i, f"chunk {i}", f"chunk {i}", i + 1, i + 1, [f"Artikel {i}"]) for i in range(3)]
    doc = store.add_document("test.pdf", f"sha-{os.getpid()}-{np.random.randint(1 << 30)}", 3, 0,
                             chunks, np.stack([unit(i) for i in range(3)]))
    try:
        hits = store.search(unit(2), k=2, document_id=doc)
        top = hits[0]
        assert top.chunk_index == 2
        assert (top.page_start, top.headings, round(top.score, 3)) == (3, ["Artikel 2"], 1.0)
    finally:
        assert store.delete_document(doc)
        assert store.search(unit(2), k=5, document_id=doc) == []
        store.close()
