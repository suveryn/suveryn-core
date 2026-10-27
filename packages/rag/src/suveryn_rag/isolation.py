"""Reading uploaded files in a separate process, away from the gateway's secrets (suveryn-tracker#15).

Why: an uploaded file is untrusted input. Reading a PDF runs large native parsers: pypdfium2,
qpdf (pikepdf), Ghostscript and Tesseract (through OCRmyPDF) and Docling. Ghostscript in
particular has a history of memory-safety flaws. Until the 2026-10 code review they ran inside the
gateway's own process, so a malicious PDF could crash the gateway for everyone or, with a working
exploit, read the database URL, the Keycloak client secret and other users' documents in memory.
Word, Excel, Markdown and CSV files (``formats``: zip archives of XML, and text) are read here too.

How (``IsolatedExtractor``):

- **A separate process** (``python -I -m suveryn_rag.isolation``) loads Docling once and reads one
  PDF at a time. It gets the path of the private copy of the upload and nothing else: no database
  connection, and an environment without secrets (``child_env`` removes the database URL, the
  sign-in settings and anything named like a secret, password, token or key).
- **Only JSON comes back**: the Docling document (``DoclingDocument``, validated by pydantic), the
  page texts and counts; for the other formats the passages, each checked for its types. Never pickle: unpickling what a compromised process sends would hand it
  code execution in the gateway, which is exactly what the separation prevents.
- **A fresh reader for every owner**: when the next document belongs to someone else, the reader
  is replaced first. A reader taken over by one user's malicious PDF never sees, or answers for,
  another user's document (security review 2026-10-11). Consecutive documents of one owner share
  a reader, so the models aren't reloaded for each.
- **A crash or a hang** (``SUVERYN_EXTRACT_TIMEOUT_S``, default 30 minutes per document) fails that
  document only: its process group is killed (OCRmyPDF's Ghostscript and Tesseract with it) and a
  fresh reader is started for the next one. No core dumps (they would contain document text).
- **Sandboxing hook**: ``SUVERYN_EXTRACT_WRAPPER`` is a command prefix for the reader, e.g.
  ``systemd-run --user --scope -p MemoryMax=8G`` or a ``bwrap`` line without network. The appliance
  sets it (suveryn-appliance). Without it the reader is refused unless ``SUVERYN_EXTRACT_UNSANDBOXED=1``
  (development only), so a production setup can't run unsandboxed by omission.

What this does not do on its own: the reader still runs as the same operating-system user and can
read what that user can (e.g. the 0600 secrets file, if it knows where it is), and it has network
access. A separate user, no network and seccomp come from ``SUVERYN_EXTRACT_WRAPPER``, set by the
appliance (suveryn-appliance's ``reader-sandbox``). A reader running as another user can't enter
the gateway's 0700 work folder, so then uploads wait in ``SUVERYN_EXTRACT_INBOX`` (provisioned:
owner the gateway, group the reader, 2750; files 0640) and the reader keeps its intermediate files
in ``SUVERYN_EXTRACT_WORK_DIR`` (``own_workspace``). ``SUVERYN_EXTRACT_ISOLATION=off`` reads PDFs
in-process again (debugging only).
"""

import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

from .config import RagSettings
from .extract import Extraction
from .formats import Passage
from .reading import Cancelled, Progress, Unreadable, Watch

STARTUP_TIMEOUT_S = 600          # loading Docling's models: 20-40 s on a GPU, longer on a CPU
CANCEL_CHECK_S = 0.25            # how often a cancel request is looked at while the reader works
MAX_MESSAGE_BYTES = 512 << 20    # a 60-page deed's document is a few MB of JSON
# Environment variables the reader never gets. Matched anywhere in the name, case-insensitive.
SECRET_ENV = re.compile(r"SECRET|PASSW|TOKEN|CREDENTIAL|API_?KEY|PRIVATE|_KEY$|DATABASE_URL|^PG|^SUVERYN_OIDC"
                        r"|^AWS_|^AZURE_|^GOOGLE_APPLICATION|^RUNPOD|^SSH_", re.IGNORECASE)


class ExtractionFailed(Unreadable):
    """The reader couldn't read this document (it failed, crashed or took too long). Safe to show. Its
    ``code`` comes from the reader when it knows why (``reading.Unreadable``), else from what happened."""


def child_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The reader's environment: this process's, minus anything secret, and minus anything that points
    into this process's private temporary folder.

    The reader makes its own temporary folder (``own_workspace``). Libraries set variables into the
    gateway's: torch, imported here for the embedding model, sets TORCHINDUCTOR_CACHE_DIR to
    ``$TMPDIR/torchinductor_<user>``. A reader running as another user can't write there and failed to
    start; and the gateway's private folder isn't the reader's business anyway.
    """
    env = os.environ if environ is None else environ
    private_tmp = env.get("TMPDIR")
    return {k: v for k, v in env.items()
            if not SECRET_ENV.search(k) and not (private_tmp and k != "PATH" and private_tmp in v) and k != "TMPDIR"}


def _settings_for_child(settings: RagSettings) -> dict:
    """What the reader needs to know: OCR and device settings, never the database URL."""
    return {"device": settings.device, "ocr_languages": settings.ocr_languages, "ocr_jobs": settings.ocr_jobs,
            "work_dir": str(settings.extract_work_dir or settings.work_dir), "max_pages": settings.max_pages,
            "chunk_max_tokens": settings.chunk_max_tokens, "layout_batch_size": settings.layout_batch_size,
            "table_batch_size": settings.table_batch_size}


def _document_from_json(data: dict | None):
    if data is None:  # a Word, Excel, Markdown or CSV file: passages instead
        return None
    from docling_core.types.doc import DoclingDocument

    return DoclingDocument.model_validate(data)


def _strings(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise TypeError("expected a list of strings")
    return list(value)


def _passages_from_json(data) -> list[Passage] | None:
    """The passages of a non-PDF file, every field checked: the reader is not trusted to send the right types."""
    if data is None:
        return None
    if not isinstance(data, list):
        raise TypeError("expected a list of passages")
    out = []
    for p in data:
        if not isinstance(p, dict) or not isinstance(p.get("text"), str) or not isinstance(p.get("place"), (str, type(None))):
            raise TypeError("malformed passage")
        out.append(Passage(p["text"], _strings(p.get("headings", [])), p["place"]))
    return out


class IsolatedExtractor:
    """``Extractor``'s interface (``extract(pdf) -> Extraction``), with the reading done in a separate process.

    The reader is started (and its models loaded) on construction, so a broken setup fails at
    start-up as before. One document at a time. ``command`` replaces the reader for tests.
    """

    def __init__(self, settings: RagSettings, command: list[str] | None = None, timeout_s: float | None = None):
        self.settings = settings
        self.timeout_s = timeout_s if timeout_s is not None else settings.extract_timeout_s
        wrapper = shlex.split(settings.extract_wrapper) if settings.extract_wrapper else []
        self._command = command or [*wrapper, sys.executable, "-I", "-m", "suveryn_rag.isolation",
                                    json.dumps(_settings_for_child(settings))]
        if command is None and not settings.extract_wrapper and not settings.extract_unsandboxed:
            raise RuntimeError("the document reader needs a sandbox (SUVERYN_EXTRACT_WRAPPER); "
                               "set SUVERYN_EXTRACT_UNSANDBOXED=1 to run without one, in development only")
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._owner: str | None = None  # whose document the reader last read
        self._served = False
        self._start()

    # ------------------------------------------------------------------ the reader process
    def _start(self) -> None:
        self._proc = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      env=child_env(), start_new_session=True, bufsize=0)
        self._pending = bytearray()
        try:
            hello = self._receive(time.monotonic() + STARTUP_TIMEOUT_S, "loading took too long")
        except ExtractionFailed as e:
            raise ExtractionFailed(f"the document reader didn't start: {e}") from None
        if not hello.get("ready"):
            self._stop()
            raise ExtractionFailed(f"the document reader didn't start: {str(hello.get('error'))[:300]}")

    def _stop(self) -> None:
        """Kill the reader and everything it started (OCRmyPDF runs Ghostscript and Tesseract)."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait()
        for pipe in (proc.stdin, proc.stdout):
            if pipe:
                pipe.close()

    def _receive(self, deadline: float, too_slow: str, watch: Watch | None = None) -> dict:
        """The reader's next JSON line before ``deadline``; kills the reader on any problem, and when
        ``watch`` says the person cancelled (``Cancelled``). The reader may send several lines at once
        (progress, then the answer): what follows a line waits in ``_pending`` for the next call."""
        with selectors.DefaultSelector() as sel:
            sel.register(self._proc.stdout, selectors.EVENT_READ)
            while b"\n" not in self._pending:
                if watch is not None and watch.cancelled():
                    self._stop()
                    raise Cancelled
                left = deadline - time.monotonic()
                if left <= 0:
                    self._stop()
                    raise ExtractionFailed(too_slow, "timeout", minutes=max(1, round(self.timeout_s / 60)))
                if not sel.select(min(left, CANCEL_CHECK_S)):
                    continue
                block = os.read(self._proc.stdout.fileno(), 1 << 20)
                if not block:
                    self._stop()
                    raise ExtractionFailed("the document reader stopped (the file may be damaged or malformed)", "damaged")
                self._pending += block
                if len(self._pending) > MAX_MESSAGE_BYTES:
                    self._stop()
                    raise ExtractionFailed("the document reader sent too much data")
        line, _, rest = bytes(self._pending).partition(b"\n")
        self._pending = bytearray(rest)
        try:
            message = json.loads(line)
        except ValueError:
            self._stop()
            raise ExtractionFailed("the document reader sent an unreadable answer") from None
        if not isinstance(message, dict):
            self._stop()
            raise ExtractionFailed("the document reader sent an unreadable answer")
        return message

    # ------------------------------------------------------------------ Extractor's interface
    def extract(self, pdf: Path, owner: str | None = None, watch: Watch | None = None) -> Extraction:
        """Read one file of ``owner`` in the reader process. Raises ``ExtractionFailed``, or ``Cancelled``
        when ``watch`` says so: the reader is stopped at once (OCR and all) and a fresh one reads the next."""
        with self._lock:
            # Someone else's document: a reader that read another owner's PDF is not trusted with it.
            if self._proc is None or self._proc.poll() is not None or (self._served and owner != self._owner):
                self._stop()
                self._start()
            self._owner, self._served = owner, True
            try:
                self._proc.stdin.write(json.dumps({"file": str(pdf)}).encode() + b"\n")
            except OSError:
                self._stop()
                raise ExtractionFailed("the document reader stopped") from None
            deadline = time.monotonic() + self.timeout_s
            too_slow = f"reading took longer than {max(1, round(self.timeout_s / 60))} minutes"
            r = self._receive(deadline, too_slow, watch)
            while "progress" in r:  # how far it has got, then the answer
                if watch is not None and (progress := _progress_from_json(r["progress"])) is not None:
                    watch.report(progress)
                r = self._receive(deadline, too_slow, watch)
            if not r.get("ok"):
                detail = r.get("detail") if isinstance(r.get("detail"), dict) else {}
                raise ExtractionFailed(str(r.get("error") or "the document couldn't be read")[:300], str(r.get("code") or "unreadable"),
                                       **{k: v for k, v in detail.items() if k in ("pages", "max", "minutes") and isinstance(v, int)})
            try:
                return Extraction(document=_document_from_json(r["document"]), pages=int(r["pages"]),
                                  ocr_pages=int(r["ocr_pages"]), mixed_pages=int(r["mixed_pages"]),
                                  page_texts=[str(t) for t in r["page_texts"]],
                                  timings={str(k): float(v) for k, v in r["timings"].items()},
                                  layout_failed_pages=[int(n) for n in r.get("layout_failed_pages", [])],
                                  passages=_passages_from_json(r.get("passages")),
                                  furniture=_strings(r.get("furniture", [])))
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self._stop()  # a reader that sends malformed answers isn't trusted with the next document
                raise ExtractionFailed(f"the document reader sent an invalid answer ({type(e).__name__})") from None

    def close(self) -> None:
        with self._lock:
            self._stop()


def _progress_from_json(data) -> Progress | None:
    """A progress line from the reader, every field checked (it is not trusted); None if malformed."""
    if not isinstance(data, dict) or data.get("step") not in ("read", "ocr", "layout", "store"):
        return None
    n = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100_000 else None
    return Progress(data["step"], n(data.get("done")), n(data.get("total")))


def make_extractor(settings: RagSettings):
    """The extractor to use: isolated in its own process, unless ``SUVERYN_EXTRACT_ISOLATION=off``."""
    if settings.isolate_extraction:
        return IsolatedExtractor(settings)
    from .extract import Extractor

    return Extractor(settings)


# ---------------------------------------------------------------------- the reader's side
def serve(extract: Callable[..., Extraction], requests: IO[bytes], answers: IO[bytes]) -> None:
    """Answer ``{"file": path}`` lines with one JSON line each, until the gateway closes ``requests``;
    before it, ``{"progress": ...}`` lines as reading goes (``reading.Progress``). A failure carries its
    ``code`` and ``detail`` (``reading.Unreadable``), so the interface can say why in its own language."""
    lock = threading.Lock()  # OCRmyPDF reports progress from its own thread

    def send(message: dict) -> None:
        with lock:
            answers.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
            answers.flush()

    watch = Watch(report=lambda p: send({"progress": {"step": p.step, "done": p.done, "total": p.total}}))

    send({"ready": True})
    for line in requests:
        try:
            ex = extract(Path(json.loads(line)["file"]), watch=watch)
            doc = ex.document.export_to_dict() if hasattr(ex.document, "export_to_dict") else ex.document
            passages = None if ex.passages is None else [
                {"text": p.text, "headings": p.headings, "place": p.place} for p in ex.passages]
            send({"ok": True, "document": doc, "pages": ex.pages, "ocr_pages": ex.ocr_pages,
                  "mixed_pages": ex.mixed_pages, "page_texts": ex.page_texts, "timings": ex.timings,
                  "layout_failed_pages": ex.layout_failed_pages, "passages": passages, "furniture": ex.furniture})
        except Exception as e:  # noqa: BLE001 - reported to the gateway; the reader carries on
            send({"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "code": getattr(e, "code", "unreadable"),
                  "detail": getattr(e, "detail", {})})


def protocol_streams() -> tuple[IO[bytes], IO[bytes]]:
    """(requests, answers) for the reader. Libraries that print to stdout would corrupt the answers,
    so the answers get a private copy of stdout and stdout itself is pointed at stderr."""
    answers = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    return sys.stdin.buffer, answers


def own_workspace(work_dir: Path) -> None:
    """The reader's scratch space: its work folder (0700), also for temporary files, minus crash leftovers.

    The inherited TMPDIR is the gateway's private folder, which a sandboxed reader (another user)
    can't write to; and OCR work folders of a reader that was killed are removed here, by their owner.
    """
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(work_dir, 0o700)
    for leftover in work_dir.glob("doc-*"):
        shutil.rmtree(leftover, ignore_errors=True)
    os.environ["TMPDIR"] = tempfile.tempdir = str(work_dir)


def main() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # a core dump would contain document text
    requests, answers = protocol_streams()
    try:
        from .extract import Extractor

        options = json.loads(sys.argv[1])
        settings = RagSettings(database_url="", device=options["device"], ocr_languages=options["ocr_languages"],
                               ocr_jobs=int(options["ocr_jobs"]), work_dir=Path(options["work_dir"]),
                               max_pages=int(options.get("max_pages", RagSettings.max_pages)),
                               chunk_max_tokens=int(options.get("chunk_max_tokens", RagSettings.chunk_max_tokens)),
                               layout_batch_size=int(options.get("layout_batch_size", RagSettings.layout_batch_size)),
                               table_batch_size=int(options.get("table_batch_size", RagSettings.table_batch_size)),
                               isolate_extraction=False)
        own_workspace(settings.work_dir)
        extractor = Extractor(settings)
    except Exception as e:  # noqa: BLE001 - reported to the gateway, which fails its start-up
        answers.write(json.dumps({"ready": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}).encode() + b"\n")
        answers.flush()
        raise SystemExit(1) from None
    serve(extractor.extract, requests, answers)


if __name__ == "__main__":
    main()
