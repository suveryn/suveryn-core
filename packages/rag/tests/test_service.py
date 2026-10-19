"""DocumentService's worker and queue under failure (suveryn-core review 2026-10-13): a database that
stays down while the worker reconnects, a worker thread that dies, and uploads arriving at once.
Fake ingestion and database; no models or PostgreSQL needed."""

import io
import threading
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("psycopg")
import psycopg  # noqa: E402

from suveryn_rag import service  # noqa: E402
from suveryn_rag.config import RagSettings  # noqa: E402
from suveryn_rag.service import DocumentService, UploadRejected  # noqa: E402


class FakeStore:
    def __init__(self, failing_reconnects: int):
        self.failing_reconnects, self.reconnects = failing_reconnects, 0

    def reconnect(self):
        self.reconnects += 1
        if self.reconnects <= self.failing_reconnects:
            raise psycopg.OperationalError("connection refused")


class FakeIngest:
    """Fails with a lost connection for the first ``down`` documents, then reads them."""

    def __init__(self, down: int, failing_reconnects: int):
        self.down, self.store, self.calls = down, FakeStore(failing_reconnects), 0

    def ingest(self, path, filename, owner, case_id=None):
        self.calls += 1
        if self.calls <= self.down:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return type("R", (), {"document_id": uuid.uuid4(), "status": "ok", "pages": 1, "ocr_pages": 0, "warnings": [], "noticed": None})()


def running(tmp_path: Path, ingest) -> DocumentService:
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    docs._ingest, docs.state = ingest, "ready"
    docs._worker = threading.Thread(target=docs._work, daemon=True)
    docs._worker.start()
    return docs


def wait(condition, seconds: float = 5.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_database_that_stays_down_while_reconnecting_doesnt_stop_the_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RECONNECT_DELAYS_S", (0.05,))
    ingest = FakeIngest(down=1, failing_reconnects=3)  # the reconnect itself fails three times
    docs = running(tmp_path, ingest)
    job = docs.accept_upload(io.BytesIO(b"%PDF-1.7 a"), "a.pdf", "user-a")
    assert wait(lambda: docs.state == "failed")  # /health says so while the database is down
    assert docs.error == "the document database can't be reached"
    assert wait(lambda: docs.job(job.id, "user-a").status == "ready")  # read once it is back, not failed
    assert docs.state == "ready" and docs.error is None and ingest.store.reconnects == 4
    later = docs.accept_upload(io.BytesIO(b"%PDF-1.7 b"), "b.pdf", "user-a")
    assert wait(lambda: docs.job(later.id, "user-a").status == "ready")  # the worker is still there


def test_a_document_that_keeps_meeting_a_lost_connection_fails_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RECONNECT_DELAYS_S", (0.01,))
    docs = running(tmp_path, FakeIngest(down=10**6, failing_reconnects=0))
    job = docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "a.pdf", "user-a")
    assert wait(lambda: docs.job(job.id, "user-a").status == "failed")
    assert job.db_retries == service.MAX_DB_RETRIES and "OperationalError" in job.error
    assert "db_retries" not in job.public()


def test_a_worker_that_stopped_is_not_reported_ready(tmp_path):
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    docs.state = "ready"
    docs._worker = threading.Thread(target=lambda: None)
    docs._worker.start()
    docs._worker.join()
    assert docs.state == "failed"


class SlowUpload(io.RawIOBase):
    """A PDF arriving slowly, so uploads overlap while their files are copied."""

    def __init__(self):
        self.parts = [b"%PDF-", b"1.7"] + [b"x" * 1024] * 20

    def read(self, n=-1):
        time.sleep(0.005)
        return self.parts.pop(0) if self.parts else b""


def test_simultaneous_uploads_cant_exceed_the_queue_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MAX_QUEUED_PER_OWNER", 3)
    monkeypatch.setattr(service, "MAX_QUEUED", 5)
    docs = DocumentService(RagSettings(work_dir=tmp_path))  # no worker: everything stays queued
    results: list[str] = []
    lock = threading.Lock()

    def upload(owner):
        try:
            docs.accept_upload(SlowUpload(), "a.pdf", owner)
            outcome = owner
        except UploadRejected as e:
            outcome = f"refused {e.status}"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=upload, args=(owner,)) for owner in ["user-a"] * 10 + ["user-b"] * 10]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("user-a") == 3 and results.count("user-b") == 2  # per owner 3; 5 in all
    assert results.count("refused 429") == 15
    assert len(list((tmp_path / "uploads").glob("*.pdf"))) == 5  # no refused upload left a file


def test_a_failed_upload_releases_its_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MAX_QUEUED_PER_OWNER", 1)
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    with pytest.raises(UploadRejected):
        docs.accept_upload(io.BytesIO(b"not a pdf"), "a.pdf", "user-a")
    docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "a.pdf", "user-a")  # the slot is free again
