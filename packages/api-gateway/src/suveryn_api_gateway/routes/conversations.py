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
    MoveIn,
    PinIn,
    RenameIn,
    ShareIn,
    cited_documents,
)
from .common import Scope, case_for, history_or_503, log_access, owner_of, readable_case_ids, scope_of

router = APIRouter()


def _conversation_id(conversation_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(422, "Not a conversation id.") from None


@router.get("/v1/conversations", response_model=list[ConversationSummary])
async def list_conversations(request: Request, case: str | None = None, all: bool = False):
    """The caller's saved conversations in their personal space, or in the case ``case`` their own
    and the ones its members shared (``shared``, ``owner``), most recently changed first (titles
    and dates, no content). With ``all``: every one of their own, across the cases they may read
    and their personal space (the sidebar's list, docs/design/chat-ui.md)."""
    store = history_or_503(request)
    if all:
        owner, case_ids = owner_of(request), await readable_case_ids(request)
        found = await run_in_threadpool(store.summaries_all, owner, case_ids)
        return shielded(request, await with_owner_names(request, found, owner), await confidential_cases(request, found))
    scope = await scope_of(request, case, "read")
    return await run_in_threadpool(store.summaries, owner_of(request), scope.case_id)


@router.get("/v1/conversations/{conversation_id}", response_model=Conversation,
            responses={404: {"description": "Unknown, expired or another user's conversation"}})
async def get_conversation(conversation_id: str, request: Request):
    """One of the caller's conversations with all its turns, or one shared with a case the caller
    may read (read-only for them: saving it answers 404)."""
    store, cid = history_or_503(request), _conversation_id(conversation_id)
    found = await run_in_threadpool(store.get, cid, owner_of(request))
    if found is None:
        shared = await run_in_threadpool(store.get_shared, cid)
        if shared is None:
            raise HTTPException(404, "Unknown conversation.")
        try:
            await case_for(request, shared.case_id or "", "read")
        except HTTPException:
            raise HTTPException(404, "Unknown conversation.") from None  # a case they may not see: like a missing one
        found = shared
    return found


@router.post("/v1/conversations/{conversation_id}/share", response_model=ConversationSummary, responses={
    403: {"description": "The case is closed, or the caller may not contribute to it"},
    404: {"description": "Not the caller's conversation, or not in a case"},
    409: {"description": "The case is strictly confidential"}})
async def share_conversation(conversation_id: str, body: ShareIn, request: Request):
    """Share one of the caller's conversations with its case (decision 12), or stop sharing it.
    Its owner only; a shared conversation is read-only for the case's other members. Noted in the
    case's access log. A conversation in the personal space can't be shared."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    own = await run_in_threadpool(store.get, cid, owner)
    if own is None or own.case_id is None:
        raise HTTPException(404, "Unknown conversation, or not in a case.")
    case = await case_for(request, own.case_id, "contribute")  # sharing is a change in the case: not in a closed one
    if body.shared and case.confidential:
        raise HTTPException(409, "Conversations aren't shared in a strictly confidential case.")
    changed = await run_in_threadpool(store.set_shared, cid, owner, body.shared)
    if changed is None:
        raise HTTPException(404, "Unknown conversation.")
    await log_access(request, uuid.UUID(own.case_id), "conversation_shared" if body.shared else "conversation_unshared",
                     {"conversation": str(cid)})
    return changed


@router.patch("/v1/conversations/{conversation_id}", response_model=ConversationSummary, responses={
    404: {"description": "Not the caller's conversation"}})
async def rename_conversation(conversation_id: str, body: RenameIn, request: Request):
    """Rename one of the caller's conversations (docs/design/chat-ui.md §4). The title is kept over
    later saves, which otherwise name a conversation after its first question."""
    store = history_or_503(request)
    changed = await run_in_threadpool(store.rename, _conversation_id(conversation_id), owner_of(request), body.title)
    if changed is None:
        raise HTTPException(404, "Unknown conversation.")
    return changed


@router.put("/v1/conversations/{conversation_id}/pin", response_model=ConversationSummary, responses={
    404: {"description": "Not the caller's conversation"}, 409: {"description": "In a case: the case is pinned instead"}})
async def pin_conversation(conversation_id: str, body: PinIn, request: Request):
    """Pin or unpin one of the caller's personal conversations (§3). A conversation in a case has no
    pin of its own: it follows its case. Personal, so not in any access log."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    own = await run_in_threadpool(store.get, cid, owner)
    if own is None:
        raise HTTPException(404, "Unknown conversation.")
    if own.case_id is not None:
        raise HTTPException(409, "A conversation in a case follows its case: pin the case instead.")
    return await run_in_threadpool(store.set_pinned, cid, owner, body.pinned)


@router.post("/v1/conversations/{conversation_id}/move", response_model=ConversationSummary, responses={
    403: {"description": "The caller may not contribute to the case, or it is closed"},
    404: {"description": "Not the caller's conversation, or an unknown case"},
    409: {"description": "Already in a case"}})
async def move_conversation(conversation_id: str, body: MoveIn, request: Request):
    """Move one of the caller's personal conversations into a case they contribute to (§4). It isn't
    shared, loses its own pin and follows the case; its questions and answers come along. Its
    documents stay in the personal space, so its next questions read the case's documents. Noted in
    the case's access log."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    own = await run_in_threadpool(store.get, cid, owner)
    if own is None:
        raise HTTPException(404, "Unknown conversation.")
    if own.case_id is not None:
        raise HTTPException(409, "This conversation is already in a case.")
    case = await case_for(request, body.case_id, "contribute")
    moved = await run_in_threadpool(store.move, cid, owner, uuid.UUID(case.id))
    if moved is None:
        raise HTTPException(409, "This conversation is already in a case.")
    await log_access(request, uuid.UUID(case.id), "conversation_moved_in", {"conversation": str(cid)})
    return moved


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
    # A document deleted while this save was on its way (after the check above, before its cleaning
    # could see this save) is taken out now: its passages never stay (audit of 21 October 2026, finding 3).
    if (later := await run_in_threadpool(_deleted_documents, request, body, scope)) is not None:
        for d in cited_documents([t.model_dump() for t in body.turns]):
            try:
                did = uuid.UUID(d)
            except ValueError:
                continue
            if later(str(did)) and (gone is None or not gone(str(did))):
                await run_in_threadpool(store.remove_document, owner, did, False, None)
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


async def confidential_cases(request: Request, conversations: list[ConversationSummary]) -> set[str]:
    """The strictly confidential cases among these conversations' cases (docs/design/chat-ui.md §11)."""
    ids = {uuid.UUID(c.case_id) for c in conversations if c.case_id}
    db = request.app.state.cases
    store = db.get() if db.configured else None
    if not ids or store is None:
        return set()
    return await run_in_threadpool(store.confidential_ids, list(ids))


def shielded(request: Request, conversations: list[ConversationSummary], confidential: set[str]) -> list[ConversationSummary]:
    """The lists that span cases show a strictly confidential case's conversations without their
    title: someone looking over a shoulder at Recent sees only that one exists, in which case. The
    case's own list keeps the titles (it is open, and only its members see it)."""
    return [c.model_copy(update={"title": None, "shielded": True}) if c.case_id in confidential else c
            for c in conversations]


async def with_owner_names(request: Request, conversations: list[ConversationSummary], me: str) -> list[ConversationSummary]:
    """A colleague's shared conversation with their name as its case knows it (the Conversations
    overview's "From", docs/design/chat-ui.md §4); the caller's own stay without one."""
    others = {uuid.UUID(c.case_id) for c in conversations if c.owner != me and c.case_id}
    db = request.app.state.cases
    store = db.get() if db.configured else None
    if not others or store is None:
        return conversations
    members = await run_in_threadpool(store.members_of, list(others))
    names = {(str(cid), m.user): m.name or m.username for cid, ms in members.items() for m in ms}
    return [c.model_copy(update={"owner_name": names.get((c.case_id or "", c.owner), "")}) if c.owner != me else c
            for c in conversations]
