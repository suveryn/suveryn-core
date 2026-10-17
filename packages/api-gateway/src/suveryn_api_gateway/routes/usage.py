"""Token usage (suveryn-tracker#7): counts only, per user; administrators see the office's with a
notional cloud cost and set the rates. Informational: nothing is ever limited because of it."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from ..usage import AdminUsageReport, Rates, UsageReport, parse_range
from .common import admin_or_403, owner_of, usage_or_503

router = APIRouter()


def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    try:
        return parse_range(start, end)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/v1/usage", response_model=UsageReport)
async def my_usage(request: Request, start: datetime | None = None, end: datetime | None = None):
    """The caller's own token usage between ``start`` and ``end`` (ISO 8601 with a time zone;
    default: the last 24 hours): totals, a series of buckets in local time, per kind. Never a colleague's."""
    store, (a, b) = usage_or_503(request), _range(start, end)
    return await run_in_threadpool(store.report, a, b, owner_of(request))


@router.get("/v1/admin/usage", response_model=AdminUsageReport, responses={403: {"description": "Not an administrator"}})
async def office_usage(request: Request, start: datetime | None = None, end: datetime | None = None):
    """Administrators: the office's token usage, per user and in total, with a notional cloud cost."""
    admin_or_403(request)
    store, (a, b) = usage_or_503(request), _range(start, end)
    return await run_in_threadpool(store.admin_report, a, b)


@router.get("/v1/admin/usage/rates", response_model=Rates, responses={403: {"description": "Not an administrator"}})
async def usage_rates(request: Request):
    """Administrators: the rates the notional cost uses, per million input and output tokens."""
    admin_or_403(request)
    return await run_in_threadpool(usage_or_503(request).rates)


@router.put("/v1/admin/usage/rates", response_model=Rates, responses={403: {"description": "Not an administrator"}})
async def set_usage_rates(rates: Rates, request: Request):
    """Administrators: change the rates (e.g. to a cloud model the office would otherwise use)."""
    admin_or_403(request)
    user = getattr(request.state, "user", None)
    return await run_in_threadpool(usage_or_503(request).set_rates, rates, user.username if user else "local-dev")
