"""``GET /v1/admin/status``: is everything working? (docs/design/admin.md, *Status*, artboards 30 and 39).

Five checks in plain words, for the administrator: answering questions (the model), reading documents,
signing in, keeping your data (the databases) and disk space. Each says whether it works, since when it
doesn't, and a count or two (answers being written, documents in progress and waiting, free space). Counts
only: never what is asked or read.

A monitor runs the checks every minute while the gateway runs, so "not working since 09:12" is the time it
was first seen failing, not the time someone looked. Kept in memory: a restart starts afresh.
"""

import asyncio
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .common import admin_or_403

log = logging.getLogger("suveryn.gateway")
router = APIRouter()

INTERVAL_S = 60
OS_RELEASE = Path(os.environ.get("SUVERYN_OS_RELEASE", "/usr/lib/os-release"))
CORE_BUILT = Path(os.environ.get("SUVERYN_CORE_BUILT", "/opt/suveryn/core/.suveryn-built"))


def appliance_version() -> str | None:
    """What Status shows as the version (Filip, 29 October: it should): ``SUVERYN_VERSION`` when set, else the
    read-only system's release (``IMAGE_VERSION`` in os-release, sūveryn's image only) and the core commit the
    appliance was built with, e.g. "1.2.0 · core a34d3fb"; on a machine installed with the provisioning, the core
    commit alone. None when none of these is there (a development machine)."""
    if (given := os.environ.get("SUVERYN_VERSION", "").strip()):
        return given[:60]
    parts = []
    try:
        release = dict(line.split("=", 1) for line in OS_RELEASE.read_text().splitlines() if "=" in line)
        if release.get("IMAGE_ID", "").strip('"').startswith("suveryn") and (v := release.get("IMAGE_VERSION", "").strip('"')):
            parts.append(v[:30])
    except OSError:
        pass
    try:
        built = CORE_BUILT.read_text().strip()  # "suveryn-core@<full commit>"
        if built.startswith("suveryn-core@"):
            parts.append(f"core {built.split('@', 1)[1][:7]}")
    except OSError:
        pass
    return " · ".join(parts) or None
FRESH_S = 15  # a page asking within this long of the last check gets that one
# Disk space is short below either: a tenth of the disk, or room for a night's backup and a few uploads.
LOW_SHARE = 0.10
LOW_BYTES = 10 * 1024**3
# Where the office's data is: the data partition on an appliance (everything under /var/lib/suveryn).
DATA_PATH = Path(os.environ.get("SUVERYN_DATA_PATH", "/var/lib/suveryn"))

CheckId = Literal["answering", "reading", "signin", "data", "disk"]


class Check(BaseModel):
    id: CheckId
    ok: bool
    since: datetime | None = None  # when it was first seen failing, while it fails
    in_progress: int | None = None  # answering: answers being written; reading: documents being read
    waiting: int | None = None  # reading: documents waiting
    free: int | None = None  # disk: bytes free, and of
    total: int | None = None


class AdminStatus(BaseModel):
    checked_at: datetime
    checks: list[Check]
    version: str | None = None  # the appliance's version (appliance_version)


def _disk() -> tuple[int, int] | None:
    path = DATA_PATH if DATA_PATH.exists() else Path("/")
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free, usage.total


class StatusMonitor:
    """The latest checks, and since when each has failed."""

    def __init__(self) -> None:
        self.latest: AdminStatus | None = None
        self.failing_since: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def check(self, state) -> AdminStatus:
        async with self._lock:
            now = datetime.now(UTC)
            h = await state.llm.health()
            docs = state.documents
            reading_ok = docs is not None and docs.state == "ready"
            in_progress, waiting = await run_in_threadpool(docs.job_counts) if docs is not None and hasattr(docs, "job_counts") else (None, None)
            signin_ok = (await state.auth.status())[0] in ("ready", "disabled")
            stores = [state.history, state.usage, state.cases]
            statuses = [await run_in_threadpool(s.status) for s in stores if s.configured]
            data_ok = all(s.status == "ready" for s in statuses)
            disk = await run_in_threadpool(_disk)
            disk_ok = disk is None or (disk[0] >= LOW_SHARE * disk[1] and disk[0] >= LOW_BYTES)
            checks = [
                Check(id="answering", ok=h.status == "ok", in_progress=getattr(state.chat, "answering", None)),
                Check(id="reading", ok=reading_ok, in_progress=in_progress, waiting=waiting),
                Check(id="signin", ok=signin_ok),
                Check(id="data", ok=data_ok),
                Check(id="disk", ok=disk_ok, free=disk[0] if disk else None, total=disk[1] if disk else None),
            ]
            for c in checks:
                if c.ok:
                    self.failing_since.pop(c.id, None)
                else:
                    c.since = self.failing_since.setdefault(c.id, now)
            self.latest = AdminStatus(checked_at=now, checks=checks, version=appliance_version())
            return self.latest

    async def run(self, state) -> None:
        """Every minute, for as long as the gateway runs; one failing check never stops it."""
        while True:
            try:
                status = await self.check(state)
                for c in status.checks:
                    if not c.ok and c.since == status.checked_at:
                        log.warning("status: %s stopped working", c.id)
            except Exception as e:  # noqa: BLE001 - the monitor must outlive any one failure
                log.error("status check: %s", type(e).__name__)
            await asyncio.sleep(INTERVAL_S)


@router.get("/v1/admin/status", response_model=AdminStatus, responses={403: {"description": "Not an administrator"}})
async def admin_status(request: Request):
    """Is everything working? The five checks, the latest at most a quarter of a minute old."""
    admin_or_403(request)
    monitor: StatusMonitor = request.app.state.status
    latest = monitor.latest
    if latest is not None and time.time() - latest.checked_at.timestamp() < FRESH_S:
        return latest
    return await monitor.check(request.app.state)
