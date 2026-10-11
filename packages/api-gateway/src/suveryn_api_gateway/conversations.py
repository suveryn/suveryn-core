"""Saved conversations (suveryn-tracker#5): each user's chat history, kept on this server.

A conversation is stored as the chat UI's list of turns (questions, answers with their citations
and calculations, attachment names), as JSON, under the owner's Keycloak id. The gateway checks
the shape loosely (``SavedTurn``) and bounds the size; it never reads the text.

Retention: kept until the user deletes it (one conversation, or all of them when signing out).
An administrator can cap the age with ``SUVERYN_CONVERSATION_MAX_AGE_DAYS``: older conversations
(by last change) are no longer listed or returned, and are deleted on start and on each listing.

Deleted documents (suveryn-tracker#12): saved answers quote the passages they cite. When a
document is deleted, every passage of it is taken out of the owner's conversations
(``remove_document``): its text and its location (headings are document text too) are emptied and
the citation is marked ``removed``; attachments of the document lose their file name the same way.
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
"""


@dataclass(frozen=True)
class ConversationSettings:
    """Where conversations are stored and for how long; build with ``from_env()``."""

    database_url: str = ""
    max_age_days: int | None = None  # None: kept until deleted

    @classmethod
    def from_env(cls) -> "ConversationSettings":
        days = os.environ.get("SUVERYN_CONVERSATION_MAX_AGE_DAYS", "").strip()
        if days and (not days.isdigit() or int(days) < 1):
            raise ValueError("SUVERYN_CONVERSATION_MAX_AGE_DAYS must be a whole number of days, 1 or more")
        return cls(database_url=os.environ.get("SUVERYN_DATABASE_URL", ""), max_age_days=int(days) if days else None)


class SavedTurn(BaseModel):
    """One turn as the UI saves it. Only the role is checked; the other fields are the UI's own."""

    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant"]
    text: str = Field(default="", max_length=200_000)


class ConversationIn(BaseModel):
    """Body of ``PUT /v1/conversations/{id}``: the whole conversation, replacing what was stored."""

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    turns: list[SavedTurn] = Field(min_length=1, max_length=MAX_TURNS)


class ConversationSummary(BaseModel):
    """One entry of ``GET /v1/conversations``."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


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
        self.purge()

    def _fresh(self) -> tuple[str, tuple]:
        """SQL condition (and its parameters) for conversations within the admin's age cap."""
        if self.settings.max_age_days is None:
            return "true", ()
        return "updated_at > now() - make_interval(days => %s)", (self.settings.max_age_days,)

    def purge(self) -> int:
        """Delete every owner's conversations older than the age cap; returns how many."""
        if self.settings.max_age_days is None:
            return 0
        n = self._execute("DELETE FROM conversations WHERE updated_at <= now() - make_interval(days => %s)",
                          (self.settings.max_age_days,)).rowcount
        if n:
            log.info("deleted %d conversations older than %d days", n, self.settings.max_age_days)
        return n

    def summaries(self, owner: str) -> list[ConversationSummary]:
        """The owner's conversations, most recently changed first."""
        self.purge()
        fresh, params = self._fresh()
        rows = self._execute(f"SELECT id, title, created_at, updated_at FROM conversations"
                             f" WHERE owner = %s AND {fresh} ORDER BY updated_at DESC", (owner, *params)).fetchall()
        return [ConversationSummary(id=str(r[0]), title=r[1], created_at=r[2], updated_at=r[3]) for r in rows]

    def get(self, conversation_id: uuid.UUID, owner: str) -> Conversation | None:
        fresh, params = self._fresh()
        r = self._execute(f"SELECT id, title, created_at, updated_at, turns FROM conversations"
                          f" WHERE id = %s AND owner = %s AND {fresh}", (conversation_id, owner, *params)).fetchone()
        return Conversation(id=str(r[0]), title=r[1], created_at=r[2], updated_at=r[3], turns=r[4]) if r else None

    def save(self, conversation_id: uuid.UUID, owner: str, body: ConversationIn,
             gone: Callable[[str], bool] | None = None) -> bool:
        """Create or replace the owner's conversation. False if the id belongs to another owner.

        ``gone`` says which cited documents no longer exist: their passages are taken out first.
        """
        turns = [t.model_dump() for t in body.turns]
        if gone is not None:
            redact(turns, gone)
        turns = json.dumps(turns)
        row = self._execute(
            "INSERT INTO conversations (id, owner, title, turns) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, turns = EXCLUDED.turns, updated_at = now()"
            " WHERE conversations.owner = EXCLUDED.owner RETURNING id",
            (conversation_id, owner, body.title, turns)).fetchone()
        return row is not None

    def delete(self, conversation_id: uuid.UUID, owner: str) -> bool:
        return self._execute("DELETE FROM conversations WHERE id = %s AND owner = %s",
                             (conversation_id, owner)).rowcount > 0

    def using_document(self, owner: str, document_id: uuid.UUID) -> list[ConversationSummary]:
        """The owner's conversations that cite or attach this document, most recently changed first."""
        fresh, params = self._fresh()
        rows = self._execute(f"SELECT id, title, created_at, updated_at, turns FROM conversations"
                             f" WHERE owner = %s AND turns::text LIKE %s AND {fresh} ORDER BY updated_at DESC",
                             (owner, f'%"{document_id}"%', *params)).fetchall()
        return [ConversationSummary(id=str(r[0]), title=r[1], created_at=r[2], updated_at=r[3]) for r in rows
                if str(document_id) in cited_documents(r[4])]

    def remove_document(self, owner: str, document_id: uuid.UUID, delete_conversations: bool = False) -> int:
        """After deleting a document: take its passages out of the owner's conversations, or delete those
        conversations (``delete_conversations``). Returns how many conversations were changed or deleted.
        A cleaned conversation keeps its date, so the sidebar's order doesn't change."""
        n = 0
        for summary in self.using_document(owner, document_id):
            if delete_conversations:
                n += self.delete(uuid.UUID(summary.id), owner)
                continue
            turns = self._execute("SELECT turns FROM conversations WHERE id = %s AND owner = %s",
                                  (summary.id, owner)).fetchone()[0]
            if redact(turns, lambda d: d == str(document_id)):
                n += self._execute("UPDATE conversations SET turns = %s WHERE id = %s AND owner = %s",
                                   (json.dumps(turns), summary.id, owner)).rowcount
        return n

    def delete_all(self, owner: str) -> int:
        """Delete every conversation of this owner (the sign-out choice "Delete history")."""
        return self._execute("DELETE FROM conversations WHERE owner = %s", (owner,)).rowcount
