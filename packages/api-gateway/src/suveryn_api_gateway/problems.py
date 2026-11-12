"""How the gateway answers when it doesn't give the answer asked for: Problem Details (RFC 9457,
``application/problem+json``) with a code of the registry of messages (``suveryn_harness.messages``; the handbook's
decision of 12 November 2026, *Messages are codes*; docs/design/messages.md).

Three ways an answer becomes a problem, and one shape for all:

- a ``Problem`` raised anywhere (the one way new code refuses): its own code and parameters;
- a plain ``HTTPException`` (code not yet moved to the registry; ``tests/test_problems.py`` counts them, and the count
  may only go down): the general code for its status (``GENERAL``), its English detail kept for developers;
- anything nobody planned for: ``system.internal`` with a reference. The log has the reference, the exception's
  type and where it was raised, never its message, which may quote a document.

The page words the code in its reader's language and never shows ``title`` or ``detail``.
"""
from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from suveryn_harness.messages import Problem, loggable, message, problem, reference

log = logging.getLogger("suveryn.gateway")

MEDIA_TYPE = "application/problem+json"
# The general code a status stands for, for a refusal that has no code of its own yet.
GENERAL = {400: "request.invalid", 401: "auth.signed_out", 403: "request.forbidden", 404: "request.not_found",
           405: "request.invalid", 409: "request.conflict", 411: "request.invalid", 413: "request.too_large",
           415: "request.unsupported", 422: "request.invalid", 429: "request.too_many"}


def answer(code: str, detail: str = "", status: int | None = None, headers: dict[str, str] | None = None, **params) -> JSONResponse:
    """The Problem Details answer for a code."""
    body = problem(code, detail, status, **params)
    return JSONResponse(body, status_code=body["status"], headers=headers, media_type=MEDIA_TYPE)


def general(status: int) -> str:
    return GENERAL.get(status, "system.unavailable" if status >= 500 else "request.invalid")


def install(app: FastAPI) -> None:
    """The handlers that give every refusal and failure the one shape. Called first when the app is made, so the
    catch-all is the outermost middleware."""

    @app.exception_handler(Problem)
    async def a_problem(request: Request, exc: Problem):
        if exc.kind != "refused":
            log.warning("%s %s: %s", request.method, request.url.path, loggable(exc.message))
        return answer(exc.code, exc.detail, headers=exc.headers, **exc.params)

    @app.exception_handler(StarletteHTTPException)
    async def a_plain_refusal(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else ""
        return answer(general(exc.status_code), detail, exc.status_code, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def an_invalid_request(request: Request, exc: RequestValidationError):
        # where and what, for developers; never the values sent, which may be client data
        body = problem("request.invalid", "The request's body or parameters aren't valid.")
        body["errors"] = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
        return JSONResponse(body, status_code=422, media_type=MEDIA_TYPE)


def catch_all(app: FastAPI) -> None:
    """Anything nobody planned for becomes ``system.internal`` with a reference. Added last, so it is the outermost
    middleware and nothing passes it."""

    @app.middleware("http")
    async def unplanned(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - this is the one place everything unplanned ends
            ref = reference()
            where = " < ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno} {f.name}" for f in reversed(traceback.extract_tb(exc.__traceback__)[-6:]))
            log.error("internal %s: %s %s: %s at %s", ref, request.method, request.url.path, type(exc).__name__, where)
            return answer("system.internal", ref=ref)


__all__ = ["GENERAL", "MEDIA_TYPE", "Problem", "answer", "catch_all", "general", "install", "message"]
