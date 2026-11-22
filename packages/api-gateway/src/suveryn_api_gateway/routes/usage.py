"""Token usage (suveryn-tracker#7): counts only, per user; administrators see the office's with a
notional cloud cost and set the rates. Informational: nothing is ever limited because of it."""

from datetime import datetime

from fastapi import APIRouter, Request
from suveryn_harness.messages import Problem
from fastapi.concurrency import run_in_threadpool

from ..problems import refusals
from ..usage import AdminUsageReport, Rates, UsageReport, parse_range
from .common import admin_or_403, owner_of, usage_or_503, who

router = APIRouter(tags=["usage"])  # the group its operations are in, in the description (description.py)


def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    try:
        return parse_range(start, end)
    except ValueError as e:
        raise Problem("request.invalid", str(e)) from None


@router.get("/v1/usage", response_model=UsageReport, responses=refusals())
async def get_my_usage(request: Request, start: datetime | None = None, end: datetime | None = None):
    """The caller's own token usage between ``start`` and ``end`` (ISO 8601 with a time zone;
    default: the last 24 hours): totals, a series of buckets in local time, per kind. Never a colleague's."""
    store, (a, b) = usage_or_503(request), _range(start, end)
    return await run_in_threadpool(store.report, a, b, owner_of(request))


@router.get("/v1/admin/usage", response_model=AdminUsageReport, responses=refusals())
async def get_office_usage(request: Request, start: datetime | None = None, end: datetime | None = None):
    """Administrators: the office's token usage, per user and in total, with a notional cloud cost."""
    admin_or_403(request)
    store, (a, b) = usage_or_503(request), _range(start, end)
    return await run_in_threadpool(store.admin_report, a, b)


@router.get("/v1/admin/usage/rates", response_model=Rates, responses=refusals())
async def get_usage_rates(request: Request):
    """Administrators: the rates the notional cost uses, per million input and output tokens."""
    admin_or_403(request)
    return await run_in_threadpool(usage_or_503(request).rates)


@router.put("/v1/admin/usage/rates", response_model=Rates, responses=refusals())
async def set_usage_rates(rates: Rates, request: Request):
    """Administrators: change the rates (e.g. to a cloud model the office would otherwise use)."""
    admin_or_403(request)
    return await run_in_threadpool(usage_or_503(request).set_rates, rates, who(request)[1] or who(request)[0])
