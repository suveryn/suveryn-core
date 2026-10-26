"""The appliance's backups, as the administrator sees them (suveryn-tracker#33). The appliance's backup
service (suveryn-appliance ``backup/suveryn-backup``) writes its status to a file with no secrets and no
document text; the gateway only reads and checks it. Without that file (a development machine, or an
appliance whose backups have never run) the answer says so.

The key test (review of the backup strategy, 26 October 2026): the appliance can't read its own backups,
so the administrator gives the recovery key, and the backup service checks that it opens the newest
backup and that every part of it is there. The gateway only passes the key on: it writes it, then a
request, into a folder in memory the backup service watches (``suveryn-backup key-test``), which deletes
the key whatever happens and records the result (``key-test.json``). The key is never logged."""

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .common import admin_or_403

router = APIRouter()

STATUS = Path(os.environ.get("SUVERYN_BACKUP_STATUS", "/var/lib/suveryn/backup/status.json"))
KEY_TEST_RESULT = Path(os.environ.get("SUVERYN_BACKUP_KEY_TEST_RESULT", "/var/lib/suveryn/backup/key-test.json"))
KEY_TEST_DROP = Path(os.environ.get("SUVERYN_BACKUP_KEY_TEST", "/run/suveryn/backup-key-test"))
# An age identity file as the web setup downloads it: comment lines and one AGE-SECRET-KEY-1… line.
AGE_IDENTITY = re.compile(r"AGE-SECRET-KEY-1[02-9AC-HJ-NP-Z]{58}")
MAX_KEY_FILE = 4096
WHEN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DISK = re.compile(r"usb-[A-Za-z0-9._-]{1,120}")


class BackupSuccess(BaseModel):
    at: str
    size: int
    on_target: int | None = None
    oldest: str | None = None
    disk: str | None = None       # which USB disk, when the office swaps two


class BackupFailure(BaseModel):
    at: str
    step: str
    message: str


class KeyTest(BaseModel):
    """The last key test: whether the key opened the newest backup and every part was there."""

    at: str
    ok: bool
    created: str | None = None   # when the backup it opened was made
    step: str | None = None      # where it failed


class BackupStatus(BaseModel):
    """``available``: the appliance has a backup service that has run at least once. ``configured``: a
    target is set (the web setup's Backups step). The rest only when known."""

    available: bool
    configured: bool = False
    target: str | None = None
    retention_days: int | None = None
    last_attempt: str | None = None
    last_success: BackupSuccess | None = None
    last_error: BackupFailure | None = None
    key_test: KeyTest | None = None
    key_testing: bool = False     # a test was asked for and hasn't finished


def read_status(path: Path | None = None) -> BackupStatus:
    try:
        raw = json.loads((path or STATUS).read_text())
    except (OSError, ValueError):
        return BackupStatus(available=False)
    if not isinstance(raw, dict):
        return BackupStatus(available=False)

    def when(value) -> str | None:
        return value if isinstance(value, str) and WHEN.fullmatch(value) else None

    ok, err = raw.get("last_success"), raw.get("last_error")
    disk = ok.get("disk") if isinstance(ok, dict) else None
    success = BackupSuccess(at=ok["at"], size=int(ok.get("size", 0)), on_target=ok.get("on_target"), oldest=when(ok.get("oldest")),
                            disk=disk if isinstance(disk, str) and DISK.fullmatch(disk) else None) \
        if isinstance(ok, dict) and when(ok.get("at")) else None
    failure = BackupFailure(at=err["at"], step=str(err.get("step", ""))[:40], message=str(err.get("message", ""))[:300]) \
        if isinstance(err, dict) and when(err.get("at")) else None
    return BackupStatus(available=True, configured=bool(raw.get("configured")),
                        target=raw.get("target") if raw.get("target") in ("usb", "share") else None,
                        retention_days=raw.get("retention_days") if isinstance(raw.get("retention_days"), int) else None,
                        last_attempt=when(raw.get("last_attempt")), last_success=success, last_error=failure,
                        key_test=read_key_test(when), key_testing=(KEY_TEST_DROP / "request").exists())


def read_key_test(when) -> KeyTest | None:
    try:
        raw = json.loads(KEY_TEST_RESULT.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not when(raw.get("at")) or not isinstance(raw.get("ok"), bool):
        return None
    return KeyTest(at=raw["at"], ok=raw["ok"], created=when(raw.get("created")),
                   step=str(raw["step"])[:40] if raw.get("step") and not raw["ok"] else None)


@router.get("/v1/admin/backups", response_model=BackupStatus, responses={403: {"description": "Not an administrator"}})
async def backups(request: Request):
    """The last backup and the last failure, as the appliance's backup service recorded them."""
    admin_or_403(request)
    return await run_in_threadpool(read_status)


def leave_key(key: bytes) -> None:
    """The key, then the request, into the backup service's folder: the request last, so the test starts
    only with the whole key there. 0600, the gateway's own; the backup service (root) deletes both."""
    if not KEY_TEST_DROP.is_dir():
        raise HTTPException(503, "The appliance's backup service can't be reached for a key test.")
    if (KEY_TEST_DROP / "request").exists():
        raise HTTPException(409, "A key test is already running.")
    for name, data in (("key", key), ("request", b"asked by an administrator\n")):
        fd = os.open(KEY_TEST_DROP / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)


@router.post("/v1/admin/backups/key-test", status_code=202,
             responses={403: {"description": "Not an administrator"}, 409: {"description": "A test is already running"},
                        415: {"description": "Not a recovery key file"}, 503: {"description": "Not an appliance"}})
async def key_test(request: Request):
    """Test the recovery key: the request body is the key file as the web setup downloaded it. The backup
    service checks that it opens the newest backup and that every part is there, restores nothing and
    deletes the key; GET /v1/admin/backups then shows the result (``key_test``)."""
    admin_or_403(request)
    body = await request.body()
    lines = body[:MAX_KEY_FILE + 1].decode("utf-8", errors="replace").splitlines()
    keys = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if len(body) > MAX_KEY_FILE or len(keys) != 1 or not AGE_IDENTITY.fullmatch(keys[0]):
        raise HTTPException(415, "That isn't a sūveryn recovery key file.")
    await run_in_threadpool(leave_key, (keys[0] + "\n").encode())
    return Response(status_code=202)
