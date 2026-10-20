"""``GET /health`` (public: states only, never addresses or error texts) and ``GET /v1/models``."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from suveryn_harness import BackendError, LlamaServerClient, ModelInfo

from .common import StoreStatus

router = APIRouter()


class BackendStatus(BaseModel):
    """State of the model server as seen from the gateway."""

    reachable: bool
    status: str  # "ok", "loading", "error" or "unreachable"
    url: str | None = None  # not reported: /health is public (the server log has it)
    model: str | None = None
    detail: str | None = None


class DocumentsStatus(BaseModel):
    """State of document handling: "ready", "starting", "failed" or "unavailable"."""

    status: str
    detail: str | None = None


class AuthStatus(BaseModel):
    """State of sign-in: "ready", "unavailable" (Keycloak unreachable), "not_configured" or "disabled"."""

    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str  # "ok" or "degraded" (model server not ready)
    backend: BackendStatus
    documents: DocumentsStatus
    auth: AuthStatus
    history: StoreStatus
    usage: StoreStatus
    cases: StoreStatus
    directory: StoreStatus  # the office's accounts from Keycloak, to add colleagues to a case


@router.get("/health", response_model=HealthResponse,
            responses={503: {"model": HealthResponse, "description": "Model backend not ready"}})
async def health(request: Request):
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
        auth=AuthStatus(status=(await state.auth.status())[0]),
        history=state.history.status(),
        usage=state.usage.status(),
        cases=state.cases.status(),
        directory=StoreStatus(status="ready" if state.directory.configured else "unavailable"),
    )
    return JSONResponse(body.model_dump(), status_code=200 if h.status == "ok" else 503)


@router.get("/v1/models", response_model=list[ModelInfo], responses={502: {"description": "Model backend unreachable"}})
async def models(request: Request):
    """The models installed on this appliance, which one is the default, and which is loaded now.

    Choosing a model that isn't loaded makes the next answer wait while it loads (seconds when
    it was used recently, up to about half a minute otherwise), and other people's questions
    wait too: the GPU holds one model at a time.
    """
    llm: LlamaServerClient = request.app.state.llm
    try:
        return await llm.list_models()
    except BackendError as e:
        raise HTTPException(502, str(e)) from e
