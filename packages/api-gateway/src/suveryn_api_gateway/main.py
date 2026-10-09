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


def run() -> None:
    """Start the gateway. Binds to 127.0.0.1 unless SUVERYN_HOST says otherwise.

    On a network address it should sit behind the appliance's TLS reverse proxy, with
    ``SUVERYN_PUBLIC_URL`` set to the https URL people use.
    """
    host = os.environ.get("SUVERYN_HOST", "127.0.0.1")
    check_auth_settings(host)
    private_tmp()
    uvicorn.run(
        "suveryn_api_gateway.app:app",
        host=host,
        port=int(os.environ.get("SUVERYN_PORT", "8000")),
    )
