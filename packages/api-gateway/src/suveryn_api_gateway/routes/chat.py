"""``POST /v1/chat``: an answer, plain or grounded in documents, as JSON or streamed (SSE).

Data handling: request, answer and document text pass through but are not logged here. An
unexpected error during a streamed answer is reported to the client as a generic ``error`` event
and logged by exception type only, because exception messages can contain document text.
"""

import logging
import uuid
from contextlib import aclosing

import anyio
from fastapi import APIRouter, Request
from suveryn_harness.messages import Problem, message, unplanned
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
    StreamThinking,
    Thinking,
)

from ..problems import refusals
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
router = APIRouter(tags=["answers"])  # the group its operations are in, in the description (description.py)


# The events of a streamed answer, by name, each with the shape of its data: the list the stream is described by.
# ``_stream`` writes them and says their order; the test that walks an answer fails on an event this list doesn't name.
EVENTS: dict[str, type[BaseModel]] = {"status": StreamStatus, "sources": StreamSources, "thinking": StreamThinking, "delta": StreamDelta,
                                      "done": ChatResponse, "error": StreamError}


def events_described(description: dict) -> dict:
    """The description with the answer stream's events in it: under ``text/event-stream``, what one event is
    (``itemSchema``, OpenAPI 3.2's place for it, where FastAPI puts it for its own event streams): its name, and its
    data as JSON of that event's shape (``contentSchema``). FastAPI describes what a route returns; a stream written
    by hand it can't, so this does. The chat UI's generator reads OpenAPI 3.1 and is handed the same under
    ``schema`` (packages/chat-ui/orval.config.ts)."""
    from pydantic.json_schema import models_json_schema

    place = "#/components/schemas/{model}"
    _, shapes = models_json_schema([(model, "serialization") for model in EVENTS.values()], ref_template=place)
    known = description.setdefault("components", {}).setdefault("schemas", {})
    for name, shape in shapes.get("$defs", {}).items():
        known.setdefault(name, shape)
    one = [{"type": "object", "title": f"{name} event", "required": ["event", "data"], "properties": {
        "event": {"type": "string", "const": name},
        "data": {"type": "string", "contentMediaType": "application/json", "contentSchema": {"$ref": place.format(model=model.__name__)}}}}
        for name, model in EVENTS.items()]
    answered = description["paths"]["/v1/chat"]["post"]["responses"]["200"]
    answered["description"] = ("The answer. With stream=true, as events: zero or more `status`, for a grounded answer one `sources`, with "
                               "`thinking` true and a model that can think zero or more `thinking`, zero or more `delta`, then one `done` "
                               "(the whole answer) or one `error`. Closing the connection stops the answer: the model stops writing.")
    answered["content"]["text/event-stream"] = {"itemSchema": {"oneOf": one, "title": "One event of the answer stream"}}
    return description


@router.post("/v1/chat", response_model=ChatResponse, responses={200: {"content": {"text/event-stream": {}}}, **refusals(404, 422, 429)})
async def ask_question(req: ChatRequest, request: Request):
    """Answer a conversation. With ``document_ids``, ground the answer in those documents.

    Grounded answers cite passages as [n], where [n] is ``citations[n-1]``. Without
    ``document_ids`` the answer is unsourced (``citations: []``) and must be shown as unverified.
    """
    for d in req.document_ids:
        try:
            uuid.UUID(d)
        except ValueError:
            raise Problem("request.invalid", f"Not a document id: {d!r}") from None
    if req.model is not None:
        try:
            installed = {m.id for m in await request.app.state.llm.list_models()}
        except BackendError as e:
            raise Problem("model.unavailable", str(e)) from e
        if req.model not in installed:
            raise Problem("model.not_found", f"No such model on this appliance: {req.model!r}")
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
            raise Problem("answer.document_not_found", "Unknown document.")
        await touch_case(request, scope)
    await log_access(request, scope.case_id, "asked", {"documents": req.document_ids})
    chat_service: ChatService = request.app.state.chat
    if not req.stream:
        try:
            return await chat_service.answer(req, owner)
        except DocumentNotFound as e:
            raise Problem("answer.document_not_found", "Unknown document.") from e
        except DocumentsUnavailable as e:
            raise Problem("document.unavailable", str(e)) from e
        except BackendError as e:
            raise Problem("model.unavailable", str(e)) from e
    return StopOnDisconnect(_stream(chat_service, req, owner), media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class StopOnDisconnect(StreamingResponse):
    """A streamed answer that stops as soon as the client goes: the person pressed *Stop*, started a new
    chat or closed the tab (docs/design/chat-ui.md §5).

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
    loading_model, reading, writing, thinking), for a grounded answer one ``sources`` event (its passages, so a
    stopped answer keeps what its markers point to), in *Thorough* zero or more ``thinking`` events (the
    reasoning, never part of the answer), zero or more ``delta`` events, then exactly one of ``done`` (a complete
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
                elif isinstance(event, Thinking):
                    yield _sse("thinking", StreamThinking(text=event.text))
                elif isinstance(event, Delta):
                    yield _sse("delta", StreamDelta(text=event.text))
                elif isinstance(event, Done):
                    yield _sse("done", event.response)
    except BackendError as e:
        # What failed, without what the model server said back (it may quote the prompt): round 4, finding 3.
        # An answer that can't be read isn't the model being down: it falls to the unplanned failure below (#164).
        what = str(e).split(":", 1)[0]
        cause = f" ({type(e.__cause__).__name__})" if e.__cause__ else ""
        log.warning("chat stream failed: %s%s, model %s", what, cause, req.model or "default")
        yield _sse("error", StreamError(**message("model.unavailable"), detail=what))
    except DocumentsUnavailable as e:
        log.warning("chat stream failed: the documents aren't available (%s)", type(e).__name__)
        yield _sse("error", StreamError(**message("document.unavailable"), detail=str(e)))
    except DocumentNotFound:
        yield _sse("error", StreamError(**message("answer.document_not_found"), detail="unknown document"))
    except Exception as e:  # noqa: BLE001 - the stream must end with an event; the client discards the partial answer
        # Nobody planned for it: a reference for the person, and the log line under it. The exception's type and where
        # it was raised, never its message, which may hold document text (the decision of 12 November, rule 5).
        ref, where = unplanned(e)
        log.error("chat stream failed: internal %s: %s at %s", ref, type(e).__name__, where)
        yield _sse("error", StreamError(**message("system.internal", ref=ref), detail="the answer couldn't be completed because of a server error"))
