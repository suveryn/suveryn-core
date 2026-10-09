"""Entry point: `uv run suveryn-gateway` (host/port via SUVERYN_HOST / SUVERYN_PORT)."""

import atexit
import os
import shutil
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


def run() -> None:
    """Start the gateway. Binds to 127.0.0.1 unless SUVERYN_HOST says otherwise: there is no auth yet."""
    private_tmp()
    uvicorn.run(
        "suveryn_api_gateway.app:app",
        host=os.environ.get("SUVERYN_HOST", "127.0.0.1"),
        port=int(os.environ.get("SUVERYN_PORT", "8000")),
    )
