"""Entry point: `uv run suveryn-gateway` (host/port via SUVERYN_HOST / SUVERYN_PORT)."""

import atexit
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import uvicorn


def private_tmp() -> Path:
    """Point this process's temporary files at a private folder instead of /tmp.

    Starlette spools every uploaded file above 1 MB to a temporary file while the request is
    received, before our code sees it. By default that is an (already unlinked) file in /tmp,
    so a confidential PDF would be written there. The gateway redirects ``tempfile`` and
    ``TMPDIR`` to ``<SUVERYN_WORK_DIR>/tmp/<pid>`` (0700), removed on exit. Folders of processes
    that are no longer running (a crash) are removed on start; another running gateway's folder
    is left alone. Idempotent: a second call in the same process returns the same folder.
    """
    work = Path(os.environ.get("SUVERYN_WORK_DIR", Path.home() / ".local" / "state" / "suveryn" / "work"))
    root = work / "tmp"
    mine = root / str(os.getpid())
    if tempfile.tempdir == str(mine):
        return mine
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(work, 0o700)
    os.chmod(root, 0o700)
    for leftover in root.iterdir():
        if not (leftover.name.isdigit() and _running(int(leftover.name))):
            shutil.rmtree(leftover, ignore_errors=True)
    mine.mkdir(mode=0o700, exist_ok=True)
    os.environ["TMPDIR"] = str(mine)
    tempfile.tempdir = str(mine)
    atexit.register(shutil.rmtree, mine, True)
    return mine


def _running(pid: int) -> bool:
    """True if a process with this id exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def check_auth_settings(host: str) -> None:
    """Refuse to start with sign-in turned off on anything but a loopback address.

    ``SUVERYN_AUTH=off`` exists for development on one machine; on a network address it would
    give anyone who can reach the port every document. Raises ``SystemExit``.
    """
    from .auth import AuthSettings

    settings = AuthSettings.from_env()
    if settings.disabled and host not in LOOPBACK:
        raise SystemExit(f"SUVERYN_AUTH=off is only allowed on a loopback address, not {host}.")
    if not settings.disabled and settings.public_url.startswith("http://") and host not in LOOPBACK:
        print("warning: SUVERYN_PUBLIC_URL is http://; serve the UI over https on a network "
              "(session cookies are only marked Secure with https)")


def check_one_process() -> None:
    """Refuse to start as several worker processes.

    Sessions and rate limits live in this process's memory (one gateway per appliance, by design):
    with two workers a sign-in would be known to one and not the other, and a limit would count
    half. uvicorn starts workers from ``WEB_CONCURRENCY``; the gateway doesn't take ``--workers``
    itself, so this is the one way to get there without editing code. Raises ``SystemExit``.
    """
    workers = os.environ.get("WEB_CONCURRENCY", "1").strip()
    if workers not in ("", "1"):
        raise SystemExit(f"WEB_CONCURRENCY={workers}: the gateway runs as one process (sessions and rate limits "
                         "are in memory); run one gateway per appliance.")


def not_dumpable() -> bool:
    """Make this process unreadable through /proc for other processes of the same user (Linux).

    The document reader runs as the gateway's user when no sandbox wrapper is set, and could otherwise
    read ``/proc/<gateway>/environ`` and ``mem``: the database URL, the sign-in secret, other users'
    documents in memory (security review 2026-10-11). Non-dumpable also means no core dumps. The
    reader is a new program (exec), so this doesn't carry over to it. False where unsupported.
    """
    if not sys.platform.startswith("linux"):
        return False
    import ctypes

    PR_SET_DUMPABLE = 4
    libc = ctypes.CDLL(None, use_errno=True)
    return libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def configure_logging() -> logging.Handler | None:
    """Send sūveryn's own log lines (the ``suveryn.*`` loggers) to stderr, which the journal keeps.

    Without this nothing configured them: Python's last-resort handler printed warnings and errors
    only, so every informational line (a database reachable again, conversations deleted after
    their keep period, a playbook answer read again) was dropped (Pod check of eb35c55). uvicorn
    sets up its own loggers only. The level is ``SUVERYN_LOG_LEVEL`` (default ``INFO``; an unknown
    value is ``INFO`` too). The lines hold ids, counts and kinds, never document text: that is the
    rule for every log call in the code. Idempotent: a second call adds no second handler.
    """
    logger = logging.getLogger("suveryn")
    if any(getattr(h, "_suveryn", False) for h in logger.handlers):
        return None
    level = os.environ.get("SUVERYN_LOG_LEVEL", "INFO").strip().upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler._suveryn = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level if level in LOG_LEVELS else "INFO")
    logger.propagate = False  # not printed twice (by the root's last-resort handler)
    return handler


def run() -> None:
    """Start the gateway. Binds to 127.0.0.1 unless SUVERYN_HOST says otherwise.

    On a network address it should sit behind the appliance's TLS reverse proxy, with
    ``SUVERYN_PUBLIC_URL`` set to the https URL people use.
    """
    host = os.environ.get("SUVERYN_HOST", "127.0.0.1")
    check_auth_settings(host)
    check_one_process()
    if not not_dumpable() and sys.platform.startswith("linux"):
        print("warning: couldn't make the gateway unreadable through /proc (prctl PR_SET_DUMPABLE)")
    private_tmp()
    configure_logging()
    uvicorn.run(
        "suveryn_api_gateway.app:app",
        host=host,
        port=int(os.environ.get("SUVERYN_PORT", "8000")),
    )
