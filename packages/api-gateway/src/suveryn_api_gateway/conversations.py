"""Saved conversations (suveryn-tracker#5): each user's chat history, kept on this server.

A conversation is stored as the chat UI's list of turns (questions, answers with their citations
and calculations, attachment names), as JSON, under the owner's Keycloak id. The gateway checks
the shape loosely (``SavedTurn``) and bounds the size; it never reads the text.

Cases (suveryn-tracker#10): a conversation started in a case carries its ``case_id`` and is listed
with that case; one without is in the owner's personal space. Either way it is private to whoever
started it, unless its owner **shares** it with the case (decision 12, stage 4): a shared
conversation is listed for and readable by everyone who may read the case, read-only for them
(only the owner saves, shares, unshares or deletes it). The gateway checks the right in the case;
the store only knows ``shared``.

Retention: kept until the user deletes it (one conversation, or all of them when signing out), or
until the office's keep period for conversations passes (the data lifecycle, suveryn-tracker#31):
``SUVERYN_CONVERSATIONS_KEEP`` as provisioned (``6m``, ``1y``, ``5y`` or ``manual``, the default:
nothing is chosen for the office), changed by an administrator in the dashboard with the case
settings (``conversations_keep`` in ``case_settings``). The gateway tells the store the period
that applies (``keep``); conversations older than it, by last change and in cases too, are no
longer listed or returned, and are deleted on start, on each listing and by the hourly sweep.

Deleted documents (suveryn-tracker#12): saved answers quote the passages they cite. When a
document is deleted, every passage of it is taken out of the owner's conversations
(``remove_document``): its text and its location (headings are document text too) are emptied and
the citation is marked ``removed``; attachments of the document, and its place in a question's *Ask
about* choice, lose their file name the same way.
The answers themselves stay, and still state facts from the document, so the UI offers to delete
those conversations together with the document (``using_document``). A save from a tab that still
holds the passages is cleaned the same way before it is stored (``redact``), so they can't come back.

Review notes:
- Deletion makes rows unreachable, not unrecoverable, as for documents (docs/architecture.md §6).
- PostgreSQL itself is provisioned outside suveryn-core (suveryn-appliance), as for documents.
"""

import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .cases import KEEP_PERIODS
from .db import PgStore

log = logging.getLogger("suveryn.gateway")

MAX_BODY_BYTES = 2 * 1024 * 1024  # one saved conversation, as JSON
MAX_TURNS = 500
MAX_TITLE = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          uuid PRIMARY KEY,
    owner       text NOT NULL,
    title       text NOT NULL,
    turns       jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_owner_updated ON conversations (owner, updated_at DESC);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS case_id uuid;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS shared boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS conversations_case ON conversations (case_id);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pinned_at timestamptz;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS renamed boolean NOT NULL DEFAULT false;
"""


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


class SavedTurn(BaseModel):
    """One turn as the UI saves it. Only the role is checked; the other fields are the UI's own."""

    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant"]
    text: str = Field(default="", max_length=200_000)


class ConversationIn(BaseModel):
    """Body of ``PUT /v1/conversations/{id}``: the whole conversation, replacing what was stored."""

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    turns: list[SavedTurn] = Field(min_length=1, max_length=MAX_TURNS)
    case_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")  # None: the personal space


class ConversationSummary(BaseModel):
    """One entry of ``GET /v1/conversations``."""

    id: str
    # None when ``shielded``: a conversation in a strictly confidential case, in the lists that span
    # cases (docs/design/sidebar.md §11); the UI shows "Shielded conversation" with the case.
    title: str | None
    created_at: datetime
    updated_at: datetime
    case_id: str | None = None
    owner: str = ""        # who started it (a Keycloak id); the UI names them from the case's members
    shared: bool = False   # shared with the case's members (stage 4)
    messages: int = 0      # how many turns (questions and answers): the Conversations overview (docs/design/sidebar.md §4)
    owner_name: str = ""   # a colleague's name, for one shared with a case (the overview's "From"); empty for the caller's own
    shielded: bool = False
    pinned: bool = False   # a personal conversation pinned by its owner (docs/design/sidebar.md §3)


class PinIn(BaseModel):
    """Body of ``PUT /v1/conversations/{id}/pin``."""

    pinned: bool


class RenameIn(BaseModel):
    """Body of ``PATCH /v1/conversations/{id}``: a title the owner chose, kept over later saves."""

    title: str = Field(min_length=1, max_length=MAX_TITLE, pattern=r"^\S(.*\S)?$")


class MoveIn(BaseModel):
    """Body of ``POST /v1/conversations/{id}/move``: the case a personal conversation moves into."""

    case_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class ShareIn(BaseModel):
    """Body of ``POST /v1/conversations/{id}/share``."""

    shared: bool


class Conversation(ConversationSummary):
    """Body of ``GET /v1/conversations/{id}``."""

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
        # attachments, and the documents a question was asked about (Ask about, docs/design/sidebar.md §10)
        for a in [*(turn.get("attachments") or []), *(turn.get("about") or [])]:
            if isinstance(a, dict) and isinstance(a.get("documentId"), str):
                yield a["documentId"], a


def redact(turns: list[dict], gone: Callable[[str], bool]) -> bool:
    """Take every passage and attachment name of the documents ``gone`` says are deleted out of the
    turns, in place. True if anything changed."""
    changed = False
    for doc, ref in list(_references(turns)):
        if not gone(doc) or ref.get("removed"):
            continue
        if "source" in ref:  # a citation: no text, no location (headings), only the page number stays
            ref["text"] = ""
            ref["source"] = {"document_id": doc, "page": ref["source"].get("page"), "location": None}
        else:  # an attachment
            ref["filename"] = ""
        ref["removed"] = True
        changed = True
    return changed


class ConversationStore(PgStore):
    """Conversations in PostgreSQL, one owner's at a time. Creates its table on connect.

    Every method takes the owner: another user's conversation is treated as missing.
    """

    schema = SCHEMA

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
        return "updated_at > now() - make_interval(days => %s)", (self.max_age_days,)

    def purge(self) -> int:
        """Delete every owner's conversations older than the keep period; returns how many."""
        if self.max_age_days is None:
            return 0
        n = self._execute("DELETE FROM conversations WHERE updated_at <= now() - make_interval(days => %s)",
                          (self.max_age_days,)).rowcount
        if n:
            log.info("deleted %d conversations older than %d days", n, self.max_age_days)
        return n

    SUMMARY = "id, title, created_at, updated_at, case_id, owner, shared, jsonb_array_length(turns), pinned_at IS NOT NULL"
    TURNS = 9  # the column after SUMMARY's, where a query adds ``turns``

    @staticmethod
    def _summary(r) -> ConversationSummary:
        return ConversationSummary(id=str(r[0]), title=r[1], created_at=r[2], updated_at=r[3],
                                   case_id=str(r[4]) if r[4] else None, owner=r[5], shared=r[6], messages=r[7] or 0,
                                   pinned=bool(r[8]))

    def summaries(self, owner: str, case_id: uuid.UUID | None = None) -> list[ConversationSummary]:
        """The conversations in one place, most recently changed first: the owner's own in their
        personal space (``case_id`` None), or in one case their own and the ones others shared."""
        self.purge()
        fresh, params = self._fresh()
        rows = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                             f" WHERE case_id IS NOT DISTINCT FROM %s AND (owner = %s OR (shared AND case_id IS NOT NULL))"
                             f" AND {fresh} ORDER BY updated_at DESC", (case_id, owner, *params)).fetchall()
        return [self._summary(r) for r in rows]

    def summaries_all(self, owner: str, case_ids: list[uuid.UUID]) -> list[ConversationSummary]:
        """Every conversation of the owner's own, in their personal space and in the cases they may
        still read (``case_ids``), and the ones colleagues shared with those cases, most recently
        changed first (the column's Recent and the Conversations overview, docs/design/sidebar.md §2, §4)."""
        self.purge()
        fresh, params = self._fresh()
        rows = self._execute(f"SELECT {self.SUMMARY} FROM conversations"
                             f" WHERE ((owner = %s AND (case_id IS NULL OR case_id = ANY(%s))) OR (shared AND case_id = ANY(%s)))"
                             f" AND {fresh} ORDER BY updated_at DESC LIMIT 500", (owner, case_ids, case_ids, *params)).fetchall()
        return [self._summary(r) for r in rows]

    def get(self, conversation_id: uuid.UUID, owner: str) -> Conversation | None:
        """The owner's conversation; None if it is someone else's (see ``get_shared``)."""
        fresh, params = self._fresh()
        r = self._execute(f"SELECT {self.SUMMARY}, turns FROM conversations"
                          f" WHERE id = %s AND owner = %s AND {fresh}", (conversation_id, owner, *params)).fetchone()
        return Conversation(**self._summary(r).model_dump(), turns=r[self.TURNS]) if r else None

    def get_shared(self, conversation_id: uuid.UUID) -> Conversation | None:
        """A conversation its owner shared with its case, whoever asks: the gateway checks the
        caller may read that case before returning it."""
        fresh, params = self._fresh()
        r = self._execute(f"SELECT {self.SUMMARY}, turns FROM conversations"
                          f" WHERE id = %s AND shared AND case_id IS NOT NULL AND {fresh}", (conversation_id, *params)).fetchone()
        return Conversation(**self._summary(r).model_dump(), turns=r[self.TURNS]) if r else None

    def rename(self, conversation_id: uuid.UUID, owner: str, title: str) -> ConversationSummary | None:
        """The owner's new title, kept over later saves. None if it isn't the owner's."""
        r = self._execute(f"UPDATE conversations SET title = %s, renamed = true WHERE id = %s AND owner = %s"
                          f" RETURNING {self.SUMMARY}", (title, conversation_id, owner)).fetchone()
        return self._summary(r) if r else None

    def set_pinned(self, conversation_id: uuid.UUID, owner: str, pinned: bool) -> ConversationSummary | None:
        """Pin or unpin the owner's personal conversation (a conversation in a case follows its case,
        docs/design/sidebar.md §3). None if it isn't the owner's or is in a case."""
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
        return self._execute("UPDATE conversations SET shared = false WHERE case_id = %s AND shared", (case_id,)).rowcount

    def set_shared(self, conversation_id: uuid.UUID, owner: str, shared: bool) -> ConversationSummary | None:
        """Share the owner's conversation with its case, or stop sharing it. None if it isn't the
        owner's or isn't in a case (a personal conversation can't be shared)."""
        r = self._execute(f"UPDATE conversations SET shared = %s WHERE id = %s AND owner = %s AND case_id IS NOT NULL"
                          f" RETURNING {self.SUMMARY}", (shared, conversation_id, owner)).fetchone()
        return self._summary(r) if r else None

    def save(self, conversation_id: uuid.UUID, owner: str, body: ConversationIn,
             gone: Callable[[str], bool] | None = None) -> bool:
        """Create or replace the owner's conversation. False if the id belongs to another owner.

        ``gone`` says which cited documents no longer exist: their passages are taken out first.
        """
        turns = [t.model_dump() for t in body.turns]
        if gone is not None:
            redact(turns, gone)
        turns = json.dumps(turns)
        case_id = uuid.UUID(body.case_id) if body.case_id else None
        # The case is set when the conversation is first saved and never moves with a later save.
        row = self._execute(
            "INSERT INTO conversations (id, owner, title, turns, case_id) VALUES (%s, %s, %s, %s, %s)"
            # a title the owner chose (``rename``) is kept over the one the UI derives from the first question
            " ON CONFLICT (id) DO UPDATE SET title = CASE WHEN conversations.renamed THEN conversations.title"
            " ELSE EXCLUDED.title END, turns = EXCLUDED.turns, updated_at = now()"
            " WHERE conversations.owner = EXCLUDED.owner RETURNING id",
            (conversation_id, owner, body.title, turns, case_id)).fetchone()
        return row is not None

    def delete(self, conversation_id: uuid.UUID, owner: str) -> bool:
        return self._execute("DELETE FROM conversations WHERE id = %s AND owner = %s",
                             (conversation_id, owner)).rowcount > 0

    def using_document(self, owner: str, document_id: uuid.UUID,
                       case_id: uuid.UUID | None = None) -> list[ConversationSummary]:
        """The conversations that cite or attach this document, most recently changed first: the
        owner's, or with ``case_id`` everyone's in that case (a case's document is cited by every
        member who asked about it)."""
        fresh, params = self._fresh()
        whose, who = ("case_id = %s", case_id) if case_id is not None else ("owner = %s", owner)
        rows = self._execute(f"SELECT {self.SUMMARY}, turns FROM conversations"
                             f" WHERE {whose} AND turns::text LIKE %s AND {fresh} ORDER BY updated_at DESC",
                             (who, f'%"{document_id}"%', *params)).fetchall()
        return [self._summary(r) for r in rows if str(document_id) in cited_documents(r[self.TURNS])]

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
            with self.transaction():  # the row locked between reading and writing its turns
                row = self._execute("SELECT turns FROM conversations WHERE id = %s FOR UPDATE", (summary.id,)).fetchone()
                if row and redact(row[0], lambda d: d == str(document_id)):
                    n += self._execute("UPDATE conversations SET turns = %s WHERE id = %s",
                                       (json.dumps(row[0]), summary.id)).rowcount
        return n

    def delete_all(self, owner: str) -> int:
        """Delete every conversation of this owner (the sign-out choice "Delete history")."""
        return self._execute("DELETE FROM conversations WHERE owner = %s", (owner,)).rowcount

    def delete_case(self, case_id: uuid.UUID) -> int:
        """Delete every conversation in a case, whoever started it (the case is being deleted)."""
        return self._execute("DELETE FROM conversations WHERE case_id = %s", (case_id,)).rowcount
