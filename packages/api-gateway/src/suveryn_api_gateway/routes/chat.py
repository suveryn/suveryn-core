"""``POST /v1/chat``: an answer, plain or grounded in documents, as JSON or streamed (SSE).

Data handling: request, answer and document text pass through but are not logged here. An
unexpected error during a streamed answer is reported to the client as a generic ``error`` event
and logged by exception type only, because exception messages can contain document text.
"""

import json
import logging
import uuid
from contextlib import aclosing

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from suveryn_harness import (
    BackendError,
    ChatRequest,
    ChatResponse,
    ChatService,
    Delta,
    DocumentsUnavailable,
    Done,
    Sources,
    Status,
    StreamDelta,
    StreamError,
    StreamSources,
    StreamStatus,
)

from .common import (
    DocumentNotFound,
    docs_or_503,
    log_access,
    owner_of,
    remember_user,
    scope_of,
    touch_case,
)

log = logging.getLogger("suveryn.gateway")
router = APIRouter()


@router.post("/v1/chat", response_model=ChatResponse, responses={
    200: {"content": {"text/event-stream": {}},
          "description": "With stream=true: SSE events `status` ({step, ...}), for a grounded answer `sources` ({citations}), "
                         "`delta` ({text}), then `done` (a full ChatResponse) or `error` ({message}). Closing the connection "
                         "stops the answer: the model stops writing."},
    404: {"description": "A document id doesn't exist or belongs to another user"},
    422: {"description": "Invalid request, e.g. a malformed document id"},
    502: {"description": "Model backend unreachable or returned an error"},
    503: {"description": "Grounded answer requested but document search is unavailable"},
})
async def chat(req: ChatRequest, request: Request):
    """Answer a conversation. With ``document_ids``, ground the answer in those documents.

    Grounded answers cite passages as [n], where [n] is ``citations[n-1]``. Without
    ``document_ids`` the answer is unsourced (``citations: []``) and must be shown as unverified.
    """
    for d in req.document_ids:
        try:
            uuid.UUID(d)
        except ValueError:
            raise HTTPException(422, f"Not a document id: {d!r}") from None
    if req.model is not None:
        try:
            installed = {m.id for m in await request.app.state.llm.list_models()}
        except BackendError as e:
            raise HTTPException(502, str(e)) from e
        if req.model not in installed:
            raise HTTPException(422, f"No such model on this appliance: {req.model!r}")
    owner = owner_of(request)
    await remember_user(request)
    # The case the question is about, if any: asking is a contributor's right (a reader may only
    # read; 404 for a case the caller may not see at all).
    scope = await scope_of(request, req.case_id, "contribute")
    if req.document_ids:
        # Before anything streams: only documents in that scope, and only uploaded ones (sūveryn's
        # own output is never a source). An id elsewhere is answered like a missing one. The
        # retriever checks again when it reads the passages.
        docs = docs_or_503(request)
        if not await run_in_threadpool(docs.in_scope, req.document_ids, scope, True):
            raise HTTPException(404, "Unknown document.")
        await touch_case(request, scope)
    await log_access(request, scope.case_id, "asked", {"documents": req.document_ids})
    chat_service: ChatService = request.app.state.chat
    if not req.stream:
        try:
            return await chat_service.answer(req, owner)
        except DocumentNotFound as e:
            raise HTTPException(404, "Unknown document.") from e
        except DocumentsUnavailable as e:
            raise HTTPException(503, str(e)) from e
        except BackendError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
    return StopOnDisconnect(_stream(chat_service, req, owner), media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class StopOnDisconnect(StreamingResponse):
    """A streamed answer that stops as soon as the client goes: the person pressed *Stop*, started a new
    chat or closed the tab (docs/design/sidebar.md §5).

    Starlette notices a closed connection only when it next sends something (ASGI 2.4); before the first
    word, while the model reads the passages, that can be half a minute of the GPU for nobody. So the
    connection is watched from the start, and the stream is cancelled the moment it closes: the chat
    service's generator is closed, which closes the connection to llama-server, which stops generating.
    """

    async def __call__(self, scope, receive, send) -> None:
        async with anyio.create_task_group() as group:

            async def stream() -> None:
                try:
                    await self.stream_response(send)
                except OSError:
                    pass  # the client went while a chunk was being sent: as a disconnect
                group.cancel_scope.cancel()

            group.start_soon(stream)
            await self.listen_for_disconnect(receive)
            group.cancel_scope.cancel()


def _sse(event: str, payload: BaseModel) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


async def _stream(chat_service: ChatService, req: ChatRequest, owner: str):
    """Translate the chat service's events into the gateway's SSE contract.

    Event order: zero or more ``status`` events (pipeline steps before the first word: searching,
    loading_model, reading, writing), for a grounded answer one ``sources`` event (its passages, so a
    stopped answer keeps what its markers point to), zero or more ``delta`` events, then exactly one of ``done`` (a complete
    ``ChatResponse``, the same shape as the JSON answer, with citations) or ``error``. A client
    that saw ``delta`` events followed by ``error`` must discard the partial answer.
    """
    try:
        async with aclosing(chat_service.answer_stream(req, owner)) as events:
            async for event in events:
                if isinstance(event, Status):
                    yield _sse("status", StreamStatus(step=event.step, passages=event.passages,
                                                      complete=event.complete, model=event.model))
                elif isinstance(event, Sources):
                    yield _sse("sources", StreamSources(citations=event.citations))
                elif isinstance(event, Delta):
                    yield _sse("delta", StreamDelta(text=event.text))
                elif isinstance(event, Done):
                    yield _sse("done", event.response)
    except (BackendError, DocumentsUnavailable, json.JSONDecodeError) as e:
        yield _sse("error", StreamError(message=str(e)))
    except DocumentNotFound:
        yield _sse("error", StreamError(message="unknown document"))
    except Exception as e:  # noqa: BLE001 - the stream must end with an event; the client discards the partial answer
        log.error("chat stream failed: %s", type(e).__name__)  # the message may contain document text
        yield _sse("error", StreamError(message="the answer couldn't be completed because of a server error"))
