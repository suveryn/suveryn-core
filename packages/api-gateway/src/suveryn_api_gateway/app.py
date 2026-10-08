"""FastAPI application: chat completion (JSON or streamed) and health check.

Scope of this slice: no auth, no retrieval and no document handling in the HTTP API yet.
Because there is no auth, the gateway binds to 127.0.0.1 by default (see ``main.py``); exposing
it on a network is only safe once Keycloak integration (development context §5.2) exists.

Data handling: request and answer text pass through but are not logged by this module. Uvicorn's
access log records only method, path and status code.
"""

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from suveryn_engine import (
    BackendError, ChatRequest, ChatResponse, LLMSettings, LlamaServerClient, StreamDelta, StreamError, Usage,
)


class BackendStatus(BaseModel):
    """State of the model server as seen from the gateway."""

    reachable: bool
    status: str  # "ok", "loading", "error" or "unreachable"
    url: str
    model: str | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str  # "ok" or "degraded"
    backend: BackendStatus


def _sse(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


def create_app(client: LlamaServerClient | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``client`` lets tests inject a ``LlamaServerClient`` backed by a fake server; in production
    it is created from environment variables when the app starts.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.llm = client or LlamaServerClient(LLMSettings.from_env())
        yield
        await app.state.llm.aclose()

    # FastAPI's /docs and /redoc pages load scripts, styles and fonts from public CDNs, which breaks
    # air-gapped installs and contacts third parties. Off unless explicitly enabled for development.
    # The OpenAPI schema itself (/openapi.json) is served locally and stays available.
    docs = os.environ.get("SUVERYN_API_DOCS") == "1"
    app = FastAPI(title="Sūveryn API", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs" if docs else None, redoc_url=None)

    @app.get("/health", response_model=HealthResponse,
             responses={503: {"model": HealthResponse, "description": "Model backend not ready"}})
    async def health(request: Request):
        """Report whether the model server is reachable and ready, and which model it serves.

        200 when ready; 503 while the model is loading, on a server error, or when the server
        can't be reached. Suitable as a readiness probe.
        """
        llm: LlamaServerClient = request.app.state.llm
        h = await llm.health()
        body = HealthResponse(
            status="ok" if h.status == "ok" else "degraded",
            backend=BackendStatus(reachable=h.reachable, status=h.status, url=llm.settings.base_url,
                                  model=h.model, detail=h.detail),
        )
        return JSONResponse(body.model_dump(), status_code=200 if h.status == "ok" else 503)

    @app.post("/v1/chat", response_model=ChatResponse, responses={
        200: {"content": {"text/event-stream": {}},
              "description": "With stream=true: SSE events `delta` ({text}), then `done` (a full ChatResponse) "
                             "or `error` ({message})."},
        502: {"description": "Model backend unreachable or returned an error"},
    })
    async def chat(req: ChatRequest, request: Request):
        """Answer a conversation with the served model.

        Answers are not grounded in documents yet: ``citations`` is always empty, so every
        answer from this endpoint is unsourced and must be shown as unverified.
        """
        llm: LlamaServerClient = request.app.state.llm
        if not req.stream:
            try:
                return await llm.complete(req)
            except BackendError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
        return StreamingResponse(_stream(llm, req), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


async def _stream(llm: LlamaServerClient, req: ChatRequest) -> AsyncIterator[str]:
    """Translate the backend stream into the gateway's SSE contract.

    Event order: zero or more ``delta`` events, then exactly one of ``done`` (a complete
    ``ChatResponse``, the same shape as the JSON answer) or ``error``. A client that saw
    ``delta`` events followed by ``error`` must discard the partial answer.
    """
    parts: list[str] = []
    finish_reason, usage = None, Usage()
    try:
        async for chunk in llm.stream(req):
            if chunk.text:
                parts.append(chunk.text)
                yield _sse("delta", StreamDelta(text=chunk.text))
            finish_reason = chunk.finish_reason or finish_reason
            usage = chunk.usage or usage
    except (BackendError, json.JSONDecodeError) as e:
        yield _sse("error", StreamError(message=str(e)))
        return
    yield _sse("done", ChatResponse(id=f"chat-{uuid.uuid4().hex}", model=await llm.model_name(),
                                    answer="".join(parts), citations=[], finish_reason=finish_reason, usage=usage))


app = create_app()
