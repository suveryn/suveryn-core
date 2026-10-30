"""The appliance's clock: the browsers' measurements, and an administrator setting it (``clock.py``)."""

import re
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import clock as clock_module
from .common import admin_or_403, principal

router = APIRouter()

YEAR_MS = 366 * 24 * 3600 * 1000


class Now(BaseModel):
    now_ms: int  # the appliance's clock, in milliseconds since 1970 (UTC)


class Measured(BaseModel):
    """What a browser measured: the appliance's clock minus its own, and the round trip it measured it in."""

    offset_ms: int = Field(ge=-YEAR_MS, le=YEAR_MS)
    rtt_ms: int = Field(ge=0, le=60_000)


class SetAnswer(BaseModel):
    id: str
    pending: bool = False
    ok: bool | None = None
    error: str | None = None  # synced, out_of_range, invalid
    moved_ms: int | None = None


@router.get("/v1/clock", response_model=Now)
async def clock_now(response: Response):
    """The appliance's clock, for a signed-in browser to measure the difference with its own."""
    response.headers["Cache-Control"] = "no-store"
    return Now(now_ms=time.time_ns() // 1_000_000)


@router.post("/v1/clock", status_code=204)
async def clock_measured(body: Measured, request: Request):
    """A signed-in browser's measurement. The newest per account counts for a day; when they agree the
    appliance is asked to nudge its clock (``clock.Clock.report``)."""
    caller = principal(request)
    await run_in_threadpool(request.app.state.clock.report, caller.sub, caller.admin, body.offset_ms, body.rtt_ms)
    return Response(status_code=204)


@router.post("/v1/admin/clock", response_model=SetAnswer, status_code=202, responses={
    403: {"description": "Not an administrator"}, 409: {"description": "A time server keeps the clock, or the last request is busy"},
    503: {"description": "Not an appliance"}})
async def set_clock(body: Measured, request: Request):
    """Administrators: set the appliance's clock to this PC's time, by the difference just measured (Status, after a
    confirmation that shows both times). The answer comes at ``GET /v1/admin/clock/{id}``."""
    admin_or_403(request)
    if body.rtt_ms > clock_module.MAX_RTT_MS:
        raise HTTPException(422, "The measurement took too long to say how far off the clock is; try again.")
    if request.app.state.clock.synced():
        raise HTTPException(409, "A time server keeps the appliance's clock.")
    if not clock_module.REQUESTS.is_dir():
        raise HTTPException(503, "The appliance's clock can't be set from here.")
    rid = await run_in_threadpool(clock_module.leave_request, {"kind": "set", "offset_ms": body.offset_ms})
    if rid is None:
        raise HTTPException(409, "The appliance is still busy with the last change to its clock.")
    request.app.state.clock.reports.clear()  # what was measured before no longer holds
    clock_module.log.warning("clock: an administrator set the appliance's clock by %+.1f s", -body.offset_ms / 1000)
    return SetAnswer(id=rid, pending=True)


@router.get("/v1/admin/clock/{rid}", response_model=SetAnswer, responses={403: {"description": "Not an administrator"}})
async def set_clock_answer(rid: str, request: Request):
    """The appliance's answer to setting its clock, or ``pending`` while it acts on it."""
    admin_or_403(request)
    if not re.fullmatch(r"[0-9a-f]{16}", rid):
        raise HTTPException(404, "No such request.")
    raw = await run_in_threadpool(clock_module.result_of, rid)
    if raw is None:
        return SetAnswer(id=rid, pending=True)
    moved = raw.get("moved_ms")
    return SetAnswer(id=rid, ok=bool(raw.get("ok")), error=str(raw["error"])[:40] if raw.get("error") else None,
                     moved_ms=moved if type(moved) is int else None)
