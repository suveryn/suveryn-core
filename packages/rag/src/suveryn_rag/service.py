"""Document service for the HTTP API: an upload queue, one ingestion worker, listing and search.

Why a queue with a single worker: ingestion uses the GPU heavily and redirects the process-wide
TMPDIR (see ``workspace``), and the benchmark showed heavy jobs must be queued, not run side by
side. Uploads are accepted immediately and processed one at a time in a background thread; the
client polls the job.

Two ``Rag`` instances share one embedding model: one owned by the worker (with a PDF reader
process that runs Docling and the OCR, see ``isolation``), one for search and listing (no reader),
each with its own database connection. Search calls are
serialised with a lock (one connection); they take milliseconds.

Confidentiality: an uploaded file is written only to ``<work_dir>/uploads`` (0700) under a random
name and deleted as soon as its job ends, successfully or not. Files left behind by a crash or power
loss (uploads, and ``doc-*`` OCR work folders) are deleted when the service starts. File names are
kept in memory (jobs, for ``JOB_RETENTION_S`` after they finish) and in the database (documents);
they can be personal data.

Ownership: every upload, job and document is uploaded by one user (the Keycloak user id the
gateway passes as ``owner``) into one scope: their personal space, or a case (``case_id``; the
gateway has checked they may contribute to it, see its ``cases``). Listing, deletion and retrieval
take the ``Scope`` the caller may see (``suveryn_rag.store.Scope``) and only ever see that scope's
documents; a document elsewhere is answered exactly like a missing one. Job status is the
uploader's. De-duplication by content hash is per scope too, so uploading a file someone else
stored in their own space creates your own copy instead of handing you theirs.

Database connections are reopened once after a connection error (e.g. PostgreSQL restarted); if
that fails too, ``SearchUnavailable`` is raised, which the gateway reports as 503.
"""

import logging
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
from .formats import SUFFIX, kind_of, looks_like
from .store import Scope

log = logging.getLogger("suveryn.rag")

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # a 300 dpi 60-page scan is ~60 MB
# Documents waiting or being read, per user and in all: one user can't hold up everyone's documents or
# fill the disk with uploads (security review 2026-10-11). An upload over either is refused with 429.
MAX_QUEUED_PER_OWNER = 20
MAX_QUEUED = 200
# While the database is unreachable the worker waits and tries again, longest wait last; the
# document waits too, and is read once the database is back (at most MAX_DB_RETRIES times).
RECONNECT_DELAYS_S = (1, 2, 5, 10, 30)
MAX_DB_RETRIES = 3
WAITING = ("receiving", "queued", "processing")  # counted against the queue limits
JOB_RETENTION_S = 3600  # finished jobs (and their file names) are forgotten after an hour


# What an upload may be (formats.py); said when anything else is uploaded.
ACCEPTED = "PDF, Word (.docx), Excel (.xlsx), Markdown (.md) and CSV files"
LABELS = {"pdf": "PDF", "docx": "Word", "xlsx": "Excel", "md": "Markdown", "csv": "CSV"}


class UploadRejected(ValueError):
    """The upload is not a file type sūveryn reads, is empty, or is too large. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class DocumentNotFound(LookupError):
    """A requested document doesn't exist or belongs to another user (deliberately the same answer)."""


class SearchUnavailable(RuntimeError):
    """The database can't be reached, even after reconnecting."""


@dataclass
class Job:
    """One uploaded document on its way into the store. Holds no document text.

    ``owner`` is the uploader (Keycloak user id); it is not part of ``public()``. ``case_id`` is the
    case it goes into, or None for the uploader's personal space.
    """

    id: str
    filename: str
    owner: str
    case_id: uuid.UUID | None = None
    status: str = "queued"  # receiving | queued | processing | ready | needs_review | failed
    document_id: str | None = None
    error: str | None = None
    pages: int | None = None
    ocr_pages: int | None = None
    warnings: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    db_retries: int = 0     # how often the database was unreachable while reading it
    noticed: dict | None = None  # the file carries sūveryn's export mark (marks.py): not a source until confirmed

    finished_at: float | None = None

    def public(self) -> dict:
        """The job as JSON for the API (no document text; the file name may be personal data)."""
        out = asdict(self)
        out.pop("owner")
        out.pop("db_retries")
        out["case_id"] = str(self.case_id) if self.case_id else None
        return out


def job_status(document_status: str) -> str:
    """Job status for a stored document: "ready", or "needs_review" when text may be missing."""
    return "needs_review" if document_status == "needs_review" else "ready"


class DocumentService:
    """Owns the ingestion worker and the search connection. ``start()`` loads the models in the background."""

    def __init__(self, settings: RagSettings):
        self.settings = settings
        self._state = "starting"  # starting | ready | failed
        self.error: str | None = None
        self._worker: threading.Thread | None = None
        self._queue: Queue[tuple[Job, Path]] = Queue()
        self._jobs: dict[str, Job] = {}
        self._jobs_lock = threading.Lock()
        self._search_lock = threading.Lock()
        self._search = None
        self._ingest = None
        # Uploads wait in the gateway's private folder. With an inbox (sandboxed reader, see
        # RagSettings.extract_inbox) only the document being read is put there, group-readable: the
        # reader never sees the other users' waiting documents.
        self._inbox = settings.extract_inbox
        self._uploads = settings.work_dir / "uploads"

    @property
    def state(self) -> str:
        """starting | ready | failed. A worker thread that stopped is never "ready" (/health must say so)."""
        if self._state == "ready" and self._worker is not None and not self._worker.is_alive():
            return "failed"
        return self._state

    @state.setter
    def state(self, value: str) -> None:
        self._state = value

    def start(self) -> None:
        """Delete leftovers of an earlier crash, then load the models and run the worker in a background thread."""
        self._remove_leftovers()
        self._worker = threading.Thread(target=self._run, name="suveryn-ingest", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        try:
            from .embed import Embedder
            from .pipeline import Rag

            embedder = Embedder(self.settings.embedding_model, self.settings.device)
            self._ingest = Rag(self.settings, embedder=embedder)
            self._search = Rag(self.settings, load_extractor=False, embedder=embedder)
            self.state = "ready"
        except Exception as e:  # noqa: BLE001 - reported through state, not raised in a thread
            # The message can name hosts and users (a database URL): in the server log only, the kind for others.
            log.error("document handling failed to start: %s: %s", type(e).__name__, str(e)[:200])
            self.state, self.error = "failed", type(e).__name__
            return
        self._work()

    def _work(self) -> None:
        """Read queued documents one at a time, for as long as the process runs. Nothing escapes this
        loop: a document that fails is marked failed, and an unreachable database is waited for
        (suveryn-core review 2026-10-13: a failed reconnect used to end the worker silently)."""
        while True:
            job, path = self._queue.get()
            try:
                self._process(job, path)
            except Exception as e:  # noqa: BLE001 - last resort: the worker must outlive any one document
                log.error("document worker: unexpected %s", type(e).__name__)
                job.status, job.error, job.finished_at = "failed", type(e).__name__, time.time()
                self._discard(path)

    def _process(self, job: Job, path: Path) -> None:
        job.status = "processing"
        try:
            staged = self._stage(job, path)
            r = self._ingest.ingest(staged, filename=job.filename, owner=job.owner, case_id=job.case_id)  # the file on disk has a random name
            # The document's status is "ok" or "needs_review"; the job's is "ready" or "needs_review".
            job.document_id, job.status = str(r.document_id), job_status(r.status)
            job.pages, job.ocr_pages, job.warnings = r.pages, r.ocr_pages, r.warnings
            job.noticed = r.noticed
        except Exception as e:  # noqa: BLE001 - a failed document must not stop the worker
            if _is_connection_error(e) and job.db_retries < MAX_DB_RETRIES:
                # Not the document's fault: wait for the database, then read it again.
                job.db_retries += 1
                self._wait_for_database()
                job.status = "queued"
                self._queue.put((job, path))
                return
            job.status, job.error = "failed", f"{type(e).__name__}: {str(e)[:200]}"
        job.finished_at = time.time()
        self._discard(path)

    def _discard(self, path: Path) -> None:
        path.unlink(missing_ok=True)
        if self._inbox is not None:
            (self._inbox / path.name).unlink(missing_ok=True)

    def _wait_for_database(self) -> None:
        """Reconnect until the database answers. Meanwhile document handling reports "failed" (and
        /health with it), and is "ready" again as soon as it is back. Waiting documents stay queued."""
        attempt = 0
        while True:
            try:
                self._ingest.store.reconnect()
            except Exception as e:  # noqa: BLE001 - any failure to reconnect means: wait and try again
                if self._state == "ready":
                    log.error("document database unreachable (%s); waiting for it", type(e).__name__)
                self._state, self.error = "failed", "the document database can't be reached"
                time.sleep(RECONNECT_DELAYS_S[min(attempt, len(RECONNECT_DELAYS_S) - 1)])
                attempt += 1
                continue
            if self._state == "failed":
                log.info("document database reachable again")
            self._state, self.error = "ready", None
            return

    def _stage(self, job: Job, path: Path) -> Path:
        """The file the reader reads: the private upload, or a group-readable copy in the inbox."""
        if self._inbox is None:
            return path
        self._check_inbox()
        staged = self._inbox / path.name
        with open(os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640), "wb") as out, open(path, "rb") as src:
            shutil.copyfileobj(src, out)
        return staged

    def _remove_uploads(self) -> None:
        """Delete every waiting upload, and the provisioned inbox's files (not the inbox itself)."""
        shutil.rmtree(self._uploads, ignore_errors=True)
        if self._inbox is not None:
            for suffix in set(SUFFIX.values()):  # uploads only: other files in the inbox aren't ours
                for leftover in self._inbox.glob(f"*{suffix}"):
                    leftover.unlink(missing_ok=True)

    def _prepare_uploads(self) -> None:
        self._uploads.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._uploads, 0o700)
        if self._inbox is not None:
            self._check_inbox()

    def _check_inbox(self) -> None:
        if not self._inbox.is_dir():  # provisioned, not created here: its group must be the reader's
            raise UploadRejected("the upload inbox doesn't exist; provision it (owner the gateway, group the reader, 2750)", 503)
        if self._inbox.stat().st_mode & 0o007:
            raise UploadRejected("the upload inbox is readable by other users; fix its permissions (2750)", 503)

    def _remove_leftovers(self) -> None:
        """Uploads and OCR work folders left by a process that didn't shut down cleanly."""
        self._remove_uploads()
        for leftover in self.settings.work_dir.glob("doc-*"):
            shutil.rmtree(leftover, ignore_errors=True)

    # ------------------------------------------------------------------ uploads and jobs
    def accept_upload(self, src: BinaryIO, filename: str, owner: str, case_id: uuid.UUID | None = None) -> Job:
        """Store an uploaded file privately and queue it, uploaded by ``owner`` into the case ``case_id``
        (or their personal space). A PDF, Word, Excel, Markdown or CSV file, by its extension, and its
        first bytes must fit (``formats.looks_like``); the reader checks the rest. Raises ``UploadRejected``."""
        kind = kind_of(filename or "document.pdf")
        if kind is None:
            raise UploadRejected(f"only {ACCEPTED} can be added", 415)
        self._prepare_uploads()
        job = Job(id=uuid.uuid4().hex, filename=Path(filename or "document.pdf").name[:200], owner=owner,
                  case_id=case_id, status="receiving")
        # Check and reserve in one step, before the file is copied: simultaneous uploads can't all pass
        # the same check (suveryn-core review 2026-10-13). The reservation counts as waiting.
        with self._jobs_lock:
            self._prune()
            waiting = [j for j in self._jobs.values() if j.status in WAITING]
            if len(waiting) >= MAX_QUEUED or sum(j.owner == owner for j in waiting) >= MAX_QUEUED_PER_OWNER:
                raise UploadRejected("too many documents are waiting to be read; try again when some are done", 429)
            self._jobs[job.id] = job
        path = self._uploads / f"{job.id}{SUFFIX[kind]}"  # the reader goes by the extension
        size = 0
        try:
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                head = src.read(8)
                if not head:
                    raise UploadRejected("the file is empty", 415)
                if not looks_like(kind, head):
                    raise UploadRejected(f"the file is not a valid {LABELS[kind]} file", 415)
                out.write(head)
                size = len(head)
                while block := src.read(1 << 20):
                    size += len(block)
                    if size > MAX_UPLOAD_BYTES:
                        raise UploadRejected(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB", 413)
                    out.write(block)
        except BaseException:
            path.unlink(missing_ok=True)
            with self._jobs_lock:
                self._jobs.pop(job.id, None)  # release the reservation
            raise
        job.status = "queued"
        self._queue.put((job, path))
        return job

    def _prune(self) -> None:
        """Forget jobs that finished more than ``JOB_RETENTION_S`` ago. Call with ``_jobs_lock`` held."""
        cutoff = time.time() - JOB_RETENTION_S
        for job_id in [j.id for j in self._jobs.values() if j.finished_at and j.finished_at < cutoff]:
            del self._jobs[job_id]

    def job(self, job_id: str, owner: str) -> Job | None:
        """The owner's job by id, or None if unknown, someone else's, or already forgotten."""
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            return job if job is not None and job.owner == owner else None

    def pending_jobs(self, owner: str, scope: Scope | None = None) -> list[Job]:
        """The owner's jobs not yet in the store: queued, processing, or failed (not one still being
        received). With a ``scope``, only those going into it (the personal space or one case)."""
        with self._jobs_lock:
            self._prune()
            return [j for j in self._jobs.values()
                    if j.owner == owner and j.status in ("queued", "processing", "failed")
                    and (scope is None or j.case_id == scope.case_id)]

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

    def documents(self, scope: Scope) -> list[dict]:
        """The scope's stored documents (no text): id, file name, pages, status, warnings, chunks,
        created, origin, who uploaded it."""
        return self._with_search(lambda rag: rag.store.list_documents(scope))

    def documents_many(self, owner: str, case_ids: list[uuid.UUID]) -> list[dict]:
        """The owner's personal documents and those of the cases given, with ``case_id`` (no text)."""
        return self._with_search(lambda rag: rag.store.list_documents_many(owner, case_ids))

    def store_text(self, filename: str, text: str, scope: Scope, origin: str, provenance: dict | None = None,
                   content: dict | None = None, by: str | None = None) -> str:
        """Store text sūveryn produced (a playbook's result, a saved answer) as a document in the scope, with
        its origin, provenance and content (what rebuilds its file); its id. ``by`` is who stored it, when a
        person did. Never a source for answers (``Rag.store_text``)."""
        return str(self._with_search(lambda rag: rag.store_text(filename, text, by or scope.owner, scope.case_id, origin,
                                                                 provenance, content)))

    def saved_answer(self, scope: Scope, message: str) -> tuple[str, str] | None:
        """(id, file name) of the answer ``message`` already saved in the scope, or None."""
        found = self._with_search(lambda rag: rag.store.saved_answer(scope, message))
        return (str(found[0]), found[1]) if found else None

    def content(self, document_id: str, scope: Scope) -> tuple[str, str, dict] | None:
        """(file name, origin, content) of a document sūveryn made, in the scope, or None."""
        return self._with_search(lambda rag: rag.store.content(uuid.UUID(document_id), scope))

    def confirm_source(self, document_id: str, scope: Scope, by: str) -> dict | None:
        """Use a noticed upload as a source anyway (docs/design/sidebar.md §6); the mark, or None."""
        return self._with_search(lambda rag: rag.store.confirm_source(uuid.UUID(document_id), scope, by))

    def delete(self, document_id: str, scope: Scope) -> bool:
        """Delete a document in the scope and its passages; False if it doesn't exist or is elsewhere."""
        return self._with_search(lambda rag: rag.store.delete_document(uuid.UUID(document_id), scope))

    def delete_all(self, scope: Scope) -> int:
        """Delete every document in the scope (a case being deleted); how many."""
        return self._with_search(lambda rag: rag.store.delete_scope(scope))

    def existing(self, document_ids: list[str], scope: Scope) -> set[str]:
        """Which of these ids are documents in ``scope`` that still exist."""
        ids = [uuid.UUID(d) for d in document_ids]
        return {str(i) for i in self._with_search(lambda rag: rag.store.in_scope(ids, scope))} if ids else set()

    def in_scope(self, document_ids: list[str], scope: Scope, sources_only: bool = False) -> bool:
        """True if every one of these documents exists in ``scope`` (and, with ``sources_only``, was
        uploaded: sūveryn's own output is never a source for an answer)."""
        ids = [uuid.UUID(d) for d in document_ids]
        return self._with_search(lambda rag: rag.store.in_scope(ids, scope, sources_only)) == set(ids)

    def retrieve(self, question: str, document_ids: list[str], k: int,
                 scope: Scope) -> tuple[list[tuple[Citation, str]], bool]:
        """Passages to answer from, as (citation, file name), and whether they are the complete documents.

        Only uploaded documents in ``scope``: if any id is elsewhere (or doesn't exist, or is
        sūveryn's own output), ``DocumentNotFound`` is raised before anything is read, so another
        scope's text never reaches the prompt. Small documents are given whole; larger ones give
        the ``k`` best search hits (``Rag.passages``).
        """
        ids = [uuid.UUID(d) for d in document_ids]

        def scoped_passages(rag):
            if rag.store.in_scope(ids, scope, sources_only=True) != set(ids):
                raise DocumentNotFound("unknown document")
            return rag.passages(question, ids, k)

        hits, complete = self._with_search(scoped_passages)
        return [(h.citation, h.filename) for h in hits], complete

    def stop(self) -> None:
        """Remove queued uploads that were never processed (on shutdown)."""
        self._remove_uploads()


def _is_connection_error(e: Exception) -> bool:
    """True for a lost or refused database connection (psycopg ``OperationalError``/``InterfaceError``)."""
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(e, (psycopg.OperationalError, psycopg.InterfaceError))
