"""How the gateway answers when it doesn't give the answer asked for: Problem Details (RFC 9457,
``application/problem+json``) with a code of the registry of messages (``suveryn_harness.messages``; the handbook's
decision of 12 November 2026, *Messages are codes*; docs/design/messages.md).

Three ways an answer becomes a problem, and one shape for all:

- a ``Problem`` raised anywhere (the one way new code refuses): its own code and parameters;
- a plain ``HTTPException``, which only the framework raises (an unknown address; ``tests/test_problems.py`` fails on
  one anywhere in the gateway): the general code for its status (the registry's ``general``), its English detail kept
  for developers;
- anything nobody planned for: ``system.internal`` with a reference. The log has the reference, the exception's
  type and where it was raised, never its message, which may quote a document.

The page words the code in its reader's language and never shows ``title`` or ``detail``.

The description says so too, for the operations that have moved (suveryn-tracker#159, #236): a route passes
``responses=problems.refusals(...)`` and the description then gives, for every status it can answer instead of its
answer, the one shape below, as ``application/problem+json``.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from suveryn_harness.messages import Problem, general, loggable, message, problem, unplanned

log = logging.getLogger("suveryn.gateway")

MEDIA_TYPE = "application/problem+json"
# What any ``/v1`` operation can answer before its own code runs (app.py's ``require_sign_in`` and the handlers
# there): signed out; another site's request, or not an administrator; nobody planned for it; sign-in or the
# database down.
EVERY_OPERATION = (401, 403, 500, 503)


class Message(BaseModel):
    """A message as it travels inside an answer: a code of the registry, its kind and its values."""

    kind: Literal["refused", "unavailable", "internal", "warning"]
    code: str
    params: dict[str, str | int | float | None]


class InvalidPart(BaseModel):
    """Where a request wasn't valid and why, for developers: never the value sent."""

    loc: list[str | int]
    msg: str
    type: str


class ProblemDetails(Message):
    """What the gateway answers instead of the answer asked for (RFC 9457): the standard members, and the message's."""

    type: str
    title: str
    status: int
    detail: str
    errors: list[InvalidPart] | None = None  # with ``request.invalid`` only


def refusals(*statuses: int, signed_in: bool = True) -> dict:
    """``responses=`` for a route whose refusals are described: the statuses of the codes its own code raises, and
    the ones every operation can answer. ``described`` gives them their media type, and the status of a request
    that isn't valid, which FastAPI adds by itself in a shape the gateway doesn't answer. ``signed_in=False`` for
    an operation outside ``/v1``, which nothing guards: only what nobody planned for."""
    return {status: {"model": ProblemDetails} for status in sorted({*(EVERY_OPERATION if signed_in else (500,)), *statuses})}


def described(description: dict) -> dict:
    """The description with every answer in the one shape under the media type it is sent as, and, on an operation
    that describes its refusals, an invalid request in that shape too."""
    ours = {"$ref": "#/components/schemas/ProblemDetails"}
    for by_method in description.get("paths", {}).values():
        for operation in by_method.values():
            responses = operation.get("responses", {})
            if not any(r.get("content", {}).get("application/json", {}).get("schema") == ours for r in responses.values()):
                continue
            if "422" in responses:
                responses["422"] = {"description": responses["422"].get("description", "Unprocessable Content"),
                                    "content": {"application/json": {"schema": dict(ours)}}}
            for response in responses.values():
                content = response.get("content", {})
                if content.get("application/json", {}).get("schema") == ours:
                    content[MEDIA_TYPE] = content.pop("application/json")
    return description


def answer(code: str, detail: str = "", status: int | None = None, headers: dict[str, str] | None = None, **params) -> JSONResponse:
    """The Problem Details answer for a code."""
    body = problem(code, detail, status, **params)
    return JSONResponse(body, status_code=body["status"], headers=headers, media_type=MEDIA_TYPE)


def install(app: FastAPI) -> None:
    """The handlers that give every refusal and failure the one shape. Called first when the app is made, so the
    catch-all is the outermost middleware."""
    built = app.openapi

    def openapi() -> dict:
        if app.openapi_schema is None:
            described(built())
        return app.openapi_schema

    app.openapi = openapi

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
    async def nobody_planned(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - this is the one place everything unplanned ends
            ref, where = unplanned(exc)
            log.error("internal %s: %s %s: %s at %s", ref, request.method, request.url.path, type(exc).__name__, where)
            return answer("system.internal", ref=ref)


__all__ = ["MEDIA_TYPE", "Problem", "answer", "catch_all", "general", "install", "message"]
