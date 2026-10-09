"""Document service for the HTTP API: an upload queue, one ingestion worker, listing and search.

Why a queue with a single worker: ingestion uses the GPU heavily and redirects the process-wide
TMPDIR (see ``workspace``), and the benchmark showed heavy jobs must be queued, not run side by
side. Uploads are accepted immediately and processed one at a time in a background thread; the
client polls the job.

Two ``Rag`` instances share one embedding model: one owned by the worker (with Docling), one for
search and listing (no Docling), each with its own database connection. Search calls are
serialised with a lock (one connection); they take milliseconds.

Confidentiality: an uploaded file is written only to ``<work_dir>/uploads`` (0700) under a random
name and deleted as soon as its job ends, successfully or not. Files left behind by a crash or power
loss (uploads, and ``doc-*`` OCR work folders) are deleted when the service starts. File names are
kept in memory (jobs, for ``JOB_RETENTION_S`` after they finish) and in the database (documents);
they can be personal data.

Database connections are reopened once after a connection error (e.g. PostgreSQL restarted); if
that fails too, ``SearchUnavailable`` is raised, which the gateway reports as 503.
"""

import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from queue import Queue
from typing import BinaryIO

from suveryn_engine import Citation

from .config import RagSettings

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # a 300 dpi 60-page scan is ~60 MB
JOB_RETENTION_S = 3600  # finished jobs (and their file names) are forgotten after an hour


class UploadRejected(ValueError):
    """The upload is not a PDF, is empty, or is too large. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class SearchUnavailable(RuntimeError):
    """The database can't be reached, even after reconnecting."""


@dataclass
class Job:
    """One uploaded document on its way into the store. Holds no document text."""

    id: str
    filename: str
    status: str = "queued"  # queued | processing | ready | needs_review | failed
    document_id: str | None = None
    error: str | None = None
    pages: int | None = None
    ocr_pages: int | None = None
    warnings: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    finished_at: float | None = None

    def public(self) -> dict:
        """The job as JSON for the API (no document text; the file name may be personal data)."""
        return asdict(self)


def job_status(document_status: str) -> str:
    """Job status for a stored document: "ready", or "needs_review" when text may be missing."""
    return "needs_review" if document_status == "needs_review" else "ready"


class DocumentService:
    """Owns the ingestion worker and the search connection. ``start()`` loads the models in the background."""

    def __init__(self, settings: RagSettings):
        self.settings = settings
        self.state = "starting"  # starting | ready | failed
        self.error: str | None = None
        self._queue: Queue[tuple[Job, Path]] = Queue()
        self._jobs: dict[str, Job] = {}
        self._jobs_lock = threading.Lock()
        self._search_lock = threading.Lock()
        self._search = None
        self._ingest = None
        self._uploads = settings.work_dir / "uploads"

    def start(self) -> None:
        """Delete leftovers of an earlier crash, then load the models and run the worker in a background thread."""
        self._remove_leftovers()
        threading.Thread(target=self._run, name="suveryn-ingest", daemon=True).start()

    def _run(self) -> None:
        try:
            from .embed import Embedder
            from .pipeline import Rag

            embedder = Embedder(self.settings.embedding_model, self.settings.device)
            self._ingest = Rag(self.settings, embedder=embedder)
            self._search = Rag(self.settings, load_extractor=False, embedder=embedder)
            self.state = "ready"
        except Exception as e:  # noqa: BLE001 - reported through state, not raised in a thread
            self.state, self.error = "failed", f"{type(e).__name__}: {str(e)[:200]}"
            return
        while True:
            job, path = self._queue.get()
            job.status = "processing"
            try:
                r = self._ingest.ingest(path, filename=job.filename)  # the file on disk has a random name
                # The document's status is "ok" or "needs_review"; the job's is "ready" or "needs_review".
                job.document_id, job.status = str(r.document_id), job_status(r.status)
                job.pages, job.ocr_pages, job.warnings = r.pages, r.ocr_pages, r.warnings
            except Exception as e:  # noqa: BLE001 - a failed document must not stop the worker
                job.status, job.error = "failed", f"{type(e).__name__}: {str(e)[:200]}"
                if _is_connection_error(e):
                    self._ingest.store.reconnect()  # so the next job doesn't fail the same way
            finally:
                job.finished_at = time.time()
                path.unlink(missing_ok=True)

    def _remove_leftovers(self) -> None:
        """Uploads and OCR work folders left by a process that didn't shut down cleanly."""
        shutil.rmtree(self._uploads, ignore_errors=True)
        for leftover in self.settings.work_dir.glob("doc-*"):
            shutil.rmtree(leftover, ignore_errors=True)

    # ------------------------------------------------------------------ uploads and jobs
    def accept_upload(self, src: BinaryIO, filename: str) -> Job:
        """Store an uploaded PDF privately and queue it. Raises ``UploadRejected``."""
        self._uploads.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._uploads, 0o700)
        job = Job(id=uuid.uuid4().hex, filename=Path(filename or "document.pdf").name[:200])
        path = self._uploads / f"{job.id}.pdf"
        size = 0
        try:
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                head = src.read(5)
                if head != b"%PDF-":
                    raise UploadRejected("only PDF files can be added", 415)
                out.write(head)
                size = len(head)
                while block := src.read(1 << 20):
                    size += len(block)
                    if size > MAX_UPLOAD_BYTES:
                        raise UploadRejected(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB", 413)
                    out.write(block)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        with self._jobs_lock:
            self._prune()
            self._jobs[job.id] = job
        self._queue.put((job, path))
        return job

    def _prune(self) -> None:
        """Forget jobs that finished more than ``JOB_RETENTION_S`` ago. Call with ``_jobs_lock`` held."""
        cutoff = time.time() - JOB_RETENTION_S
        for job_id in [j.id for j in self._jobs.values() if j.finished_at and j.finished_at < cutoff]:
            del self._jobs[job_id]

    def job(self, job_id: str) -> Job | None:
        """A job by id, or None if unknown or already forgotten."""
        with self._jobs_lock:
            return self._jobs.get(job_id)

    def pending_jobs(self) -> list[Job]:
        """Jobs not yet in the store: queued, processing, or failed."""
        with self._jobs_lock:
            self._prune()
            return [j for j in self._jobs.values() if j.status in ("queued", "processing", "failed")]

    # ------------------------------------------------------------------ stored documents and search
    def _require_ready(self):
        if self.state != "ready":
            raise RuntimeError(f"document service is {self.state}")
        return self._search

    def _with_search(self, call):
        """Run ``call(rag)`` under the search lock; reconnect once after a connection error."""
        rag = self._require_ready()
        with self._search_lock:
            try:
                return call(rag)
            except Exception as e:
                if not _is_connection_error(e):
                    raise
                try:
                    rag.store.reconnect()
                    return call(rag)
                except Exception as again:
                    if _is_connection_error(again):
                        raise SearchUnavailable("the document database can't be reached") from again
                    raise

    def documents(self) -> list[dict]:
        """Every stored document (no text): id, file name, pages, status, warnings, chunks, created."""
        return self._with_search(lambda rag: rag.store.list_documents())

    def delete(self, document_id: str) -> bool:
        """Delete a stored document and its passages; False if it doesn't exist."""
        return self._with_search(lambda rag: rag.forget(uuid.UUID(document_id)))

    def retrieve(self, question: str, document_ids: list[str], k: int) -> tuple[list[tuple[Citation, str]], bool]:
        """Passages to answer from, as (citation, file name), and whether they are the complete documents.

        Small documents are given whole; larger ones give the ``k`` best search hits (``Rag.passages``).
        """
        ids = [uuid.UUID(d) for d in document_ids]
        hits, complete = self._with_search(lambda rag: rag.passages(question, ids, k))
        return [(h.citation, h.filename) for h in hits], complete

    def stop(self) -> None:
        """Remove queued uploads that were never processed (on shutdown)."""
        shutil.rmtree(self._uploads, ignore_errors=True)


def _is_connection_error(e: Exception) -> bool:
    """True for a lost or refused database connection (psycopg ``OperationalError``/``InterfaceError``)."""
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(e, (psycopg.OperationalError, psycopg.InterfaceError))
