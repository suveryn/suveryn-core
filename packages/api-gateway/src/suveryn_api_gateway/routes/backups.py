"""The appliance's backups, as the administrator sees them (suveryn-tracker#33). The appliance's backup
service (suveryn-appliance ``backup/suveryn-backup``) writes its status to a file with no secrets and no
document text; the gateway only reads and checks it. Without that file (a development machine, or an
appliance whose backups have never run) the answer says so."""

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .common import admin_or_403

router = APIRouter()

STATUS = Path(os.environ.get("SUVERYN_BACKUP_STATUS", "/var/lib/suveryn/backup/status.json"))
WHEN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class BackupSuccess(BaseModel):
    at: str
    size: int
    on_target: int | None = None
    oldest: str | None = None


class BackupFailure(BaseModel):
    at: str
    step: str
    message: str


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
    success = BackupSuccess(at=ok["at"], size=int(ok.get("size", 0)), on_target=ok.get("on_target"), oldest=when(ok.get("oldest"))) \
        if isinstance(ok, dict) and when(ok.get("at")) else None
    failure = BackupFailure(at=err["at"], step=str(err.get("step", ""))[:40], message=str(err.get("message", ""))[:300]) \
        if isinstance(err, dict) and when(err.get("at")) else None
    return BackupStatus(available=True, configured=bool(raw.get("configured")),
                        target=raw.get("target") if raw.get("target") in ("usb", "share") else None,
                        retention_days=raw.get("retention_days") if isinstance(raw.get("retention_days"), int) else None,
                        last_attempt=when(raw.get("last_attempt")), last_success=success, last_error=failure)


@router.get("/v1/admin/backups", response_model=BackupStatus, responses={403: {"description": "Not an administrator"}})
async def backups(request: Request):
    """The last backup and the last failure, as the appliance's backup service recorded them."""
    admin_or_403(request)
    return await run_in_threadpool(read_status)
