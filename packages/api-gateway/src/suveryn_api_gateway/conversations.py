"""Saved conversations (suveryn-tracker#5): each user's chat history, kept on this server.

A conversation is a row in ``conversations`` under the owner's Keycloak id, and its turns are rows in
``turns``, one each (questions, answers with their citations and calculations, attachment names):
the words in ``text``, the rest of what the server wrote beside them in ``meta``. It never reads the text.

Cases (suveryn-tracker#10): a conversation started in a case carries its ``case_id`` and is listed
with that case; one without is in the owner's personal space. Either way it is private to whoever
started it, unless its owner **shares** it with the case (decision 12, stage 4): a shared
conversation is listed for and readable by everyone who may read the case, read-only for them
(only the owner asks in it, shares, unshares or deletes it). The gateway checks the right in the case;
the store only knows ``shared``.

Retention: kept until the user deletes it (one conversation, or all of them when signing out), or
until the office's keep period for conversations passes (the data lifecycle, suveryn-tracker#31):
``SUVERYN_CONVERSATIONS_KEEP`` as provisioned (``6m``, ``1y``, ``5y`` or ``manual``, the default:
nothing is chosen for the office), changed by an administrator in Administration › Settings
(``conversations_keep`` in ``case_settings``). The gateway tells the store the period that applies
(``keep``); conversations older than it, by last change and in cases too, are hidden from lists and
no longer returned at once, and are deleted on start, when the setting is saved and by the hourly
sweep.

Deleted documents (suveryn-tracker#12): saved answers quote the passages they cite. When a
document is deleted, every passage of it is taken out of the owner's conversations
(``remove_document``): its text and its location (headings are document text too) are emptied and
the citation is marked ``removed``; attachments of the document, and its place in a question's *Ask
about* choice, lose their file name the same way.
The answers themselves stay, and still state facts from the document, so the UI offers to delete
those conversations together with the document (``using_document``).

**Turns, one row each** (``turns``; docs/design/playbooks.md, "The thread"). A thread several people
write in can't be one blob the browser writes whole: the last save wins and the others' lines are
gone, and a blob says neither who wrote a line nor when. So every turn is a row, stamped with who
and when, appended by the server (``TurnStore.append``): nothing is saved whole.

**The server stores each turn as it answers** (suveryn-tracker#251): a question asked in a conversation
(``POST /v1/conversations/{id}/questions``) is stored, the model reads what was stored on the way to it
(``path_to``, ``history_pairs``, ``suveryn_harness.conversation_history``), and the answer is stored as it was
written, however it ends (``answered_turn``): written out with its checks, failed (no words, the code), or stopped
(the words so far, unchecked). So an answer a colleague opens is the one the model wrote, and the browser can't hand
the model an answer it never gave. Such a turn says ``kind`` (question, answer) in ``meta`` (``AskedTurn``,
``AnsweredTurn``) and names documents by id only (``narrowed_to`` too), so a deleted one leaves no name; a document
deleted while an answer is written is taken out of it as it is stored.

**A conversation is a tree**, as in Claude and ChatGPT: each turn the server writes names the turn it follows
(``parent``), so *Regenerate* gives a question another answer beside the earlier ones, which stay, and a question can
follow any answer, the one the person has in front of them. A playbook's thread names no ``parent``: each of its
turns follows the one before it. Looked at: Claude's and ChatGPT's conversations, and OpenAI's Responses and Conversations
APIs (a response names the one before it, ``previous_response_id``), which keep a conversation this way; a flat list
with versions of the last answer only (built first, and set aside in review) can't carry on from an earlier version.
The routes and codes are this gateway's own, since none of these is a standard to follow by the letter. The screens
ask only through it; the stream says the numbers the server gave the question and its answer (event ``stored``).

**A playbook run is a conversation** (decision, 30 October 2026; docs/design/playbooks.md, "The chat UI"):
starting one makes a conversation in the case (``run_id`` set), titled with the playbook, its
starter its owner, shared with the case from the start, so it is listed, opened and pinned like any
other. It goes with its case: the keep period, "Delete history" and the account's deletion leave it,
it can't be unshared, moved, saved over or deleted on its own (stop or cancel the run instead).

Review notes:
- Deletion makes rows unreachable, not unrecoverable, as for documents (docs/architecture.md §6).
- PostgreSQL itself is provisioned outside suveryn-core (suveryn-appliance), as for documents.
- A turn's text is document-grade data like the blob's: stored, never logged.
"""

import json
import logging
import os
import re
import uuid

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from suveryn_harness.grounding import MARKER
from suveryn_harness.schemas import Calculation, Citation, CitationIssue, SupportSpan

from .cases import KEEP_PERIODS
from .db import PgStore
from .description import Answer
from .problems import Message

# A document's id, as a question names the documents it shows with it.
DocumentId = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]

log = logging.getLogger("suveryn.gateway")

MAX_TURNS = 500
MAX_TITLE = 200
MAX_TURN_TEXT = 200_000  # one turn's text

# Conversations and their turns, in one schema both stores create (idempotent DDL): the playbook store
# writes turns too, and a turn's conversation must exist first.
SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          uuid PRIMARY KEY,
    owner       text NOT NULL,
    title       text NOT NULL,
    case_id     uuid,
    shared      boolean NOT NULL DEFAULT false,
    pinned_at   timestamptz,
    run_id      uuid UNIQUE,               -- a playbook run's conversation (playbook_runs.conversation_id)
    titles      jsonb,                     -- a run's: its title in every language, the pack's words; the UI shows the reader's
    -- Kept beside the turns on every change, so lists and look-ups don't open them: how many turns,
    -- and which documents the turns cite or attach (``cited_documents``).
    messages    integer NOT NULL DEFAULT 0,
    documents   text[] NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_owner_updated ON conversations (owner, updated_at DESC);
CREATE INDEX IF NOT EXISTS conversations_case ON conversations (case_id);
CREATE INDEX IF NOT EXISTS conversations_documents ON conversations USING gin (documents);
CREATE TABLE IF NOT EXISTS turns (
    id               bigserial PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    seq              integer NOT NULL,
    role             text NOT NULL CHECK (role IN ('user', 'assistant', 'playbook')),
    step_id          text,
    "by"             text NOT NULL,
    at               timestamptz NOT NULL DEFAULT now(),
    text             text NOT NULL,
    meta             jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (conversation_id, seq)
);
CREATE TABLE IF NOT EXISTS conversation_cleanups (
    document_id           uuid NOT NULL,
    owner                 text NOT NULL,
    case_id               uuid,
    delete_conversations  boolean NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, owner)
);
"""
# What a turn's row holds itself; everything else the UI keeps on a turn goes in ``meta``.
ROW_FIELDS = ("seq", "role", "text", "by", "at", "step_id")


@dataclass(frozen=True)
class ConversationSettings:
    """Where conversations are stored and for how long; build with ``from_env()``."""

    database_url: str = ""
    keep: str = "manual"  # a KEEP_PERIODS key: how long a conversation is kept after its last change

    @property
    def max_age_days(self) -> int | None:
        """The keep period in whole days; None: kept until deleted."""
        period = KEEP_PERIODS.get(self.keep)
        return period.days if period is not None else None

    @classmethod
    def from_env(cls) -> "ConversationSettings":
        keep = os.environ.get("SUVERYN_CONVERSATIONS_KEEP", "manual").strip().lower() or "manual"
        if keep not in KEEP_PERIODS:
            raise ValueError("SUVERYN_CONVERSATIONS_KEEP must be '6m', '1y', '5y' or 'manual'")
        return cls(database_url=os.environ.get("SUVERYN_DATABASE_URL", ""), keep=keep)


class QuestionIn(BaseModel):
    """Body of ``POST /v1/conversations/{id}/questions``: a new question in a conversation the server keeps
    (suveryn-tracker#251), or one asked again. Only the question: what the model reads of the conversation before it
    comes from the turns the server stored, and the answer is stored as it is written.

    A conversation is a tree, as in Claude and ChatGPT (suveryn-tracker#251): every turn the
    server writes names the turn it follows (``parent``). A question follows an answer, ``after`` (needed once the
    conversation has one); asked again (``again``, the question's ``seq``: *Regenerate*), it gets another answer beside the earlier
    ones, which stay, so a question can have several answers and what follows each of them."""

    text: str | None = Field(default=None, min_length=1, max_length=100_000)
    # What the answer is grounded in (as ``ChatRequest.document_ids``): empty, a plain, unsourced answer.
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    # What the question shows with it, by id: the documents chosen with *Ask about*, and the ones attached to it.
    about: list[DocumentId] = Field(default_factory=list, max_length=50)
    attached: list[DocumentId] = Field(default_factory=list, max_length=50)
    # The case a new conversation is in (None: the personal space); a conversation stays where it was started.
    case_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    model: str | None = Field(default=None, pattern=r"^[\w.:-]{1,120}$")
    thinking: bool = False
    # The answer the question follows (its ``seq``): the one the person has in front of them. None only for the
    # conversation's first question.
    after: int | None = Field(default=None, ge=1)
    # *Regenerate*: the question (its ``seq``) to answer once more, with what it was asked with; nothing else is sent.
    again: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _a_question_or_one_again(self) -> "QuestionIn":
        if self.again is None and self.text is None:
            raise ValueError("a question: its text, or the question to ask again")
        if self.again is not None and self.model_fields_set - {"again"}:
            raise ValueError("a question asked again is asked as it was: nothing but again")
        return self


class StoredTurns(Answer):
    """Event ``stored`` of an answer in a saved conversation: the numbers (``seq``) the server gave the question, first,
    then with the answer's too, once it is stored, before ``done`` or ``error``. What the next question follows
    (``after``), what *Regenerate* asks again (``again``) and what *Save to case* names: told, as chat APIs return the
    ids of the messages they store, never guessed from the conversation read back (review of #251, step 3a, finding 1)."""

    question: int
    answer: int | None


class AskedTurn(Answer):
    """What a question's row keeps beside its text (``meta``), as the server writes it: the turn it follows, the
    documents it was about, by id only, so a deleted one leaves no name behind; how it was asked."""

    kind: Literal["question"] = "question"
    parent: int | None  # the answer it follows (``seq``); None: the first question
    document_ids: list[str]
    about: list[str]
    attached: list[str]
    model: str | None
    thinking: bool


class AnsweredTurn(Answer):
    """What an answer's row keeps beside its text (``meta``), as the server writes it once the stream ended: the
    question it answers (``parent``), how it ended (``outcome``), and for an answer written out everything the answer
    said beside its words (``ChatResponse`` but its id, words and token counts; a test holds the two together), the
    document it was narrowed to by id."""

    kind: Literal["answer"] = "answer"
    parent: int | None = None  # the question it answers (``seq``)
    outcome: Literal["done", "stopped", "failed"]
    model: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    calculations: list[Calculation] = Field(default_factory=list)
    unverified_figures: list[str] = Field(default_factory=list)
    citation_issues: list[CitationIssue] = Field(default_factory=list)
    support_spans: list[SupportSpan] = Field(default_factory=list)
    instruction_like_sources: list[int] = Field(default_factory=list)
    finish_reason: str | None = None
    reasoning: str = ""
    thought_seconds: float | None = None
    thinking_cut: bool = False
    narrowed_to: str | None = None  # a document's id, never its name
    complete: bool | None = None
    asked_again: bool = False
    failure: Message | None = None  # why it failed: a code of the registry


class SavedAnswer(Answer):
    """What an answer saved to its case keeps as its document's ``content`` (what rebuilds its Word file), when the
    server copies it from the answer it stored (suveryn-tracker#251, step 2): in the shape the chat UI has always
    saved and reads (its ``SavedAnswer``, ``lib/saved.ts``), so every saved answer is read one way. The passages are
    copied as stored, with ``removed`` where a deleted document was taken out; ``citations`` and ``filenames`` are
    where a later deletion takes them out (the rag's ``store.without``)."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)
    question: str
    answer: str
    answered_on: datetime = Field(alias="answeredOn")  # when it was saved, as the chat UI keeps it
    model: str | None
    citations: list[dict]
    calculations: list[dict]
    unverified_figures: list[str] = Field(alias="unverifiedFigures")
    citation_issues: list[dict] = Field(alias="citationIssues")
    support_spans: list[dict] = Field(alias="supportSpans")
    instruction_like_sources: list[int] = Field(alias="instructionLikeSources")
    filenames: dict[str, str]                      # a cited document's id: its file name when the answer was saved
    turn_id: str = Field(alias="turnId")           # "<conversation>/<seq>": the file's mark refers to it
    case_ref: str | None = Field(alias="caseRef")  # the case's reference, as the file's mark shows it


def search_text(question: str, answer: str) -> str:
    """What search finds of a saved answer: the question and the answer, without its markers (the same words as the
    chat UI's ``stripMarkers`` leaves when it copies an answer)."""
    return f"{question}\n\n{re.sub(r'[ \t]+([.,;:])', r'\1', MARKER.sub('', answer))}".strip()


def file_name(question: str) -> str:
    """A saved answer's Word file name: its question, on one line, without characters a file name can't hold, at most
    80 characters, "answer" when nothing of it is left. The only place a saved answer is named (the chat UI named
    them itself until it saved answers by naming the stored turn, suveryn-tracker#251)."""
    name = re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", question)).strip()
    name = re.sub(r"[. ]+$", "", name)
    return f"{(name[:80].rstrip() if len(name) > 80 else name) or 'answer'}.docx"


def title_of(question: str) -> str:
    """A new conversation's title: its first question, on one line, at most 80 characters."""
    first = " ".join(question.split())
    return first if len(first) <= 80 else first[:79].rstrip() + "\u2026"


def asked_turn(body: QuestionIn, parent: int | None) -> dict:
    return AskedTurn(parent=parent, document_ids=body.document_ids, about=body.about, attached=body.attached, model=body.model,
                     thinking=body.thinking).model_dump(mode="json")


def answered_turn(text: str, reasoning: str, sources: list, done: BaseModel | None, failure: dict | None,
                  parent: int | None = None) -> tuple[str, dict]:
    """An answer's row (text, ``meta``) once its stream ended: written out (``done``, the whole answer with its
    checks), failed (no words, as the stream's contract says, and the code it failed with), or stopped (the words so
    far and their passages, unchecked: stopped by the person, or the connection went). ``parent``: its question."""
    if done is not None:
        whole = done.model_dump(exclude={"id", "answer", "usage"})
        if whole.get("narrowed_to") is not None:
            # The one document the question named, kept by its id, never by the file name the answer carries: only
            # that document was read, so its passages say which (a name would stay when it is deleted). Without a
            # passage it can't be told, and nothing is kept.
            read = {c["source"]["document_id"] for c in whole["citations"] if c.get("source")}
            whole["narrowed_to"] = read.pop() if len(read) == 1 else None
        return done.answer, AnsweredTurn(parent=parent, outcome="done", **whole).model_dump(mode="json")
    if failure is not None:
        return "", AnsweredTurn(parent=parent, outcome="failed", failure=Message(**failure)).model_dump(mode="json")
    return text, AnsweredTurn(parent=parent, outcome="stopped", citations=sources, reasoning=reasoning).model_dump(mode="json")


def parent_of(turns: list["Turn"], i: int) -> int | None:
    """The ``seq`` of the turn ``turns[i]`` follows: the one it names (``parent``), or, for a turn without one (a
    playbook's thread), the turn before it."""
    if "parent" in turns[i].meta:
        return turns[i].meta["parent"]
    return turns[i - 1].seq if i > 0 else None


def path_to(turns: list["Turn"], seq: int | None) -> list["Turn"]:
    """The turns from the conversation's first to the one ``seq`` names, each the one the next follows: what was said
    on the way to it, in that branch of the tree. Empty for None or a ``seq`` that isn't there."""
    at = {t.seq: i for i, t in enumerate(turns)}
    path: list[Turn] = []
    while seq is not None and seq in at and len(path) <= len(turns):  # bounded: a loop in stored parents ends
        path.append(turns[at[seq]])
        seq = parent_of(turns, at[seq])
    return path[::-1]


def history_pairs(path: list["Turn"]) -> list[tuple[str, str | None]]:
    """(question, its completed answer or None) for each question on a path (``path_to``), for the model's history
    (``suveryn_harness.conversation_history``). Completed: the server says ``outcome`` done."""
    pairs = []
    for i, turn in enumerate(path):
        if turn.role != "user":
            continue
        after = path[i + 1] if i + 1 < len(path) else None
        done = after is not None and after.role == "assistant" and after.meta.get("outcome") == "done"
        pairs.append((turn.text, after.text if done else None))
    return pairs


class ConversationSummary(Answer):
    """One entry of ``GET /v1/conversations``."""

    id: str
    # None when ``shielded``: a conversation in a strictly confidential case, in the lists that span
    # cases (docs/design/chat-ui.md §11); the UI shows "Shielded conversation" with the case.
    title: str | None
    created_at: datetime
    updated_at: datetime
    case_id: str | None = None
    owner: str = ""        # who started it (a Keycloak id); the UI names them from the case's members
    shared: bool = False   # shared with the case's members (stage 4)
    messages: int = 0      # how many turns (questions and answers): the Conversations overview (docs/design/chat-ui.md §4)
    owner_name: str = ""   # a colleague's name, for one shared with a case (the overview's "From"); empty for the caller's own
    shielded: bool = False
    pinned: bool = False   # a personal conversation pinned by its owner (docs/design/chat-ui.md §3)
    run_id: str | None = None  # a playbook run's conversation (its icon is the route; it goes with its case)
    # A run's title in every language (the pack's words): the UI shows the reader's; ``title`` is the starter's.
    titles: dict[str, str] | None = None


class Deleted(Answer):
    """What ``DELETE /v1/conversations`` answers: how many of the caller's conversations were deleted."""

    deleted: int


class PinIn(BaseModel):
    """Body of ``PUT /v1/conversations/{id}/pin``."""

    pinned: bool


class RenameIn(BaseModel):
    """Body of ``PATCH /v1/conversations/{id}``: a title the owner chose, instead of its first question."""

    title: str = Field(min_length=1, max_length=MAX_TITLE, pattern=r"^\S(.*\S)?$")


class MoveIn(BaseModel):
    """Body of ``POST /v1/conversations/{id}/move``: the case a personal conversation moves into."""

    case_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class ShareIn(BaseModel):
    """Body of ``POST /v1/conversations/{id}/share``."""

    shared: bool


class Conversation(ConversationSummary):
    """Body of ``GET /v1/conversations/{id}``: each turn as the server keeps it (what it wrote beside it, ``meta``),
    with ``seq``, ``by`` and ``at`` (and a playbook's ``step_id``) from its row."""

    turns: list[dict]


def cited_documents(turns: list[dict]) -> set[str]:
    """Ids of the documents a conversation cites or attaches."""
    return {d for d, _ in _references(turns)}


def _references(turns: list[dict]) -> Iterator[tuple[str, dict]]:
    """(document id, the citation or attachment dict naming it) for every reference in the turns."""
    for turn in turns:
        for c in turn.get("citations") or []:
            if isinstance(c, dict) and isinstance(c.get("source"), dict) and isinstance(c["source"].get("document_id"), str):
                yield c["source"]["document_id"], c
        # the documents a playbook's turn was given (a question the server stores names its documents by id only)
        for a in turn.get("attachments") or []:
            if isinstance(a, dict) and isinstance(a.get("documentId"), str):
                yield a["documentId"], a


def redact(turns: list[dict], gone: Callable[[str], bool]) -> bool:
    """Take every passage and attachment name of the documents ``gone`` says are deleted out of the
    turns, in place. True if anything changed."""
    changed = False
    for doc, ref in list(_references(turns)):
        if not gone(doc) or ref.get("removed"):
            continue
        if "source" in ref:  # a citation: no text, no location (headings), no text around it; only the page number stays
            ref["text"] = ""
            ref.pop("context", None)
            ref["source"] = {"document_id": doc, "page": ref["source"].get("page"), "location": None}
        else:  # an attachment
            ref["filename"] = ""
        ref["removed"] = True
        changed = True
    return changed


class Turn(Answer):
    """One line of a thread, as ``turns`` holds it."""

    seq: int
    role: Literal["user", "assistant", "playbook"]
    step_id: str | None = None
    by: str                       # the username, the playbook id for its own turns, "assistant" for an answer
    at: datetime
    text: str
    meta: dict = Field(default_factory=dict)

    def as_saved(self) -> dict:
        """The turn as it is read back: what the server wrote beside it (``meta``), then the row's."""
        return {**self.meta, "seq": self.seq, "role": self.role, "text": self.text, "by": self.by, "at": self.at.isoformat(),
                **({"step_id": self.step_id} if self.step_id else {})}


class TurnStore(PgStore):
    """The ``turns`` table, and the conversation rows they belong to. ``RunStore`` inherits it, so one
    connection serves a run and its thread; ``ConversationStore`` too, for a conversation's questions and answers."""

    schema = SCHEMA
    TURN = "seq, role, step_id, \"by\", at, text, meta"

    @staticmethod
    def _turn(r) -> Turn:
        return Turn(seq=r[0], role=r[1], step_id=r[2], by=r[3], at=r[4], text=r[5], meta=r[6])

    def turns_of(self, conversation_id: uuid.UUID, limit: int = MAX_TURNS) -> list[Turn]:
        rows = self._execute(f"SELECT {self.TURN} FROM turns WHERE conversation_id = %s ORDER BY seq LIMIT %s",
                             (conversation_id, limit)).fetchall()
        return [self._turn(r) for r in rows]

    def append(self, conversation_id: uuid.UUID, role: str, by: str, text: str, step_id: str | None = None,
               meta: dict | None = None, once: bool = False) -> Turn:
        """Add a turn at the end of a conversation (a playbook's thread). The conversation's row is
        locked while the next ``seq`` is taken, so two writers at once never pick the same one. ``once``:
        not when the last turn already says the same (role, step, text and meta): two requests walking the run
        at the same moment wrote the playbook's question twice (VM regression e0f2e26, finding 2). A playbook's
        own turn has no text, only its meaning (``meta``; the decision of 12 November 2026, *Meaning on the
        server*), so the meaning is compared too."""
        text = text[:MAX_TURN_TEXT]
        with self.transaction():
            n = self._execute("SELECT messages FROM conversations WHERE id = %s FOR UPDATE", (conversation_id,)).fetchone()
            if n is None:
                raise LookupError("no such conversation")
            if once:
                last = self._execute(f"SELECT {self.TURN} FROM turns WHERE conversation_id = %s ORDER BY seq DESC LIMIT 1",
                                     (conversation_id,)).fetchone()
                if last is not None and (last[1], last[2], last[5], last[6]) == (role, step_id, text, meta or {}):
                    return self._turn(last)
            seq = self._execute("SELECT coalesce(max(seq), 0) + 1 FROM turns WHERE conversation_id = %s", (conversation_id,)).fetchone()[0]
            r = self._execute(f"INSERT INTO turns (conversation_id, seq, role, step_id, \"by\", text, meta) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                              f" RETURNING {self.TURN}", (conversation_id, seq, role, step_id, by, text, json.dumps(meta or {}))).fetchone()
            self._execute("UPDATE conversations SET messages = messages + 1, updated_at = now() WHERE id = %s", (conversation_id,))
        return self._turn(r)

    def create_for_run(self, conversation_id: uuid.UUID, run_id: uuid.UUID, owner: str, title: str, case_id: uuid.UUID,
                       titles: dict[str, str] | None = None) -> None:
        """A playbook run's conversation: in its case, shared with it from the start, owned by its starter.
        ``titles``: the playbook's title in every language, so each reader sees it in theirs."""
        self._execute("INSERT INTO conversations (id, owner, title, case_id, shared, run_id, titles) VALUES (%s, %s, %s, %s, true, %s, %s)",
                      (conversation_id, owner, title[:MAX_TITLE], case_id, run_id,
                       json.dumps({k: v[:MAX_TITLE] for k, v in titles.items()}) if titles else None))


class ConversationStore(TurnStore):
    """Conversations in PostgreSQL, one owner's at a time. Creates its table on connect.

    Every method takes the owner: another user's conversation is treated as missing.
    """

    def __init__(self, settings: ConversationSettings):
        super().__init__(settings.database_url)
        self.settings = settings
        self.keep = settings.keep  # as provisioned; the gateway sets what an administrator chose since
        self.purge()

    @property
    def max_age_days(self) -> int | None:
        """The keep period that applies now, in whole days; None: kept until deleted."""
        period = KEEP_PERIODS.get(self.keep)
        return period.days if period is not None else None

    def _fresh(self) -> tuple[str, tuple]:
        """SQL condition (and its parameters) for conversations within the office's keep period."""
        if self.max_age_days is None:
            return "true", ()
        return "(run_id IS NOT NULL OR updated_at > now() - make_interval(days => %s))", (self.max_age_days,)

    def older_than(self, days: int) -> int:
        """How many saved conversations a keep period of ``days`` would delete now (every owner's)."""
        return self._execute("SELECT count(*) FROM conversations WHERE run_id IS NULL AND updated_at <= now() - make_interval(days => %s)",
                             (days,)).fetchone()[0]

    def purge(self) -> int:
        """Delete every owner's conversations older than the keep period; returns how many. A playbook
        run's goes with its case, not with this period."""
        if self.max_age_days is None:
            return 0
        n = self._execute("DELETE FROM conversations WHERE run_id IS NULL AND updated_at <= now() - make_interval(days => %s)",
                          (self.max_age_days,)).rowcount
        if n:
            log.info("deleted %d conversations older than %d days", n, self.max_age_days)
        return n

    # ``messages``, not ``jsonb_array_length(turns)``: counting opened every conversation's turns for a list.
    SUMMARY = "id, title, created_at, updated_at, case_id, owner, shared, messages, pinned_at IS NOT NULL, run_id, titles"

    @staticmethod
    def _summary(r) -> ConversationSummary:
        return ConversationSummary(id=str(r[0]), title=r[1], created_at=r[2], updated_at=r[3],
                                   case_id=str(r[4]) if r[4] else None, owner=r[5], shared=r[6], messages=r[7],
                                   pinned=bool(r[8]), run_id=str(r[9]) if r[9] else None, titles=r[10])

    def summaries(self, owner: str, case_id: uuid.UUID | None = None) -> list[ConversationSummary]:
        """The conversations in one place, most recently changed first: the owner's own in their
        personal space (``case_id`` None), or in one case their own and the ones others shared.
        Expired ones are left out here and deleted by the hourly sweep (``purge``), not on every listing."""
        fresh, params = self._fresh()
        rows = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                             f" WHERE case_id IS NOT DISTINCT FROM %s AND (owner = %s OR (shared AND case_id IS NOT NULL))"
                             f" AND {fresh} ORDER BY updated_at DESC", (case_id, owner, *params)).fetchall()
        return [self._summary(r) for r in rows]

    def summaries_all(self, owner: str, case_ids: list[uuid.UUID]) -> list[ConversationSummary]:
        """Every conversation of the owner's own, in their personal space and in the cases they may
        still read (``case_ids``), and the ones colleagues shared with those cases, most recently
        changed first (the column's Recent and the Conversations overview, docs/design/chat-ui.md §2, §4).
        Expired ones are left out here and deleted by the hourly sweep."""
        fresh, params = self._fresh()
        rows = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                             f" WHERE ((owner = %s AND (case_id IS NULL OR case_id = ANY(%s))) OR (shared AND case_id = ANY(%s)))"
                             f" AND {fresh} ORDER BY updated_at DESC LIMIT 500", (owner, case_ids, case_ids, *params)).fetchall()
        return [self._summary(r) for r in rows]

    def get(self, conversation_id: uuid.UUID, owner: str) -> Conversation | None:
        """The owner's conversation; None if it is someone else's (see ``get_shared``)."""
        fresh, params = self._fresh()
        r = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                          f" WHERE id = %s AND owner = %s AND {fresh}", (conversation_id, owner, *params)).fetchone()
        return self._whole(r)

    def _whole(self, r) -> Conversation | None:
        if r is None:
            return None
        return Conversation(**self._summary(r).model_dump(), turns=[t.as_saved() for t in self.turns_of(r[0])])

    def get_shared(self, conversation_id: uuid.UUID) -> Conversation | None:
        """A conversation its owner shared with its case, whoever asks: the gateway checks the
        caller may read that case before returning it."""
        fresh, params = self._fresh()
        r = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                          f" WHERE id = %s AND shared AND case_id IS NOT NULL AND {fresh}", (conversation_id, *params)).fetchone()
        return self._whole(r)

    def rename(self, conversation_id: uuid.UUID, owner: str, title: str) -> ConversationSummary | None:
        """The owner's new title. None if it isn't the owner's."""
        r = self._execute(f"UPDATE conversations SET title = %s WHERE id = %s AND owner = %s"
                          f" RETURNING {self.SUMMARY}", (title, conversation_id, owner)).fetchone()
        return self._summary(r) if r else None

    def set_pinned(self, conversation_id: uuid.UUID, owner: str, pinned: bool) -> ConversationSummary | None:
        """Pin or unpin the owner's personal conversation (a conversation in a case follows its case,
        docs/design/chat-ui.md §3). None if it isn't the owner's or is in a case."""
        r = self._execute(f"UPDATE conversations SET pinned_at = CASE WHEN %s THEN coalesce(pinned_at, now()) END"
                          f" WHERE id = %s AND owner = %s AND case_id IS NULL RETURNING {self.SUMMARY}",
                          (pinned, conversation_id, owner)).fetchone()
        return self._summary(r) if r else None

    def move(self, conversation_id: uuid.UUID, owner: str, case_id: uuid.UUID) -> ConversationSummary | None:
        """Move the owner's personal conversation into a case: not shared, no pin of its own. None if it
        isn't the owner's or is already in a case."""
        r = self._execute(f"UPDATE conversations SET case_id = %s, shared = false, pinned_at = NULL, updated_at = now()"
                          f" WHERE id = %s AND owner = %s AND case_id IS NULL RETURNING {self.SUMMARY}",
                          (case_id, conversation_id, owner)).fetchone()
        return self._summary(r) if r else None

    def unshare_case(self, case_id: uuid.UUID) -> int:
        """Stop sharing every conversation of a case (it became strictly confidential); their owners
        keep them. How many were shared."""
        return self._execute("UPDATE conversations SET shared = false WHERE case_id = %s AND shared AND run_id IS NULL", (case_id,)).rowcount

    def set_shared(self, conversation_id: uuid.UUID, owner: str, shared: bool) -> ConversationSummary | None:
        """Share the owner's conversation with its case, or stop sharing it. None if it isn't the
        owner's or isn't in a case (a personal conversation can't be shared), or is a playbook run's."""
        r = self._execute(f"UPDATE conversations SET shared = %s WHERE id = %s AND owner = %s AND case_id IS NOT NULL AND run_id IS NULL"
                          f" RETURNING {self.SUMMARY}", (shared, conversation_id, owner)).fetchone()
        return self._summary(r) if r else None

    def place(self, conversation_id: uuid.UUID) -> tuple[str, uuid.UUID | None, bool] | None:
        """(owner, case, whether it can't be asked in: a playbook run's, or past the office's keep period) of a
        conversation; None if there is none."""
        fresh, params = self._fresh()
        r = self._execute(f"SELECT owner, case_id, run_id IS NOT NULL OR NOT {fresh} FROM conversations WHERE id = %s",
                          (*params, conversation_id)).fetchone()
        return (r[0], r[1], r[2]) if r else None

    def start(self, conversation_id: uuid.UUID, owner: str, title: str, case_id: uuid.UUID | None) -> bool:
        """A new conversation, empty; False if the id is taken already (by anyone)."""
        return self._execute("INSERT INTO conversations (id, owner, title, case_id) VALUES (%s, %s, %s, %s)"
                             " ON CONFLICT (id) DO NOTHING RETURNING id",
                             (conversation_id, owner, title[:MAX_TITLE], case_id)).fetchone() is not None

    def add(self, conversation_id: uuid.UUID, role: str, by: str, text: str, meta: dict, documents: set[str]) -> Turn:
        """A turn the server wrote, at the end of a conversation (suveryn-tracker#251), and the documents it names
        added to the conversation's (``documents``: what a document's deletion looks for)."""
        with self.transaction():
            turn = self.append(conversation_id, role, by, text, meta=meta)
            if documents:
                self._execute("UPDATE conversations SET documents = ARRAY(SELECT DISTINCT unnest(documents || %s::text[]) ORDER BY 1)"
                              " WHERE id = %s", (sorted(documents), conversation_id))
        return turn

    def delete(self, conversation_id: uuid.UUID, owner: str) -> bool:
        """Delete one of the owner's conversations (a playbook run's goes with its case: not here)."""
        return self._execute("DELETE FROM conversations WHERE id = %s AND owner = %s AND run_id IS NULL",
                             (conversation_id, owner)).rowcount > 0

    def using_document(self, owner: str, document_id: uuid.UUID,
                       case_id: uuid.UUID | None = None) -> list[ConversationSummary]:
        """The conversations that cite or attach this document, most recently changed first: the
        owner's, or with ``case_id`` everyone's in that case (a case's document is cited by every
        member who asked about it). By ``documents``, kept on save: searching every conversation's turns
        as text took 0.3 s for 500 conversations, and grew with them."""
        fresh, params = self._fresh()
        whose, who = ("case_id = %s", case_id) if case_id is not None else ("owner = %s", owner)
        rows = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                             f" WHERE {whose} AND documents @> ARRAY[%s]::text[] AND {fresh} ORDER BY updated_at DESC",
                             (who, str(document_id), *params)).fetchall()
        return [self._summary(r) for r in rows]

    # A document's deletion, noted before it is deleted and done after (audit of 21 October 2026,
    # finding 3): if cleaning the conversations fails halfway, the sweep finishes it.
    def note_cleanup(self, owner: str, document_id: uuid.UUID, delete_conversations: bool, case_id: uuid.UUID | None) -> None:
        self._execute("INSERT INTO conversation_cleanups (document_id, owner, case_id, delete_conversations)"
                      " VALUES (%s, %s, %s, %s) ON CONFLICT (document_id, owner) DO UPDATE"
                      " SET delete_conversations = EXCLUDED.delete_conversations OR conversation_cleanups.delete_conversations",
                      (document_id, owner, case_id, delete_conversations))

    def cleanup_done(self, owner: str, document_id: uuid.UUID) -> None:
        self._execute("DELETE FROM conversation_cleanups WHERE document_id = %s AND owner = %s", (document_id, owner))

    def finish_cleanups(self) -> int:
        """Finish the cleanings a deletion left unfinished: the sweep's part. Returns how many."""
        rows = self._execute("SELECT owner, document_id, delete_conversations, case_id FROM conversation_cleanups"
                             " ORDER BY created_at").fetchall()
        for owner, did, delete, case_id in rows:
            self.remove_document(owner, did, delete, case_id)
            self.cleanup_done(owner, did)
        return len(rows)

    def remove_document(self, owner: str, document_id: uuid.UUID, delete_conversations: bool = False,
                        case_id: uuid.UUID | None = None) -> int:
        """After deleting a document: take its passages out of the conversations that cite it (the
        owner's, or with ``case_id`` everyone's in that case), or delete those conversations
        (``delete_conversations``). Returns how many conversations were changed or deleted.
        A cleaned conversation keeps its date, so the sidebar's order doesn't change."""
        n = 0
        for summary in self.using_document(owner, document_id, case_id):
            if delete_conversations:
                n += self._execute("DELETE FROM conversations WHERE id = %s", (summary.id,)).rowcount
                continue
            with self.transaction():  # the conversation locked between reading and writing its turns
                if self._execute("SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (summary.id,)).fetchone() is None:
                    continue
                turns = [t.as_saved() for t in self.turns_of(uuid.UUID(summary.id))]
                if redact(turns, lambda d: d == str(document_id)):
                    for t in turns:
                        self._execute("UPDATE turns SET meta = %s WHERE conversation_id = %s AND seq = %s",
                                      (json.dumps({k: v for k, v in t.items() if k not in ROW_FIELDS}), summary.id, t["seq"]))
                    n += 1
        return n

    def personal(self, owner: str) -> int:
        """How many of this owner's conversations nobody else can read: outside a case, or in one and not shared."""
        return self._execute("SELECT count(*) FROM conversations WHERE owner = %s AND (case_id IS NULL OR NOT shared)",
                             (owner,)).fetchone()[0]

    def shared_count(self, owner: str) -> int:
        """How many of this owner's conversations are shared with a case (they stay when the account is deleted)."""
        return self._execute("SELECT count(*) FROM conversations WHERE owner = %s AND case_id IS NOT NULL AND shared",
                             (owner,)).fetchone()[0]

    def delete_personal(self, owner: str) -> int:
        """Delete them (Administration › Users, an account deleted); those shared with a case stay with the case."""
        return self._execute("DELETE FROM conversations WHERE owner = %s AND (case_id IS NULL OR NOT shared)",
                             (owner,)).rowcount

    def delete_all(self, owner: str) -> int:
        """Delete every conversation of this owner (the sign-out choice "Delete history"); a playbook
        run's stays with its case."""
        return self._execute("DELETE FROM conversations WHERE owner = %s AND run_id IS NULL", (owner,)).rowcount

    def delete_case(self, case_id: uuid.UUID) -> int:
        """Delete every conversation in a case, whoever started it (the case is being deleted)."""
        return self._execute("DELETE FROM conversations WHERE case_id = %s", (case_id,)).rowcount
