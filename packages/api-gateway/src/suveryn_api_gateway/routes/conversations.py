"""Saved conversations (``conversations.py``): each user's own chat history, in their personal
space or in a case. Without a database: 503, and the UI keeps the conversation in memory only."""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..conversations import MAX_BODY_BYTES as MAX_CONVERSATION_BYTES
from ..conversations import (
    Conversation,
    ConversationIn,
    ConversationSummary,
    cited_documents,
)
from .common import Scope, history_or_503, owner_of, scope_of

router = APIRouter()


def _conversation_id(conversation_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(422, "Not a conversation id.") from None


@router.get("/v1/conversations", response_model=list[ConversationSummary])
async def list_conversations(request: Request, case: str | None = None):
    """The caller's saved conversations in their personal space, or in the case ``case``, most
    recently changed first (titles and dates, no content)."""
    store = history_or_503(request)
    scope = await scope_of(request, case, "read")
    return await run_in_threadpool(store.summaries, owner_of(request), scope.case_id)


@router.get("/v1/conversations/{conversation_id}", response_model=Conversation,
            responses={404: {"description": "Unknown, expired or another user's conversation"}})
async def get_conversation(conversation_id: str, request: Request):
    """One of the caller's conversations with all its turns."""
    store, cid = history_or_503(request), _conversation_id(conversation_id)
    found = await run_in_threadpool(store.get, cid, owner_of(request))
    if found is None:
        raise HTTPException(404, "Unknown conversation.")
    return found


@router.put("/v1/conversations/{conversation_id}", status_code=204, responses={
    404: {"description": "The id belongs to another user's conversation"},
    413: {"description": f"Larger than {MAX_CONVERSATION_BYTES // (1024 * 1024)} MB"}})
async def save_conversation(conversation_id: str, body: ConversationIn, request: Request):
    """Save the whole conversation under an id the client chose (a UUID), replacing an earlier save.
    ``case_id`` puts a new conversation in that case (the caller must be able to read it); a
    saved conversation stays where it was first saved."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    scope = await scope_of(request, body.case_id, "read")
    gone = await run_in_threadpool(_deleted_documents, request, body, scope)
    if not await run_in_threadpool(store.save, cid, owner, body, gone):
        raise HTTPException(404, "Unknown conversation.")
    return Response(status_code=204)


def _deleted_documents(request: Request, body: ConversationIn, scope: Scope):
    """Which documents the conversation cites that no longer exist (suveryn-tracker#12): a tab that
    was open while one was deleted must not save its passages back. None if that can't be known."""
    docs = request.app.state.documents
    if docs is None or docs.state != "ready":
        return None
    cited = cited_documents([t.model_dump() for t in body.turns])
    valid = []
    for d in cited:
        try:
            valid.append(str(uuid.UUID(d)))
        except ValueError:
            continue
    existing = docs.existing(valid, scope) if valid else set()
    return lambda d: d not in existing


@router.delete("/v1/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request):
    """Delete one of the caller's conversations."""
    store, cid = history_or_503(request), _conversation_id(conversation_id)
    if not await run_in_threadpool(store.delete, cid, owner_of(request)):
        raise HTTPException(404, "Unknown conversation.")
    return Response(status_code=204)


@router.delete("/v1/conversations")
async def delete_all_conversations(request: Request):
    """Delete all of the caller's conversations (the "Delete history" choice when signing out)."""
    store = history_or_503(request)
    return {"deleted": await run_in_threadpool(store.delete_all, owner_of(request))}
