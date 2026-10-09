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
    ``TMPDIR`` to ``<SUVERYN_WORK_DIR>/tmp`` (0700), emptied on start and removed on exit.
    """
    work = Path(os.environ.get("SUVERYN_WORK_DIR", Path.home() / ".local" / "state" / "suveryn" / "work"))
    tmp = work / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)  # leftovers from a crash
    tmp.mkdir(mode=0o700, parents=True)
    os.chmod(work, 0o700)
    os.environ["TMPDIR"] = str(tmp)
    tempfile.tempdir = str(tmp)
    atexit.register(shutil.rmtree, tmp, True)
    return tmp


def run() -> None:
    """Start the gateway. Binds to 127.0.0.1 unless SUVERYN_HOST says otherwise: there is no auth yet."""
    private_tmp()
    uvicorn.run(
        "suveryn_api_gateway.app:app",
        host=os.environ.get("SUVERYN_HOST", "127.0.0.1"),
        port=int(os.environ.get("SUVERYN_PORT", "8000")),
    )
