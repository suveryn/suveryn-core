"""Document service for the HTTP API: an upload queue, one ingestion worker, listing and search.

Why a queue with a single worker: ingestion uses the GPU heavily and redirects the process-wide
TMPDIR (see ``workspace``), and the benchmark showed heavy jobs must be queued, not run side by
side. Uploads are accepted immediately and processed one at a time in a background thread; the
client polls the job.

Two ``Rag`` instances share one embedding model: one owned by the worker (with Docling), one for
search and listing (no Docling), each with its own database connection. Search calls are
serialised with a lock (one connection); they take milliseconds.

Confidentiality: an uploaded file is written only to ``<work_dir>/uploads`` (0700) under a random
name and deleted as soon as its job ends, successfully or not. File names are kept in memory
(jobs) and in the database (documents); they can be personal data.
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


class UploadRejected(ValueError):
    """The upload is not a PDF, is empty, or is too large."""


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

    def public(self) -> dict:
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
            finally:
                path.unlink(missing_ok=True)

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
                    raise UploadRejected("only PDF files can be added")
                out.write(head)
                size = len(head)
                while block := src.read(1 << 20):
                    size += len(block)
                    if size > MAX_UPLOAD_BYTES:
                        raise UploadRejected(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                    out.write(block)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        with self._jobs_lock:
            self._jobs[job.id] = job
        self._queue.put((job, path))
        return job

    def job(self, job_id: str) -> Job | None:
        with self._jobs_lock:
            return self._jobs.get(job_id)

    def pending_jobs(self) -> list[Job]:
        """Jobs not yet in the store: queued, processing, or failed."""
        with self._jobs_lock:
            return [j for j in self._jobs.values() if j.status in ("queued", "processing", "failed")]

    # ------------------------------------------------------------------ stored documents and search
    def _require_ready(self):
        if self.state != "ready":
            raise RuntimeError(f"document service is {self.state}")
        return self._search

    def documents(self) -> list[dict]:
        rag = self._require_ready()
        with self._search_lock:
            return rag.store.list_documents()

    def delete(self, document_id: str) -> bool:
        rag = self._require_ready()
        with self._search_lock:
            return rag.forget(uuid.UUID(document_id))

    def retrieve(self, question: str, document_ids: list[str], k: int) -> list[tuple[Citation, str]]:
        """Best passages for the question within the given documents, as (citation, file name)."""
        rag = self._require_ready()
        ids = [uuid.UUID(d) for d in document_ids]
        with self._search_lock:
            hits = rag.retrieve(question, k=k, document_ids=ids)
        return [(h.citation, h.filename) for h in hits]

    def stop(self) -> None:
        """Remove queued uploads that were never processed (on shutdown)."""
        shutil.rmtree(self._uploads, ignore_errors=True)
