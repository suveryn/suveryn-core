"""What the document service lets reach an answer, and how it rides out a lost database connection.

``retrieve`` is the one road from stored documents to a prompt: every id must be an uploaded document in the
asker's scope, or nothing is read at all. ``_with_search`` reconnects once after a lost connection. Both are
covered by the model tests on CI as a side effect; these say it on purpose, with a fake store, no models and
no PostgreSQL (audit of 4 November 2026: the reader's package had the least coverage).
"""

import uuid

import pytest

pytest.importorskip("psycopg")
import psycopg  # noqa: E402

from suveryn_rag.config import RagSettings  # noqa: E402
from suveryn_rag.service import DocumentNotFound, DocumentService, SearchUnavailable  # noqa: E402
from suveryn_rag.store import Scope  # noqa: E402

FR, NL = str(uuid.uuid4()), str(uuid.uuid4())
SAMPLES = {
    FR: ("46. Power of Attorney (FR) - final execution version.pdf", "Le soussigné donne procuration à la société pour"),
    NL: ("Volmacht Algemene Vergadering.pdf", "De ondergetekende geeft volmacht aan de voorzitter van de vergadering om"),
}


class Hit:
    def __init__(self, doc: uuid.UUID):
        self.citation, self.filename = f"citation of {doc}", SAMPLES.get(str(doc), ("file.pdf",))[0]


class FakeStore:
    """The documents a scope holds, and how a query fares: ``fail`` lists what each next call raises."""

    def __init__(self, held: set[str], uploaded: set[str] | None = None, fail: list[Exception] | None = None):
        self.held, self.uploaded, self.fail = held, uploaded if uploaded is not None else held, list(fail or [])
        self.reconnects, self.asked = 0, []

    def _maybe_fail(self):
        if self.fail:
            raise self.fail.pop(0)

    def in_scope(self, ids, scope, sources_only=False):
        self._maybe_fail()
        self.asked.append(("in_scope", sources_only))
        pool = self.uploaded if sources_only else self.held
        return {i for i in ids if str(i) in pool}

    def document_samples(self, ids):
        return {str(i): SAMPLES[str(i)] for i in ids if str(i) in SAMPLES}

    def list_documents(self, scope):
        self._maybe_fail()
        return [{"id": d} for d in sorted(self.held)]

    def reconnect(self):
        self.reconnects += 1


class FakeRag:
    def __init__(self, store: FakeStore):
        self.store, self.read = store, []

    def passages(self, question, ids, k):
        self.read.append(sorted(str(i) for i in ids))
        return [Hit(i) for i in ids], True


def service_with(store: FakeStore, tmp_path) -> tuple[DocumentService, FakeRag]:
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    rag = FakeRag(store)
    docs._search, docs.state = rag, "ready"
    return docs, rag


MINE = Scope.personal("user-a")
LOST = psycopg.OperationalError("server closed the connection unexpectedly")


def test_one_document_from_elsewhere_and_nothing_is_read(tmp_path):
    docs, rag = service_with(FakeStore(held={FR}), tmp_path)
    with pytest.raises(DocumentNotFound):
        docs.retrieve("Wat is de prijs?", [FR, NL], 5, MINE)    # NL is another scope's, or gone
    assert rag.read == []                                        # not even FR's passages were fetched


def test_suveryns_own_output_is_never_a_source(tmp_path):
    summary = str(uuid.uuid4())
    store = FakeStore(held={FR, summary}, uploaded={FR})
    docs, rag = service_with(store, tmp_path)
    with pytest.raises(DocumentNotFound):
        docs.retrieve("Wat staat erin?", [summary], 5, MINE)
    assert store.asked == [("in_scope", True)] and rag.read == []
    assert docs.in_scope([summary], MINE) is True                 # it exists in the scope ...
    assert docs.in_scope([summary], MINE, sources_only=True) is False  # ... but isn't a source


def test_a_question_naming_one_document_reads_only_that_one(tmp_path):
    docs, rag = service_with(FakeStore(held={FR, NL}), tmp_path)
    passages, complete, narrowed = docs.retrieve("Wie geeft de Franstalige volmacht, en aan wie?", [FR, NL], 5, MINE)
    assert rag.read == [[FR]] and narrowed == SAMPLES[FR][0] and complete is True
    assert [name for _, name in passages] == [SAMPLES[FR][0]]
    rag.read.clear()
    _, _, narrowed = docs.retrieve("Wie geeft een volmacht?", [FR, NL], 5, MINE)  # both fit: both are read
    assert rag.read == [sorted([FR, NL])] and narrowed is None


def test_existing_with_no_ids_asks_nothing(tmp_path):
    store = FakeStore(held={FR})
    docs, _ = service_with(store, tmp_path)
    assert docs.existing([], MINE) == set() and store.asked == []
    assert docs.existing([FR, NL], MINE) == {FR}


def test_a_lost_connection_is_reconnected_once_and_the_query_asked_again(tmp_path):
    store = FakeStore(held={FR}, fail=[LOST])
    docs, _ = service_with(store, tmp_path)
    assert docs.documents(MINE) == [{"id": FR}] and store.reconnects == 1


def test_a_connection_still_lost_after_reconnecting_says_the_database_cant_be_reached(tmp_path):
    store = FakeStore(held={FR}, fail=[LOST, LOST])
    docs, _ = service_with(store, tmp_path)
    with pytest.raises(SearchUnavailable, match="can't be reached"):
        docs.documents(MINE)
    assert store.reconnects == 1                                  # once, not in a loop


def test_any_other_failure_is_raised_as_it_is_without_reconnecting(tmp_path):
    store = FakeStore(held={FR}, fail=[ValueError("a bug, not the network")])
    docs, _ = service_with(store, tmp_path)
    with pytest.raises(ValueError, match="a bug"):
        docs.documents(MINE)
    assert store.reconnects == 0
    store.fail = [LOST, ValueError("after reconnecting")]         # a different failure on the second try
    with pytest.raises(ValueError, match="after reconnecting"):
        docs.documents(MINE)


def test_nothing_is_searched_before_the_service_is_ready(tmp_path):
    docs, rag = service_with(FakeStore(held={FR}), tmp_path)
    docs.state = "starting"
    with pytest.raises(RuntimeError, match="starting"):
        docs.retrieve("Wat is de prijs?", [FR], 5, MINE)
    assert rag.read == []
