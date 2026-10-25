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
    """Pod check of cbccd38: the first upload after a PostgreSQL restart always failed with FileExistsError,
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


# ------------------------------------------------------------------ archives (.zip)
import unicodedata
import zipfile

from suveryn_rag.service import FairQueue, Job


def zipped(entries: dict, method=zipfile.ZIP_DEFLATED) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    buf.seek(0)
    return buf


def uploads(tmp_path: Path) -> list[str]:
    return sorted(p.suffix for p in (tmp_path / "uploads").iterdir())


def test_each_document_in_a_zip_becomes_a_job_named_after_its_file(tmp_path):
    docs = DocumentService(RagSettings(work_dir=tmp_path))  # no worker: everything stays queued
    a = docs.accept_archive(zipped({
        "Prospectus/Project Sky FR.docx": b"PK\x03\x04 word", "Prospectus/Book17.xlsx": b"PK\x03\x04 excel",
        "deed.pdf": b"%PDF-1.7", "notes.md": b"# Notes\n", "Prospectus/": b"",
        "__MACOSX/Prospectus/._Book17.xlsx": b"junk", ".DS_Store": b"junk", "Thumbs.db": b"junk",
        "old.doc": b"\xd0\xcf\x11\xe0", "inner.zip": b"PK\x05\x06", "empty.csv": b"", "renamed.pdf": b"PK\x03\x04",
    }), "Prospectus.zip", "user-a")
    assert a.filename == "Prospectus.zip"
    assert sorted(j.filename for j in a.jobs) == ["Book17.xlsx", "Project Sky FR.docx", "deed.pdf", "notes.md"]
    assert all(j.status == "queued" and j.owner == "user-a" and j.archive == "Prospectus.zip" for j in a.jobs)
    assert a.skipped == [{"name": "empty.csv", "reason": "empty"}, {"name": "inner.zip", "reason": "archive"},
                         {"name": "old.doc", "reason": "unsupported"}, {"name": "renamed.pdf", "reason": "invalid"}]
    assert uploads(tmp_path) == [".zip"]  # nothing unpacked yet: each entry waits in the archive
    assert len(docs.pending_jobs("user-a")) == 4
    assert a.public()["jobs"][0]["archive"] == "Prospectus.zip"
    assert {"owner", "upload"}.isdisjoint(a.public()["jobs"][0])


@pytest.mark.parametrize("data, says, status", [
    (b"", "empty", 415),
    (b"%PDF-1.7", "not a valid ZIP archive", 415),
    (b"PK\x03\x04 truncated", "not a valid ZIP archive", 415),
    (zipped({"folder/": b"", "__MACOSX/._x": b"junk"}).getvalue(), "the archive is empty", 415),
])
def test_an_archive_that_cant_be_used_adds_nothing_and_leaves_nothing(tmp_path, data, says, status):
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    with pytest.raises(UploadRejected, match=says) as e:
        docs.accept_archive(io.BytesIO(data), "a.zip", "user-a")
    assert e.value.status == status
    assert not list((tmp_path / "uploads").iterdir())
    assert not docs.pending_jobs("user-a")


def test_an_archive_with_nothing_to_read_says_why_for_each_file(tmp_path, monkeypatch):
    # The VM check of adccf00: one 400 MB entry was refused as "holds no PDF, Word…", which said nothing.
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 1024 * 1024)
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    a = docs.accept_archive(zipped({"scan.pdf": b"%PDF-1.7" + b"\0" * (2 * 1024 * 1024), "photo.jpg": b"\xff\xd8"}),
                            "a.zip", "user-a")
    assert a.jobs == []
    assert a.skipped == [{"name": "photo.jpg", "reason": "unsupported"}, {"name": "scan.pdf", "reason": "too_large"}]
    assert not list((tmp_path / "uploads").iterdir()) and not docs.pending_jobs("user-a")


def test_an_archive_counts_as_one_upload_however_many_documents_it_holds(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MAX_QUEUED_PER_OWNER", 3)
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "x.pdf", "user-a")
    a = docs.accept_archive(zipped({f"{n:02}.pdf": b"%PDF-1.7" for n in range(60)}), "data room.zip", "user-a")
    assert len(a.jobs) == 60  # a data room of 60 files: one upload
    assert len(docs.pending_jobs("user-a")) == 61
    docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "y.pdf", "user-a")  # the third upload
    with pytest.raises(UploadRejected) as e:
        docs.accept_archive(zipped({"a.pdf": b"%PDF-1.7"}), "more.zip", "user-a")
    assert e.value.status == 429
    assert uploads(tmp_path) == [".pdf", ".pdf", ".zip"]  # the refused archive left nothing
    docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "z.pdf", "user-b")  # someone else's limit is their own


def test_the_queue_takes_uploaders_in_turns():
    q = FairQueue()
    job = lambda owner, name: (Job(id=name, filename=name, owner=owner), Path(name))
    for n in range(4):
        q.put(job("anne", f"room-{n}"))
    q.put(job("bert", "deed"))
    q.put(job("carl", "letter"))
    q.put(job("bert", "deed-2"))
    order = [q.get()[0].id for _ in range(len(q))]
    assert order == ["room-0", "deed", "letter", "room-1", "deed-2", "room-2", "room-3"]
    q.put(job("anne", "a"))
    q.put(job("anne", "retry"), first=True)  # a document read again after a lost connection goes first
    assert [q.get()[0].id, q.get()[0].id] == ["retry", "a"]


def test_an_uploader_whose_queue_was_empty_for_a_moment_doesnt_jump_a_colleague():
    """VM check 2: Alice's scans arrive one by one, so her queue is empty while her first is read. Her
    second, arriving before Bob's deed, must not put her ahead of him again: Bob is next."""
    q = FairQueue()
    job = lambda owner, name: (Job(id=name, filename=name, owner=owner), Path(name))
    q.put(job("alice", "scan-00"))
    assert q.get()[0].id == "scan-00"       # being read; Alice's queue is empty now
    q.put(job("alice", "scan-01"))
    q.put(job("bob", "deed"))
    q.put(job("alice", "scan-02"))
    assert [q.get()[0].id for _ in range(3)] == ["deed", "scan-01", "scan-02"]


def test_someone_who_comes_later_is_next_but_gets_no_run_of_turns():
    q = FairQueue()
    job = lambda owner, name: (Job(id=name, filename=name, owner=owner), Path(name))
    for n in range(5):
        q.put(job("anne", f"room-{n}"))
    assert [q.get()[0].id for _ in range(3)] == ["room-0", "room-1", "room-2"]
    q.put(job("bert", "deed"))
    q.put(job("bert", "deed-2"))
    assert [q.get()[0].id for _ in range(len(q))] == ["deed", "room-3", "deed-2", "room-4"]


def test_an_archive_is_unpacked_one_document_at_a_time_and_then_deleted(tmp_path):
    seen: list[list[str]] = []

    class Reading:
        store = FakeStore(0)

        def ingest(self, path, filename, owner, case_id=None, watch=None):
            seen.append(uploads(tmp_path))
            assert Path(path).read_bytes().startswith(b"%PDF-1.7 " + filename.encode())
            return type("R", (), {"document_id": uuid.uuid4(), "status": "ok", "pages": 1, "ocr_pages": 0, "warnings": [], "noticed": None})()

    docs = DocumentService(RagSettings(work_dir=tmp_path))
    a = docs.accept_archive(zipped({f"{n}.pdf": b"%PDF-1.7 " + f"{n}.pdf".encode() for n in "abc"}), "a.zip", "user-a")
    docs.cancel(a.jobs[1].id, "user-a")
    docs._ingest, docs.state = Reading(), "ready"
    docs._worker = threading.Thread(target=docs._work, daemon=True)
    docs._worker.start()
    assert wait(lambda: a.jobs[2].status == "ready")
    assert [j.status for j in a.jobs] == ["ready", "cancelled", "ready"]
    # While the first is read: the archive and that one document. The second was cancelled, which lets go
    # of its entry; once the last is unpacked the archive is no longer needed and is gone.
    assert seen == [[".pdf", ".zip"], [".pdf"]]
    assert wait(lambda: not list((tmp_path / "uploads").iterdir()))


def test_a_mac_file_name_is_stored_in_one_unicode_form(tmp_path):
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    mac = unicodedata.normalize("NFD", "zvlm Lucrèce.docx")
    assert docs.accept_upload(io.BytesIO(b"PK\x03\x04"), mac, "user-a").filename == "zvlm Lucrèce.docx"
    a = docs.accept_archive(zipped({unicodedata.normalize("NFD", "Akte Hélène.pdf"): b"%PDF-1.7"}), "a.zip", "user-a")
    assert a.jobs[0].filename == unicodedata.normalize("NFC", "Akte Hélène.pdf")


def test_a_zip_bomb_stops_at_the_limit_and_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MAX_ARCHIVE_UNPACKED", 4 * 1024 * 1024)
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    bomb = zipped({"a.pdf": b"%PDF-1.7" + b"\0" * (3 * 1024 * 1024), "b.pdf": b"%PDF-1.7" + b"\0" * (3 * 1024 * 1024)})
    assert len(bomb.getvalue()) < 100_000  # small packed, large unpacked
    with pytest.raises(UploadRejected, match="unpacks to more than 4 MB") as e:
        docs.accept_archive(bomb, "bomb.zip", "user-a")
    assert e.value.status == 413
    assert not list((tmp_path / "uploads").iterdir()) and not docs.pending_jobs("user-a")


def test_an_entry_larger_than_an_upload_or_damaged_is_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 1024 * 1024)
    docs = DocumentService(RagSettings(work_dir=tmp_path))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("big.pdf", b"%PDF-1.7" + b"\0" * (2 * 1024 * 1024), zipfile.ZIP_DEFLATED)
        z.writestr("ok.pdf", b"%PDF-1.7 fine")
        z.writestr("bad.pdf", b"%PDF-1.7" + b"x" * 5000)  # stored as it is, so one byte can be changed
    data = buf.getvalue()
    i = data.index(b"x" * 5000)
    data = data[:i] + b"y" + data[i + 1:]  # one byte changed: the entry's checksum no longer fits
    a = docs.accept_archive(io.BytesIO(data), "a.zip", "user-a")
    assert [j.filename for j in a.jobs] == ["ok.pdf"]
    assert a.skipped == [{"name": "bad.pdf", "reason": "damaged"}, {"name": "big.pdf", "reason": "too_large"}]
    assert uploads(tmp_path) == [".zip"]
