"""The appliance's clock: the browsers' measurements, and an administrator setting it (``clock.py``)."""

import re
import time

from fastapi import APIRouter, Request, Response
from suveryn_harness.messages import Problem, why
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import clock as clock_module
from ..problems import Message, refusals
from .common import admin_or_403, principal

router = APIRouter(tags=["clock"])  # the group its operations are in, in the description (description.py)

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
    failure: Message | None = None  # why it wasn't set, as the clock's helper wrote it
    moved_ms: int | None = None


@router.get("/v1/clock", response_model=Now, responses=refusals())
async def get_clock(response: Response):
    """The appliance's clock, for a signed-in browser to measure the difference with its own."""
    response.headers["Cache-Control"] = "no-store"
    return Now(now_ms=time.time_ns() // 1_000_000)


@router.post("/v1/clock", status_code=204, responses=refusals())
async def report_clock_measurement(body: Measured, request: Request):
    """A signed-in browser's measurement. The newest per account counts for a day; when they agree the
    appliance is asked to nudge its clock (``clock.Clock.report``)."""
    caller = principal(request)
    await run_in_threadpool(request.app.state.clock.report, caller.sub, caller.admin, body.offset_ms, body.rtt_ms)
    return Response(status_code=204)


@router.post("/v1/admin/clock", response_model=SetAnswer, status_code=202, responses=refusals(409, 422))
async def create_clock_request(body: Measured, request: Request):
    """Administrators: set the appliance's clock to this PC's time, by the difference just measured (Status, after a
    confirmation that shows both times). The answer comes at ``GET /v1/admin/clock/{id}``."""
    admin_or_403(request)
    if body.rtt_ms > clock_module.MAX_RTT_MS:
        raise Problem("clock.measurement_too_slow", "The measurement took too long to say how far off the clock is; try again.")
    if request.app.state.clock.synced():
        raise Problem("clock.synced", "A time server keeps the appliance's clock.")
    if not clock_module.REQUESTS.is_dir():
        raise Problem("clock.unavailable", "The appliance's clock can't be set from here.")
    rid = await run_in_threadpool(clock_module.leave_request, {"kind": "set", "offset_ms": body.offset_ms})
    if rid is None:
        raise Problem("clock.busy", "The appliance is still busy with the last change to its clock.")
    request.app.state.clock.reports.clear()  # what was measured before no longer holds
    # asked, not done: the helper may refuse (a time server took over meanwhile); its answer is logged when it comes
    # (VM regression 9c97d76, finding 5: the journal said the clock was set when it never moved)
    clock_module.log.warning("clock: an administrator asked to set the appliance's clock by %+.1f s", -body.offset_ms / 1000)
    return SetAnswer(id=rid, pending=True)


@router.get("/v1/admin/clock/{rid}", response_model=SetAnswer, responses=refusals(404))
async def get_clock_request(rid: str, request: Request):
    """The appliance's answer to setting its clock, or ``pending`` while it acts on it."""
    admin_or_403(request)
    if not re.fullmatch(r"[0-9a-f]{16}", rid):
        raise Problem("request.not_found", "No such request.")
    raw = await run_in_threadpool(clock_module.result_of, rid)
    if raw is None:
        return SetAnswer(id=rid, pending=True)
    moved = raw.get("moved_ms")
    answered: set = request.app.state.__dict__.setdefault("clock_answers_logged", set())
    if rid not in answered:
        answered.add(rid)
        if raw.get("ok"):
            clock_module.log.warning("clock: the appliance's clock was set (moved by %+.1f s)",
                                     (moved if type(moved) is int else 0) / 1000)
        else:
            clock_module.log.warning("clock: the appliance did not set its clock (%s)", why(raw.get("failure"))["code"])
    ok = bool(raw.get("ok"))
    return SetAnswer(id=rid, ok=ok, failure=None if ok else why(raw.get("failure")),
                     moved_ms=moved if type(moved) is int else None)
