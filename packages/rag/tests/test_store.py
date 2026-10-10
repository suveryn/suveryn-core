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


def test_documents_are_isolated_per_owner():
    """suveryn-tracker#3: listing, ownership, deletion and de-duplication are per owner."""
    store = Store(URL, DIM)
    sha = f"sha-{os.getpid()}-{np.random.randint(1 << 30)}"
    alice, bob = f"alice-{sha}", f"bob-{sha}"
    chunk = [Chunk(0, "text of the deed", "text of the deed", 1, 1, [])]
    a = store.add_document("akte.pdf", sha, 1, 0, chunk, np.stack([unit(1)]), owner=alice)
    legacy = store.add_document("old.pdf", sha + "-legacy", 1, 0, chunk, np.stack([unit(2)]))  # no owner
    try:
        assert [d["id"] for d in store.list_documents(alice)] == [a]
        assert store.list_documents(bob) == []
        assert store.owned([a], alice) == {a} and store.owned([a], bob) == set()
        assert store.owned([legacy], alice) == set()  # documents without an owner are nobody's
        # the same file is de-duplicated per owner only: Bob never gets Alice's document back
        assert store.find_by_sha256(sha, alice) == a and store.find_by_sha256(sha, bob) is None
        b = store.add_document("akte.pdf", sha, 1, 0, chunk, np.stack([unit(1)]), owner=bob)
        assert b != a and store.owned([b], bob) == {b}
        assert not store.delete_document(a, bob)  # someone else's
        assert store.owned([a], alice) == {a}
        assert store.delete_document(b, bob)
    finally:
        store.delete_document(a)
        store.delete_document(legacy)
        store.close()


def test_best_chunks_fill_the_budget_by_relevance_in_reading_order():
    """Large documents: as many best-matching chunks as fit, not a handful of search hits."""
    store = Store(URL, DIM)
    n = 150  # more than CANDIDATES per ranking and than the 99-chunk cap
    # Chunk i is on page i + 1 and points ever further from unit(0), so its vector rank is i.
    vecs = []
    for i in range(n):
        v = unit(0) * (n - i) + unit(1 + i % 500) * i
        vecs.append(v / np.linalg.norm(v))
    chunks = [Chunk(i, f"passage number {i} of the deed " + "x" * 80, "", i + 1, i + 1, []) for i in range(n)]
    chunks[140] = Chunk(140, "erfdienstbaarheid van uitweg " + "x" * 80, "", 141, 141, [])  # found only by keyword
    doc = store.add_document("large.pdf", f"sha-{os.getpid()}-{np.random.randint(1 << 30)}", n, 0, chunks, np.stack(vecs))
    try:
        size = len(chunks[0].text)
        best = store.best_chunks(unit(0), "erfdienstbaarheid", [doc], max_chars=40 * size, max_chunks=99, min_chunks=6)
        pages = [c.page_start for c in best]
        assert sum(len(c.text) for c in best) <= 40 * size and len(best) >= 38, "the character budget decides how many"
        assert pages == sorted(pages), "reading order"
        assert 141 in pages, "the keyword match is included"
        assert set(range(1, 30)) <= set(pages), "the best vector matches are included"
        assert len(store.best_chunks(unit(0), "vraag", [doc], max_chars=10**9, max_chunks=99, min_chunks=6)) == 99
        assert len(store.best_chunks(unit(0), "vraag", [doc], max_chars=1, max_chunks=99, min_chunks=6)) == 6
    finally:
        store.delete_document(doc)
        store.close()
