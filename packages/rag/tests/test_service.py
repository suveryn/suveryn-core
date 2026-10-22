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

    def ingest(self, path, filename, owner, case_id=None, watch=None):
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


def test_word_excel_markdown_and_csv_are_accepted_and_kept_with_their_extension(tmp_path):
    docs = DocumentService(RagSettings(work_dir=tmp_path))  # no worker: everything stays queued
    for name, head in [("deed.pdf", b"%PDF-1.7"), ("Notes.DOCX", b"PK\x03\x04rest"), ("prices.xlsx", b"PK\x03\x04rest"),
                       ("notes.md", b"# Title\n"), ("list.csv", b"name;amount\n")]:
        job = docs.accept_upload(io.BytesIO(head), name, "user-a")
        assert job.filename == name
    stored = sorted(p.suffix for p in (tmp_path / "uploads").iterdir())
    assert stored == [".csv", ".docx", ".md", ".pdf", ".xlsx"]  # the reader goes by the extension


@pytest.mark.parametrize("name, head, says", [
    ("old.doc", b"\xd0\xcf\x11\xe0", r"only PDF, Word \(\.docx\), Excel \(\.xlsx\), Markdown \(\.md\) and CSV files"),
    ("macro.xlsm", b"PK\x03\x04", "only PDF"),
    ("renamed.docx", b"%PDF-1.7", "not a valid Word file"),   # the content must fit the extension
    ("encrypted.xlsx", b"\xd0\xcf\x11\xe0", "not a valid Excel file"),  # a password-protected workbook isn't a zip
    ("binary.csv", b"ab\x00cd", "not a valid CSV file"),
    ("deed.pdf", b"PK\x03\x04", "not a valid PDF file"),
    ("empty.md", b"", "empty"),
])
def test_other_files_are_refused_and_leave_nothing_behind(tmp_path, name, head, says):
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    with pytest.raises(UploadRejected, match=says) as e:
        docs.accept_upload(io.BytesIO(head), name, "user-a")
    assert e.value.status == 415
    assert not list((tmp_path / "uploads").glob("*")) if (tmp_path / "uploads").exists() else True
    assert not docs.pending_jobs("user-a")


# ------------------------------------------------------------------ progress, cancelling, reasons (sidebar.md §5)
from suveryn_rag.reading import Progress, Unreadable


class WatchedIngest:
    """Reports a page, then waits until it is cancelled (or ``finish`` is set); or fails with ``fails``."""

    def __init__(self, fails: Exception | None = None):
        self.store, self.fails, self.started, self.finish = FakeStore(0), fails, threading.Event(), threading.Event()

    def ingest(self, path, filename, owner, case_id=None, watch=None):
        if self.fails:
            raise self.fails
        watch.report(Progress("ocr", 1, 4))
        self.started.set()
        while not self.finish.is_set():
            watch.check()
            time.sleep(0.01)
        return type("R", (), {"document_id": uuid.uuid4(), "status": "ok", "pages": 4, "ocr_pages": 1, "warnings": [], "noticed": None})()


def test_a_job_shows_how_far_reading_has_got_and_can_be_cancelled(tmp_path):
    ingest = WatchedIngest()
    docs = running(tmp_path, ingest)
    job = docs.accept_upload(io.BytesIO(b"%PDF-1.7 a"), "a.pdf", "user-a")
    assert ingest.started.wait(5)
    assert docs.job(job.id, "user-a").public()["progress"] == {"step": "ocr", "done": 1, "total": 4}
    assert docs.cancel(job.id, "user-b") is None  # someone else's
    assert docs.cancel(job.id, "user-a") is True
    assert wait(lambda: job.status == "cancelled")
    assert job.progress is None and "cancel_requested" not in job.public()
    assert job not in docs.pending_jobs("user-a")  # not a failure to show
    assert not list((tmp_path / "uploads").glob("*"))  # its file is gone


def test_a_waiting_upload_cancelled_is_never_read_and_a_finished_one_cant_be(tmp_path):
    ingest = WatchedIngest()
    docs = running(tmp_path, ingest)
    first = docs.accept_upload(io.BytesIO(b"%PDF-1.7 a"), "a.pdf", "user-a")
    waiting = docs.accept_upload(io.BytesIO(b"%PDF-1.7 b"), "b.pdf", "user-a")
    assert ingest.started.wait(5)
    assert docs.cancel(waiting.id, "user-a") is True and waiting.status == "cancelled"
    ingest.finish.set()
    assert wait(lambda: first.status == "ready")
    assert docs.cancel(first.id, "user-a") is False  # a document now: delete it instead
    time.sleep(0.1)
    assert waiting.status == "cancelled" and waiting.progress is None  # never read


def test_a_failure_carries_its_code_for_the_interface(tmp_path):
    docs = running(tmp_path, WatchedIngest(fails=Unreadable("the document has 900 pages; at most 500 can be read",
                                                            "too_many_pages", pages=900, max=500)))
    job = docs.accept_upload(io.BytesIO(b"%PDF-1.7 a"), "a.pdf", "user-a")
    assert wait(lambda: job.status == "failed")
    out = job.public()
    assert (out["error_code"], out["error_detail"]) == ("too_many_pages", {"pages": 900, "max": 500})
    assert out["error"] == "the document has 900 pages; at most 500 can be read"  # the English sentence stays for the API
    docs2 = running(tmp_path / "2", WatchedIngest(fails=RuntimeError("boom")))
    other = docs2.accept_upload(io.BytesIO(b"%PDF-1.7 a"), "a.pdf", "user-a")
    assert wait(lambda: other.status == "failed") and other.error_code == "unreadable"


def test_a_document_read_again_after_a_lost_connection_is_staged_again(tmp_path, monkeypatch):
    """Pod check of 547f48e: the first upload after a PostgreSQL restart always failed with FileExistsError,
    because the retry staged the file in the inbox again (O_EXCL) without removing the first copy."""
    monkeypatch.setattr(service, "RECONNECT_DELAYS_S", (0.01,))
    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o750)
    docs = DocumentService(RagSettings(work_dir=tmp_path / "work", extract_inbox=inbox))
    docs._ingest, docs.state = FakeIngest(down=1, failing_reconnects=0), "ready"
    docs._worker = threading.Thread(target=docs._work, daemon=True)
    docs._worker.start()
    job = docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "a.pdf", "user-a")
    assert wait(lambda: docs.job(job.id, "user-a").status in ("ready", "failed"))
    assert job.status == "ready" and job.db_retries == 1 and not job.error
    assert not list(inbox.glob("*.pdf"))  # and nothing left behind
