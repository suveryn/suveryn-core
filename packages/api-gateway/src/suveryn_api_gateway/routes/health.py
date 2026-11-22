"""``GET /health`` (public: states only, never addresses or error texts) and ``GET /v1/models``."""

from typing import Literal

from fastapi import APIRouter, Request
from suveryn_harness.messages import Problem
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from suveryn_harness import BackendError, BackendState, LlamaServerClient, ModelInfo

from ..description import Answer
from ..problems import refusals
from .common import StoreStatus, signin_status

router = APIRouter(tags=["status"])  # the group its operations are in, in the description (description.py)
models_routes = APIRouter(tags=["models"])  # the installed models: a group of their own (Administration's Updates and models joins it)
routers = (router, models_routes)


class BackendStatus(Answer):
    """State of the model server as seen from the gateway."""

    reachable: bool
    status: BackendState
    url: str | None = None  # not reported: /health is public (the server log has it)
    model: str | None = None
    detail: str | None = None


class DocumentsStatus(Answer):
    """State of document handling: the rag service's own three (its ``state``; the rag is an optional package, so
    its states are repeated here), and "unavailable" where there is none."""

    status: Literal["ready", "starting", "failed", "unavailable"]
    detail: str | None = None


class AuthStatus(Answer):
    """State of sign-in: "unavailable" (Keycloak unreachable, or it can't sign anyone in), "not_configured" or
    "disabled" (development only)."""

    status: Literal["ready", "unavailable", "not_configured", "disabled"]
    detail: str | None = None


class HealthResponse(Answer):
    """Body of ``GET /health``."""

    status: Literal["ok", "degraded"]  # degraded: the model server isn't ready
    backend: BackendStatus
    documents: DocumentsStatus
    auth: AuthStatus
    history: StoreStatus
    usage: StoreStatus
    cases: StoreStatus
    directory: StoreStatus  # the office's accounts from Keycloak, to add colleagues to a case


@router.get("/health", response_model=HealthResponse,
            responses={**refusals(signed_in=False), 503: {"model": HealthResponse, "description": "Model backend not ready"}})
async def get_health(request: Request):
    """Report whether the model server is ready (and which model it serves) and whether documents work.

    200 when the model server is ready; 503 while it loads, fails or can't be reached. The
    ``documents`` part doesn't affect the status code: chat works without it. Public (no sign-in),
    so it gives states only: no internal addresses or error texts (those are in the server log).
    """
    state = request.app.state
    llm: LlamaServerClient = state.llm
    h = await llm.health()
    docs = state.documents
    body = HealthResponse(
        status="ok" if h.status == "ok" else "degraded",
        backend=BackendStatus(reachable=h.reachable, status=h.status, model=h.model),
        documents=DocumentsStatus(status="unavailable" if docs is None else docs.state),
        auth=AuthStatus(status=(await signin_status(state))[0]),
        # each asks the database (a SELECT 1), so not on the event loop
        history=await run_in_threadpool(state.history.status),
        usage=await run_in_threadpool(state.usage.status),
        cases=await run_in_threadpool(state.cases.status),
        directory=StoreStatus(status="ready" if state.directory.configured else "unavailable"),
    )
    return JSONResponse(body.model_dump(), status_code=200 if h.status == "ok" else 503)


@models_routes.get("/v1/models", response_model=list[ModelInfo], responses=refusals())
async def list_models(request: Request):
    """The models installed on this appliance, which one is the default, and which is loaded now.

    Choosing a model that isn't loaded makes the next answer wait while it loads (seconds when
    it was used recently, up to about half a minute otherwise), and other people's questions
    wait too: the GPU holds one model at a time.
    """
    llm: LlamaServerClient = request.app.state.llm
    try:
        return await llm.list_models()
    except BackendError as e:
        raise Problem("model.unavailable", str(e)) from e
