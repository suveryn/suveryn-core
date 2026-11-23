"""Saved conversations (``conversations.py``): each user's own chat history, in their personal
space or in a case. Without a database: 503, and the UI keeps the conversation in memory only."""

import logging
import uuid

from fastapi import APIRouter, Request, Response
from suveryn_harness.messages import Problem, unplanned
from fastapi.concurrency import run_in_threadpool

from suveryn_harness import ChatMessage, ChatRequest, ChatService, conversation_history

from ..conversations import (
    MAX_TURN_TEXT,
    MAX_TURNS,
    Conversation,
    ConversationIn,
    ConversationSummary,
    Deleted,
    MoveIn,
    PinIn,
    RenameIn,
    QuestionIn,
    ShareIn,
    answered_turn,
    asked_turn,
    cited_documents,
    history_pairs,
    redact,
    title_of,
)
from ..problems import refusals
from .chat import Heard, StoredWhenEnded, _stream, checked
from .common import Scope, case_for, docs_or_503, flush_soon, history_or_503, log_access, owner_of, readable_case_ids, scope_of, who

log = logging.getLogger("suveryn.gateway")
router = APIRouter(tags=["conversations"])  # the group its operations are in, in the description (description.py)


def _conversation_id(conversation_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(conversation_id)
    except ValueError:
        raise Problem("request.invalid", "Not a conversation id.") from None


@router.get("/v1/conversations", response_model=list[ConversationSummary], responses=refusals(404, 422))
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


@router.get("/v1/conversations/{conversation_id}", response_model=Conversation, responses=refusals(404, 422))
async def get_conversation(conversation_id: str, request: Request):
    """One of the caller's conversations with all its turns, or one shared with a case the caller
    may read (read-only for them: saving it answers 404)."""
    store, cid = history_or_503(request), _conversation_id(conversation_id)
    found = await run_in_threadpool(store.get, cid, owner_of(request))
    if found is None:
        shared = await run_in_threadpool(store.get_shared, cid)
        if shared is None:
            raise Problem("request.not_found", "Unknown conversation.")
        try:
            await case_for(request, shared.case_id or "", "read")
        except Problem:
            raise Problem("request.not_found", "Unknown conversation.") from None  # a case they may not see: like a missing one
        found = shared
    return found


@router.post("/v1/conversations/{conversation_id}/share", response_model=ConversationSummary, responses=refusals(404, 409, 422))
async def set_conversation_shared(conversation_id: str, body: ShareIn, request: Request):
    """Share one of the caller's conversations with its case (decision 12), or stop sharing it.
    Its owner only; a shared conversation is read-only for the case's other members. Noted in the
    case's access log. A conversation in the personal space can't be shared."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    own = await run_in_threadpool(store.get, cid, owner)
    if own is None or own.case_id is None:
        raise Problem("request.not_found", "Unknown conversation, or not in a case.")
    case = await case_for(request, own.case_id, "contribute")  # sharing is a change in the case: not in a closed one
    if body.shared and case.confidential:
        raise Problem("case.strictly_confidential", "Conversations aren't shared in a strictly confidential case.")
    changed = await run_in_threadpool(store.set_shared, cid, owner, body.shared)
    if changed is None:
        raise Problem("request.not_found", "Unknown conversation.")
    await log_access(request, uuid.UUID(own.case_id), "conversation_shared" if body.shared else "conversation_unshared",
                     {"conversation": str(cid)})
    return changed


@router.patch("/v1/conversations/{conversation_id}", response_model=ConversationSummary, responses=refusals(404, 422))
async def update_conversation(conversation_id: str, body: RenameIn, request: Request):
    """Rename one of the caller's conversations (docs/design/chat-ui.md §4). The title is kept over
    later saves, which otherwise name a conversation after its first question."""
    store = history_or_503(request)
    changed = await run_in_threadpool(store.rename, _conversation_id(conversation_id), owner_of(request), body.title)
    if changed is None:
        raise Problem("request.not_found", "Unknown conversation.")
    return changed


@router.put("/v1/conversations/{conversation_id}/pin", response_model=ConversationSummary, responses=refusals(404, 409, 413, 422))
async def set_conversation_pinned(conversation_id: str, body: PinIn, request: Request):
    """Pin or unpin one of the caller's personal conversations (§3). A conversation in a case has no
    pin of its own: it follows its case. Personal, so not in any access log."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    own = await run_in_threadpool(store.get, cid, owner)
    if own is None:
        raise Problem("request.not_found", "Unknown conversation.")
    if own.case_id is not None:
        raise Problem("conversation.in_case", "A conversation in a case follows its case: pin the case instead.")
    return await run_in_threadpool(store.set_pinned, cid, owner, body.pinned)


@router.post("/v1/conversations/{conversation_id}/move", response_model=ConversationSummary, responses=refusals(404, 409, 422))
async def move_conversation(conversation_id: str, body: MoveIn, request: Request):
    """Move one of the caller's personal conversations into a case they contribute to (§4). It isn't
    shared, loses its own pin and follows the case; its questions and answers come along. Its
    documents stay in the personal space, so its next questions read the case's documents. Noted in
    the case's access log."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    own = await run_in_threadpool(store.get, cid, owner)
    if own is None:
        raise Problem("request.not_found", "Unknown conversation.")
    if own.case_id is not None:
        raise Problem("conversation.in_case", "This conversation is already in a case.")
    case = await case_for(request, body.case_id, "contribute")
    moved = await run_in_threadpool(store.move, cid, owner, uuid.UUID(case.id))
    if moved is None:
        raise Problem("conversation.in_case", "This conversation is already in a case.")
    await log_access(request, uuid.UUID(case.id), "conversation_moved_in", {"conversation": str(cid)})
    return moved


# The conversations an answer is being written in, in this process: a second question waits for it (409).
ANSWERING: set[uuid.UUID] = set()


@router.post("/v1/conversations/{conversation_id}/questions", responses={200: {"content": {"text/event-stream": {}}},
                                                                        **refusals(404, 409, 413, 422, 429)})
async def ask_in_conversation(conversation_id: str, body: QuestionIn, request: Request):
    """Ask a question in one of the caller's conversations, under an id the client chose (a UUID): a new one is
    started, in ``case_id``'s case or the personal space. The server stores the question, and the answer as it is
    written, whatever happens to it: written out, failed, or stopped when the connection closes
    (suveryn-tracker#251). What the model reads of the conversation before the question is the turns the server
    stored. Answers as ``POST /v1/chat`` streams (its events). Someone else's conversation, a playbook run's, or one
    past the office's keep period: 404; a document to show with it that isn't the caller's to see: 404; while an
    answer is being written in it, or *Regenerate* that isn't the last question asked again: 409."""
    store, cid = history_or_503(request), _conversation_id(conversation_id)
    # Taken before anything is awaited, so two requests at once (a double click on *Regenerate*, two tabs) can't both
    # pass: the second is refused, never left to take out a second question (review of #251, finding 1).
    if cid in ANSWERING:
        raise Problem("request.conflict", "An answer is being written in this conversation.")
    ANSWERING.add(cid)
    try:
        req, owner, scope = await _asked(store, cid, body, request)
    except BaseException:
        ANSWERING.discard(cid)
        raise
    heard = Heard()

    async def ended() -> None:
        try:
            text, meta = answered_turn(heard.text, heard.reasoning, heard.sources, heard.done, heard.failure)
            # A document deleted while the answer was written: its passages never stay (as a save's, audit of
            # 21 October 2026, finding 3; review of #251, finding 2). Taken out before the answer is stored, and once
            # more after, for one deleted in between.
            cited = cited_documents([meta])
            if (gone := await run_in_threadpool(_gone, request, cited, scope)) is not None:
                redact([meta], gone)
            await run_in_threadpool(store.add, cid, "assistant", "assistant", text[:MAX_TURN_TEXT], meta, cited)
            if (later := await run_in_threadpool(_gone, request, cited, scope)) is not None:
                for d in sorted(cited):
                    if later(d) and (gone is None or not gone(d)):
                        await run_in_threadpool(store.remove_document, owner, uuid.UUID(d), False, None)
        except Exception as e:  # noqa: BLE001 - the question stays, unanswered; the log has a reference, never the text
            ref, where = unplanned(e)
            log.error("an answer couldn't be stored: internal %s: %s at %s", ref, type(e).__name__, where)
        finally:
            ANSWERING.discard(cid)

    chat_service: ChatService = request.app.state.chat
    return StoredWhenEnded(_stream(chat_service, req, owner, heard), ended, media_type="text/event-stream",
                           headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _asked(store, cid: uuid.UUID, body: QuestionIn, request: Request) -> tuple[ChatRequest, str, Scope]:
    """Everything a question in a conversation is checked for, then the question stored: the request the model gets
    (what it reads of the conversation, from the stored turns, and the question), the caller, the scope."""
    place = await run_in_threadpool(store.place, cid)
    if place is not None and (place[0] != owner_of(request) or place[2]):
        raise Problem("request.not_found", "Unknown conversation.")
    case = (str(place[1]) if place[1] is not None else None) if place is not None else body.case_id
    asked = ChatRequest(messages=[ChatMessage(role="user", content=body.text)], stream=True, document_ids=body.document_ids,
                        case_id=case, model=body.model, thinking=body.thinking)
    owner = await checked(asked, request)
    scope = Scope.case(uuid.UUID(case)) if case else Scope.personal(owner)
    shown = sorted({*body.about, *body.attached})
    if shown and not await run_in_threadpool(docs_or_503(request).in_scope, shown, scope):
        raise Problem("answer.document_not_found", "Unknown document.")  # what a question shows is the caller's to see
    if place is None:
        if body.again:
            raise Problem("request.conflict", "There is no answer to ask again.")
        if not await run_in_threadpool(store.start, cid, owner, title_of(body.text), uuid.UUID(case) if case else None):
            raise Problem("request.conflict", "The conversation was started meanwhile.")
    turns = await run_in_threadpool(store.turns_of, cid)
    if body.again:
        # *Regenerate*: the last question once more, in place of its answer, as the chat UI has always done (its
        # earlier answer isn't kept). Only that question: anything else is a new question, not a regeneration.
        if len(turns) < 2 or (turns[-2].role, turns[-1].role) != ("user", "assistant") or turns[-2].text != body.text[:MAX_TURN_TEXT]:
            raise Problem("request.conflict", "There is no answer to ask again.")
        if not await run_in_threadpool(store.drop_last_answer, cid):
            raise Problem("request.conflict", "There is no answer to ask again.")
        turns = turns[:-2]
    if len(turns) + 2 > MAX_TURNS:
        raise Problem("conversation.too_long", "The conversation is too long to add to.")
    # Validated whole, so a request too long to send is refused here, never sent (``ChatRequest``'s own limits).
    req = ChatRequest.model_validate({**asked.model_dump(), "messages": [
        *(m.model_dump() for m in conversation_history(history_pairs(turns), body.text)), *(m.model_dump() for m in asked.messages)]})
    await run_in_threadpool(store.add, cid, "user", who(request)[0], body.text[:MAX_TURN_TEXT], asked_turn(body),
                            {*body.document_ids, *shown})
    return req, owner, scope


def _gone(request: Request, cited: set[str], scope: Scope):
    """Which of these documents no longer exist in ``scope``; None if that can't be known."""
    docs = request.app.state.documents
    if not cited or docs is None or docs.state != "ready":
        return None
    existing = docs.existing(sorted(cited), scope)
    return lambda d: d not in existing


@router.put("/v1/conversations/{conversation_id}", status_code=204, responses=refusals(404, 413, 422))
async def save_conversation(conversation_id: str, body: ConversationIn, request: Request):
    """Save the whole conversation under an id the client chose (a UUID): its turns' rows are brought in
    line with the body's. ``case_id`` puts a new conversation in that case (the caller must be able to
    read it); a saved conversation stays where it was first saved. A playbook run's conversation is
    written by the server, never saved over: 404."""
    store, cid, owner = history_or_503(request), _conversation_id(conversation_id), owner_of(request)
    scope = await scope_of(request, body.case_id, "read")
    gone = await run_in_threadpool(_deleted_documents, request, body, scope)
    if not await run_in_threadpool(store.save, cid, owner, body, gone, who(request)[0]):
        raise Problem("request.not_found", "Unknown conversation.")
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


@router.delete("/v1/conversations/{conversation_id}", status_code=204, responses=refusals(404, 422))
async def delete_conversation(conversation_id: str, request: Request):
    """Delete one of the caller's conversations. A playbook run's goes with its case: stop or cancel the run."""
    store, cid = history_or_503(request), _conversation_id(conversation_id)
    if not await run_in_threadpool(store.delete, cid, owner_of(request)):
        raise Problem("request.not_found", "Unknown conversation.")
    flush_soon(request.app)
    return Response(status_code=204)


@router.delete("/v1/conversations", response_model=Deleted, responses=refusals())
async def delete_my_conversations(request: Request):
    """Delete all of the caller's conversations (the "Delete history" choice when signing out)."""
    store = history_or_503(request)
    deleted = await run_in_threadpool(store.delete_all, owner_of(request))
    flush_soon(request.app)
    return {"deleted": deleted}


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
    gone = {c.owner for c in conversations if c.owner != me and (c.case_id or "", c.owner) not in names}
    departed = await run_in_threadpool(store.departed_names, list(gone)) if gone else {}  # deleted accounts keep their name
    return [c.model_copy(update={"owner_name": names.get((c.case_id or "", c.owner)) or departed.get(c.owner, "")})
            if c.owner != me else c for c in conversations]
