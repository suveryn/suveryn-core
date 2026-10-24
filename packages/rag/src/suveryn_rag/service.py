"""Document service for the HTTP API: an upload queue, one ingestion worker, listing and search.

Why a queue with a single worker: ingestion uses the GPU heavily and redirects the process-wide
TMPDIR (see ``workspace``), and the benchmark showed heavy jobs must be queued, not run side by
side. Uploads are accepted immediately and processed one at a time in a background thread; the
client polls the job. The queue takes uploaders in turns (``FairQueue``): someone who adds a data
room of sixty files doesn't make a colleague's one deed wait behind all sixty; it is read next.

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

Archives: a .zip upload (``accept_archive``) becomes one job per PDF, Word, Excel, Markdown or CSV file
inside it, each read like an upload of its own; what can't be read (another kind of file, an archive
inside the archive, an encrypted, too large, empty or damaged entry) is listed with a reason.

- **Checked at once, unpacked one by one.** On upload every entry is read through once, writing
  nothing, to check it and count the bytes it really unpacks to (a zip bomb stops at the limit). The
  archive is then kept, private, and each entry is unpacked only when its turn comes, just before
  the reader reads it; the archive is deleted once its last document is read or cancelled. So a
  data room waiting to be read takes the archive's space on disk, never all its files unpacked.
- **One upload in the limits.** An archive counts as one upload against the queue limits (20 waiting
  per user, 200 in all), however many documents it holds (at most ``MAX_ARCHIVE_ENTRIES`` entries).
  The limits are about disk and fairness; unpacking late and taking turns already cover both.
- **Unpacked here, not in the reader:** only entries' bytes are copied out, never to a path the
  archive names, and each entry then goes to the sandboxed reader like any upload. Unpacking needs
  nothing beyond zlib.

Database connections are reopened once after a connection error (e.g. PostgreSQL restarted); if
that fails too, ``SearchUnavailable`` is raised, which the gateway reports as 503.
"""

import logging
import os
import shutil
import threading
import time
import unicodedata
import uuid
import zipfile
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from zlib import error as zlib_error

from suveryn_harness import Citation

from .config import RagSettings
from .formats import SUFFIX, kind_of, looks_like
from .reading import Cancelled, Progress, Unreadable, Watch
from .store import Scope

log = logging.getLogger("suveryn.rag")

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # a 300 dpi 60-page scan is ~60 MB
# Uploads waiting or being read, per user and in all, so no one fills the disk with uploads (security
# review 2026-10-11). An upload over either is refused with 429. An archive is one upload, however many
# documents it holds: it waits as one file, unpacked one entry at a time. Nobody's documents wait behind
# someone else's many: the queue takes uploaders in turns (FairQueue).
MAX_QUEUED_PER_OWNER = 20
MAX_QUEUED = 200
# While the database is unreachable the worker waits and tries again, longest wait last; the
# document waits too, and is read once the database is back (at most MAX_DB_RETRIES times).
RECONNECT_DELAYS_S = (1, 2, 5, 10, 30)
MAX_DB_RETRIES = 3
WAITING = ("receiving", "queued", "processing")  # counted against the queue limits, an archive as one upload
JOB_RETENTION_S = 3600  # finished jobs (and their file names) are forgotten after an hour


# What an upload may be (formats.py); said when anything else is uploaded.
ACCEPTED = "PDF, Word (.docx), Excel (.xlsx), Markdown (.md) and CSV files, or a .zip of them"
# An archive: at most this many entries listed, and this much unpacked in all (each entry is also held
# to MAX_UPLOAD_BYTES). Its documents count against the queue limits like separate uploads.
MAX_ARCHIVE_ENTRIES = 1000
MAX_ARCHIVE_UNPACKED = 300 * 1024 * 1024
# Why an entry of an archive wasn't added, for the interface to say in its language.
SKIP_REASONS = ("unsupported", "archive", "encrypted", "too_large", "empty", "invalid", "damaged")
LABELS = {"pdf": "PDF", "docx": "Word", "xlsx": "Excel", "md": "Markdown", "csv": "CSV"}


class UploadRejected(ValueError):
    """The upload is not a file type sūveryn reads, is empty, or is too large. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


@dataclass
class Archive:
    """What an uploaded .zip became: a job per document in it, and the entries left out, with a reason
    (``SKIP_REASONS``). Holds names only, never content."""

    filename: str
    jobs: list["Job"]
    skipped: list[dict]

    def public(self) -> dict:
        return {"archive": self.filename, "jobs": [j.public() for j in self.jobs], "skipped": self.skipped}


@dataclass
class _ArchiveFile:
    """An uploaded archive, kept private until the last of its documents has been unpacked or cancelled."""

    path: Path
    remaining: int
    lock: threading.Lock = field(default_factory=threading.Lock)

    def done_with_one(self) -> None:
        with self.lock:
            self.remaining -= 1
            if self.remaining <= 0:
                self.path.unlink(missing_ok=True)


@dataclass
class _Entry:
    """A document still inside its archive: unpacked when its turn comes (``DocumentService._unpack_entry``)."""

    archive: _ArchiveFile
    name: str        # the entry's name in the archive, as the archive spells it
    kind: str
    released: bool = False

    def release(self) -> None:
        """This document no longer needs the archive (unpacked, or cancelled). Once per entry."""
        if not self.released:
            self.released = True
            self.archive.done_with_one()


Source = Path | _Entry  # what a queued job reads: an upload on disk, or an entry still in its archive


class FairQueue:
    """The documents waiting to be read, taken in turns per uploader: the next document comes from the
    uploader who has waited longest for a turn, and each uploader's own documents in the order they
    came. A colleague's one deed is read next, not after someone else's data room."""

    def __init__(self):
        self._by_owner: OrderedDict[str, deque] = OrderedDict()
        self._ready = threading.Condition()

    def put(self, item: tuple["Job", Source], first: bool = False) -> None:
        """Queue ``(job, source)``; ``first``: at the front of its uploader's documents (a retry)."""
        with self._ready:
            q = self._by_owner.setdefault(item[0].owner, deque())
            q.appendleft(item) if first else q.append(item)
            self._ready.notify()

    def get(self) -> tuple["Job", Source]:
        """The next document, waiting until there is one."""
        with self._ready:
            while not self._by_owner:
                self._ready.wait()
            owner, q = next(iter(self._by_owner.items()))
            item = q.popleft()
            del self._by_owner[owner]
            if q:
                self._by_owner[owner] = q  # to the back of the turn
            return item

    def __len__(self) -> int:
        with self._ready:
            return sum(len(q) for q in self._by_owner.values())


def clean_name(name: str) -> str:
    """A file name as stored and shown: its last part, in one Unicode form (NFC). A Mac writes "è" as
    "e" plus an accent (NFD); stored as it came, it wouldn't match the same name typed elsewhere."""
    return unicodedata.normalize("NFC", PurePosixPath(name.replace("\\", "/")).name)[:200]


def is_archive(filename: str | None) -> bool:
    return Path(filename or "").suffix.lower() == ".zip"


def junk(name: PurePosixPath) -> bool:
    """Entries an archiver adds that nobody chose: macOS's __MACOSX folder and dot files, Windows's Thumbs.db."""
    return any(part == "__MACOSX" or part.startswith(".") for part in name.parts) or name.name.lower() in ("thumbs.db", "desktop.ini")


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
    status: str = "queued"  # receiving | queued | processing | ready | needs_review | failed | cancelled
    document_id: str | None = None
    error: str | None = None
    pages: int | None = None
    ocr_pages: int | None = None
    warnings: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    db_retries: int = 0     # how often the database was unreachable while reading it
    noticed: dict | None = None  # the file carries sūveryn's export mark (marks.py): not a source until confirmed
    progress: Progress | None = None  # how far reading has got (reading.Progress), while processing
    error_code: str | None = None     # why it failed, for the interface to say in its language (reading.CODES)
    error_detail: dict = field(default_factory=dict)  # the numbers that message needs (pages, max, minutes)
    cancel_requested: bool = False    # the person cancelled it while it was read; the worker stops it
    archive: str | None = None        # the .zip it came from, by name, for the interface
    upload: str | None = None         # the upload it belongs to, for the queue limits (an archive's id)

    finished_at: float | None = None

    def public(self) -> dict:
        """The job as JSON for the API (no document text; the file name may be personal data)."""
        out = asdict(self)
        out.pop("owner")
        out.pop("db_retries")
        out.pop("cancel_requested")
        out.pop("upload")
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
        self._queue = FairQueue()
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
            job, source = self._queue.get()
            if job.status == "cancelled":  # cancelled while it waited: never read
                self._discard(self._path_for(job, source), source)
                continue
            try:
                self._process(job, source)
            except Exception as e:  # noqa: BLE001 - last resort: the worker must outlive any one document
                log.error("document worker: unexpected %s", type(e).__name__)
                job.status, job.error, job.finished_at = "failed", type(e).__name__, time.time()
                self._discard(self._path_for(job, source), source)

    def _path_for(self, job: Job, source: Source) -> Path:
        """Where the job's file is (or will be, for an entry still in its archive)."""
        return source if isinstance(source, Path) else self._uploads / f"{job.id}{SUFFIX[source.kind]}"

    def _process(self, job: Job, source: Source) -> None:
        job.status = "processing"
        watch = Watch(report=lambda p: setattr(job, "progress", p), cancelled=lambda: job.cancel_requested)
        path = self._path_for(job, source)
        try:
            if isinstance(source, _Entry):
                try:
                    self._unpack_entry(source, path)
                finally:
                    source.release()
            staged = self._stage(job, path)
            r = self._ingest.ingest(staged, filename=job.filename, owner=job.owner, case_id=job.case_id,  # the file on disk has a random name
                                    watch=watch)
            # The document's status is "ok" or "needs_review"; the job's is "ready" or "needs_review".
            job.document_id, job.status = str(r.document_id), job_status(r.status)
            job.pages, job.ocr_pages, job.warnings = r.pages, r.ocr_pages, r.warnings
            job.noticed = r.noticed
        except Cancelled:
            job.status = "cancelled"
        except Exception as e:  # noqa: BLE001 - a failed document must not stop the worker
            if _is_connection_error(e) and job.db_retries < MAX_DB_RETRIES:
                # Not the document's fault: wait for the database, then read it again.
                job.db_retries += 1
                self._unstage(path)  # the next try stages it again (O_EXCL): Pod check of 547f48e
                self._wait_for_database()
                job.status = "queued"
                self._queue.put((job, path), first=True)  # unpacked now: read from the file
                return
            # A reason sūveryn knows is its own sentence; anything else names the exception (for the log).
            if not isinstance(e, Unreadable):  # the type only: the message may name the file
                log.warning("document failed: %s", type(e).__name__)
            job.status, job.error = "failed", str(e)[:200] if isinstance(e, Unreadable) else f"{type(e).__name__}: {str(e)[:200]}"
            job.error_code = e.code if isinstance(e, Unreadable) else "unreadable"
            job.error_detail = e.detail if isinstance(e, Unreadable) else {}
        job.progress = None
        job.finished_at = time.time()
        self._discard(path, source)

    def _discard(self, path: Path, source: Source | None = None) -> None:
        path.unlink(missing_ok=True)
        self._unstage(path)
        if isinstance(source, _Entry):
            source.release()

    def _unpack_entry(self, entry: _Entry, path: Path) -> None:
        """Copy one checked entry out of its archive to ``path``, its bytes counted again as they come.
        Raises ``Unreadable`` if it has changed since it was checked (it can't have, but nothing is assumed)."""
        try:
            with zipfile.ZipFile(entry.archive.path) as z, z.open(entry.name) as src, \
                    open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                size = 0
                while block := src.read(1 << 20):
                    size += len(block)
                    if size > MAX_UPLOAD_BYTES:
                        raise Unreadable("the file in the archive is too large", "too_large")
                    out.write(block)
        except (OSError, KeyError, zipfile.BadZipFile, EOFError, NotImplementedError, RuntimeError, zlib_error):
            path.unlink(missing_ok=True)
            raise Unreadable("the file couldn't be unpacked from its archive", "damaged") from None

    def _unstage(self, path: Path) -> None:
        """Remove the reader's copy in the inbox, if any; the private upload stays."""
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
            # Set, not left to the umask: under umask 077 the reader's group couldn't read it, and every
            # upload failed as "damaged" (Pod check of d1f1918, the test runner started from a shell).
            os.fchmod(out.fileno(), 0o640)
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
        job = Job(id=uuid.uuid4().hex, filename=clean_name(filename or "document.pdf"), owner=owner,
                  case_id=case_id, status="receiving")
        # Check and reserve in one step, before the file is copied: simultaneous uploads can't all pass
        # the same check (suveryn-core review 2026-10-13). The reservation counts as waiting.
        with self._jobs_lock:
            self._check_room(owner)
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
        with self._jobs_lock:
            if job.status == "cancelled":  # cancelled while it was still arriving
                path.unlink(missing_ok=True)
                return job
            job.status = "queued"
        self._queue.put((job, path))
        return job

    def _check_room(self, owner: str) -> None:
        """Refuse a new upload when 20 of the owner's (or 200 in all) wait; an archive counts as one.
        Call with ``_jobs_lock`` held, and reserve before letting go of it."""
        self._prune()
        waiting = {(j.owner, j.upload or j.id) for j in self._jobs.values() if j.status in WAITING}
        if len(waiting) >= MAX_QUEUED or sum(o == owner for o, _ in waiting) >= MAX_QUEUED_PER_OWNER:
            raise UploadRejected("too many documents are waiting to be read; try again when some are done", 429)

    def accept_archive(self, src: BinaryIO, filename: str, owner: str, case_id: uuid.UUID | None = None) -> Archive:
        """A .zip upload: each PDF, Word, Excel, Markdown or CSV file inside becomes a job of its own, named
        after the file (its folders in the archive left out), queued in turn; the rest is listed in
        ``skipped`` with a reason. Every entry is checked now; each is unpacked only when it is read (see
        the module's notes). Raises ``UploadRejected`` when the archive itself can't be used, is empty, or
        no upload may wait now; then nothing is added."""
        name = clean_name(filename or "archive.zip")
        self._prepare_uploads()
        upload = uuid.uuid4().hex
        path = self._uploads / f"{upload}.zip"
        keep = False
        try:
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                head = src.read(4)
                if not head:
                    raise UploadRejected("the file is empty", 415)
                if head not in (b"PK\x03\x04", b"PK\x05\x06"):
                    raise UploadRejected("the file is not a valid ZIP archive", 415)
                out.write(head)
                size = len(head)
                while block := src.read(1 << 20):
                    size += len(block)
                    if size > MAX_UPLOAD_BYTES:
                        raise UploadRejected(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB", 413)
                    out.write(block)
            try:
                with zipfile.ZipFile(path) as z:
                    entries = z.infolist()
                    if len(entries) > MAX_ARCHIVE_ENTRIES:
                        raise UploadRejected(f"the archive holds more than {MAX_ARCHIVE_ENTRIES} files", 415)
                    wanted, skipped = self._sort_entries(entries)
                    if not wanted and not skipped:
                        raise UploadRejected("the archive is empty", 415)
                    good, unpacked = [], 0
                    for entry, kind in wanted:
                        reason, size = self._check_entry(z, entry, kind, MAX_ARCHIVE_UNPACKED - unpacked)
                        unpacked += size
                        if reason == "limit":
                            raise UploadRejected(f"the archive unpacks to more than {MAX_ARCHIVE_UNPACKED // (1024 * 1024)} MB", 413)
                        if reason:
                            skipped.append({"name": clean_name(entry.filename), "reason": reason})
                        else:
                            good.append((entry, kind))
            except zipfile.BadZipFile:
                raise UploadRejected("the file is not a valid ZIP archive", 415) from None
            skipped.sort(key=lambda e: e["name"].lower())
            if not good:  # nothing to read: say why for each file, and keep nothing
                return Archive(filename=name, jobs=[], skipped=skipped)
            kept = _ArchiveFile(path=path, remaining=len(good))
            jobs = [(Job(id=uuid.uuid4().hex, filename=clean_name(e.filename), owner=owner, case_id=case_id,
                         status="queued", archive=name, upload=upload), _Entry(kept, e.filename, kind)) for e, kind in good]
            with self._jobs_lock:
                self._check_room(owner)
                for job, _ in jobs:
                    self._jobs[job.id] = job
            keep = True
        finally:
            if not keep:
                path.unlink(missing_ok=True)
        for item in jobs:
            self._queue.put(item)
        return Archive(filename=name, jobs=[j for j, _ in jobs], skipped=skipped)

    @staticmethod
    def _sort_entries(entries: list[zipfile.ZipInfo]) -> tuple[list[tuple[zipfile.ZipInfo, str]], list[dict]]:
        """The entries to read, with their kind, and those left out with a reason; folders and junk are ignored.
        An entry larger than an upload by what the archive says is left out unread ("too_large")."""
        wanted, skipped = [], []
        for e in entries:
            name = PurePosixPath(e.filename.replace("\\", "/"))
            if e.is_dir() or not name.name or junk(name):
                continue
            kind = kind_of(name.name)
            reason = ("archive" if is_archive(name.name) else "unsupported" if kind is None
                      else "encrypted" if e.flag_bits & 0x1 else "too_large" if e.file_size > MAX_UPLOAD_BYTES
                      else "empty" if e.file_size == 0 else None)
            if reason:
                skipped.append({"name": clean_name(e.filename), "reason": reason})
            else:
                wanted.append((e, kind))
        return wanted, skipped

    @staticmethod
    def _check_entry(z: zipfile.ZipFile, entry: zipfile.ZipInfo, kind: str, room: int) -> tuple[str | None, int]:
        """Read one entry through, writing nothing: whether its first bytes fit its kind, its checksum holds,
        and how many bytes it really unpacks to (not what the archive says). Returns (the reason it can't be
        used, or None; bytes read). "limit": the archive's total would pass ``room``."""
        size = 0
        try:
            with z.open(entry) as src:
                head = src.read(8)
                if not head:
                    return "empty", 0
                if not looks_like(kind, head):
                    return "invalid", 0
                size = len(head)
                while block := src.read(1 << 20):
                    size += len(block)
                    if size > room:
                        return "limit", size
                    if size > MAX_UPLOAD_BYTES:
                        return "too_large", size
        except (zipfile.BadZipFile, EOFError, NotImplementedError, RuntimeError, zlib_error):
            return "damaged", size  # a bad CRC, a truncated entry, a compression method zipfile doesn't know
        return None, size

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

    def cancel(self, job_id: str, owner: str) -> bool | None:
        """Cancel the owner's upload: one still arriving or waiting is never read; one being read is
        stopped (the reader with it) before it is stored, but one already being stored finishes and is
        a document like any other. True if cancelled or asked to stop, False if it has finished (it is a
        document now: delete that instead), None if unknown or someone else's."""
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None or job.owner != owner:
                return None
            if job.status == "cancelled":
                return True
            if job.status in ("receiving", "queued"):
                job.status, job.finished_at = "cancelled", time.time()
                return True
            if job.status == "processing":
                job.cancel_requested = True
                return True
            return False

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
