"""The appliance's backups, as the administrator sees them (suveryn-tracker#33). The appliance's backup
service (suveryn-appliance ``backup/suveryn-backup``) writes its status to a file with no secrets and no
document text; the gateway only reads and checks it. Without that file (a development machine, or an
appliance whose backups have never run) the answer says so.

The key test (review of the backup strategy, 26 October 2026): the appliance can't read its own backups,
so the administrator gives the recovery key, and the backup service checks that it opens the newest
backup and that every part of it is there. The gateway only passes the key on: it writes it, then a
request, into a folder in memory the backup service watches (``suveryn-backup key-test``), which deletes
the key whatever happens and records the result (``key-test.json``). The key is never logged.

Changing the backups (Administration › Backups, docs/design/admin.md, artboard 36): the gateway can change
nothing of the appliance's own, so each request (back up now, the USB disks, a share's test, new settings)
goes the same way: ``request.json`` into a folder in memory the backup service watches
(``suveryn-backup request``), which deletes it at once, acts and answers in ``request-result.json``, never with
a password. The page asks again until the answer with its id is there. The settings themselves are read from
``backups.json`` (0644, no secret)."""

import json
import os
import re
import secrets
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

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
SETTINGS = Path(os.environ.get("SUVERYN_BACKUP_SETTINGS", "/etc/suveryn/backups.json"))
SHARE_SECRET = Path(os.environ.get("SUVERYN_BACKUP_SHARE_SECRET", "/etc/suveryn/backups-share.secret"))
REQUESTS = Path(os.environ.get("SUVERYN_BACKUP_REQUESTS", "/run/suveryn/backup-requests"))
REQUEST_RESULT = Path(os.environ.get("SUVERYN_BACKUP_REQUEST_RESULT", "/var/lib/suveryn/backup/request-result.json"))
RECIPIENT = re.compile(r"age1[02-9ac-hj-np-z]{58}")
DEFAULT_HOUR = 2


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


class BackupSettings(BaseModel):
    """Where, when and how long, as saved (``backups.json``). Never the share's password: only whether one is kept."""

    target: Literal["usb", "share"]
    disk: str | None = None
    protocol: Literal["smb", "nfs"] | None = None
    address: str | None = None
    user: str | None = None
    has_password: bool = False
    retention_days: int
    hour: int = DEFAULT_HOUR
    recipient: str      # the recovery key's public half: on the recovery sheet, to compare with the key file
    next_run: str | None = None  # the next run at the office's hour, UTC


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
    running_since: str | None = None  # a backup is being made
    settings: BackupSettings | None = None


def appliance_zone() -> tzinfo:
    """The appliance's own time zone, the one the backup tool's hour is in (it runs on local time): ``TZ`` when
    set, else /etc/localtime, else UTC. Not SUVERYN_TIMEZONE, which the installer doesn't set (VM check of 28
    October, finding 5: the page said 03:00 in Brussels while the backup ran at 03:00 UTC)."""
    if (key := os.environ.get("TZ", "").lstrip(":")):
        try:
            return ZoneInfo(key)
        except (ValueError, KeyError, OSError):
            pass
    try:
        with open("/etc/localtime", "rb") as f:
            return ZoneInfo.from_file(f)
    except (OSError, ValueError):
        return ZoneInfo("UTC")


def read_settings(now: datetime | None = None) -> BackupSettings | None:
    try:
        raw = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("target") not in ("usb", "share") or not RECIPIENT.fullmatch(str(raw.get("recipient", ""))):
        return None
    hour = raw.get("hour", DEFAULT_HOUR)
    hour = hour if type(hour) is int and 0 <= hour <= 23 else DEFAULT_HOUR
    zone = appliance_zone()
    local = (now or datetime.now(zone)).astimezone(zone)
    slot = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot <= local:
        slot = (slot + timedelta(days=1)).replace(hour=hour)
    text = lambda v, n: v[:n] if isinstance(v, str) else None  # noqa: E731
    return BackupSettings(
        target=raw["target"], disk=raw.get("disk") if isinstance(raw.get("disk"), str) and DISK.fullmatch(raw["disk"]) else None,
        protocol=raw.get("protocol") if raw.get("protocol") in ("smb", "nfs") else None, address=text(raw.get("address"), 512),
        user=text(raw.get("user"), 256), has_password=raw["target"] == "share" and SHARE_SECRET.exists(),
        retention_days=raw.get("retention_days") if raw.get("retention_days") in (14, 30, 90, 365) else 30, hour=hour,
        recipient=raw["recipient"], next_run=slot.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"))


def read_status(path: Path | None = None) -> BackupStatus:
    try:
        raw = json.loads((path or STATUS).read_text())
    except (OSError, ValueError):
        return BackupStatus(available=False, settings=read_settings())
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
                        key_test=read_key_test(when), key_testing=(KEY_TEST_DROP / "request").exists(),
                        running_since=when(raw.get("running_since")), settings=read_settings())


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


# ---------------------------------------------------------------------------- the administrator's requests
class BackupRequest(BaseModel):
    """What the administrator asks the backup service for. ``settings``: the target (a USB disk by the id the
    service lists, or a share with its address, user and password), the retention, the hour and, only with a
    new recovery key, its public half. ``keep_password``: a share's password left empty keeps the saved one."""

    kind: Literal["run", "disks", "test-share", "settings"]
    target: Literal["usb", "share"] | None = None
    disk: str | None = Field(default=None, max_length=160)
    protocol: Literal["smb", "nfs"] | None = None
    address: str | None = Field(default=None, max_length=512)
    user: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=512)
    keep_password: bool = False
    retention_days: Literal[14, 30, 90, 365] | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    recipient: str | None = Field(default=None, pattern=r"^age1[02-9ac-hj-np-z]{58}$")


class RequestAnswer(BaseModel):
    """The backup service's answer: ``ok``; ``errors`` per field and ``error`` as the web setup's codes; the
    USB disks; whether the recovery key changed. ``pending`` until the service has answered."""

    id: str
    pending: bool = False
    ok: bool | None = None
    error: str | None = None
    errors: dict[str, str] | None = None
    disks: list[dict] | None = None
    key_changed: bool | None = None


def leave_request(body: dict) -> str:
    """request.json into the backup service's folder, whole (written beside it, then renamed): one at a time.
    0600, the gateway's own; the service (root) deletes it before anything else."""
    if not REQUESTS.is_dir():
        raise HTTPException(503, "The appliance's backup service can't be reached.")
    final = REQUESTS / "request.json"
    if final.exists():
        raise HTTPException(409, "The backup service is still busy with the last request.")
    rid = secrets.token_hex(8)
    tmp = REQUESTS / f".request-{rid}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"id": rid, **body}, f)
    os.replace(tmp, final)
    return rid


@router.post("/v1/admin/backups/requests", response_model=RequestAnswer, status_code=202, responses={
    403: {"description": "Not an administrator"}, 409: {"description": "The last request is still being handled"},
    503: {"description": "Not an appliance"}})
async def backup_request(body: BackupRequest, request: Request):
    """Ask the backup service: ``run`` (back up now), ``disks`` (the USB disks connected now), ``test-share``
    (sign in to the share and write a test file) or ``settings`` (save the target, retention, hour and a new
    recovery key). The answer comes at ``GET /v1/admin/backups/requests/{id}``. The password is never logged
    and never comes back."""
    admin_or_403(request)
    if body.kind == "settings" and (body.target is None or body.retention_days is None or body.hour is None):
        raise HTTPException(422, "Settings need a target, a retention period and an hour.")
    payload = body.model_dump(exclude_none=True)
    if body.kind != "test-share" and body.kind != "settings":
        payload = {"kind": body.kind}
    return RequestAnswer(id=await run_in_threadpool(leave_request, payload), pending=True)


@router.get("/v1/admin/backups/requests/{rid}", response_model=RequestAnswer, responses={403: {"description": "Not an administrator"}})
async def backup_request_answer(rid: str, request: Request):
    """The backup service's answer to a request, or ``pending`` while it is acting on it."""
    admin_or_403(request)
    if not re.fullmatch(r"[0-9a-f]{16}", rid):
        raise HTTPException(404, "No such request.")
    try:
        raw = json.loads(await run_in_threadpool(REQUEST_RESULT.read_text))
    except (OSError, ValueError):
        raw = None
    if not isinstance(raw, dict) or raw.get("id") != rid:
        return RequestAnswer(id=rid, pending=True)
    errors = raw.get("errors") if isinstance(raw.get("errors"), dict) else None
    disks = [{"id": d["id"], "name": str(d.get("name", ""))[:120], "size_bytes": int(d.get("size_bytes") or 0)}
             for d in raw.get("disks") or [] if isinstance(d, dict) and isinstance(d.get("id"), str) and DISK.fullmatch(d["id"])] \
        if isinstance(raw.get("disks"), list) else None
    return RequestAnswer(id=rid, ok=bool(raw.get("ok")), error=str(raw["error"])[:40] if raw.get("error") else None,
                         errors={str(k)[:40]: str(v)[:40] for k, v in errors.items()} if errors else None,
                         disks=disks, key_changed=raw.get("key_changed") if isinstance(raw.get("key_changed"), bool) else None)
