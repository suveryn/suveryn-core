"""Cases, suveryn-tracker#10: the file a confidential profession works on, with its
documents and conversations. Design: docs/design/cases.md.

Stages 1 and 2 of that design are here: the case with its creator as manager, the personal
space (``case_id`` null) for everything outside a case, "ask about this case", the authorisation
function ``may`` with its rules; then members with roles (reader, contributor, manager; exactly
one manager, handed over by the manager or an administrator), the appliance's office-wide
default, restriction by the manager, and the access log (``case_events``: who did what in a
case, kept ``EVENT_RETENTION_DAYS`` and then deleted, as the sign-in events); then stage 3:
closing. A closed case is read-only (no uploads, no questions, no changes) and can be reopened by
its manager while it is kept. The office chooses how long closed cases are kept
(``SUVERYN_CASES_KEEP``: 6 months, 1 year, 5 years, or ``manual``, until deleted by hand; nothing
is chosen for them, so the default is ``manual``). Closing sets ``keep_until``; in the month
before it the case is listed as due (``due``) and its manager or an administrator can extend
it by one period, reopen it, or mark it ``keep`` (never deleted by the period). Then the
gateway's sweep (hourly) deletes the case with its documents, index, conversations and log. What
deletion guarantees is the same as for a document (``Store.delete_document``: unreachable, not
unrecoverable; see the data lifecycle, suveryn-tracker#31). Stage 4: a conversation in a
case can be shared with the case (``conversations.py``), and the office's two settings, the
default access and the keep period, are changed by an administrator in the dashboard
(``case_settings`` table): the environment gives the values the appliance was provisioned with,
the table what an administrator chose since (``CaseStore.overrides``), and the gateway merges
them on every request (``CaseSettings.with_overrides``). An administrator also lists every case
(``list_all``, with who manages it) and hands cases over from there.

What is stored: the office's own file number (``reference``), a name, the case type, a short
subject, who manages it and when it was opened. Never a client's name as a label (decision 2):
the parties are information inside the case's documents. The gateway never reads a case's
documents here; they live in the rag store, keyed by ``case_id``.

Authorisation (``may``): every request about a case goes through this one function, on the
server. The rules, from the design:

1. An administrator (Keycloak role ``suveryn-admin``) may list cases, hand one over, read its
   access log and set its keep period; nothing else without membership. The access log is the
   manager's to read too.
2. A member's role gives the rights of the roles table: a reader reads and exports, a
   contributor also uploads, asks and runs playbooks, a manager also manages the case.
3. In an office-wide appliance (``SUVERYN_CASES_DEFAULT_ACCESS=office``) everyone signed in is a
   reader of an unrestricted case. Membership adds rights, never takes them away.
4. A closed case allows reading and exporting only, for everyone; and ``reopen`` and ``set_keep``
   for its manager (``close`` is the manager's on an open case).
5. The personal space is its owner's only, as before cases existed.

Fail closed: the default access, when the appliance hasn't chosen one, is members only.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

import psycopg
from pydantic import BaseModel, Field

from .db import PgStore

Access = Literal["default", "restricted"]
State = Literal["open", "closed"]
Role = Literal["reader", "contributor", "manager"]
Action = Literal["read", "contribute", "manage", "close", "reopen", "list", "handover", "read_log", "set_keep"]

READ: frozenset[str] = frozenset({"read"})
CONTRIBUTE: frozenset[str] = READ | {"contribute"}
MANAGE: frozenset[str] = CONTRIBUTE | {"manage", "close", "reopen", "read_log", "set_keep"}
ADMIN: frozenset[str] = frozenset({"list", "handover", "read_log", "set_keep"})
RIGHTS: dict[str, frozenset[str]] = {"reader": READ, "contributor": CONTRIBUTE, "manager": MANAGE}
MAX_SUBJECT_BYTES = 8 * 1024
EVENT_RETENTION_DAYS = 180  # as the sign-in events (suveryn-tracker#16)
MAX_EVENTS = 1000           # one listing of the access log
DUE_WARNING_DAYS = 30       # a closed case is listed as due this long before its deletion
KEEP_PERIODS: dict[str, timedelta | None] = {"6m": timedelta(days=183), "1y": timedelta(days=366),
                                             "5y": timedelta(days=5 * 366), "manual": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          uuid PRIMARY KEY,
    reference   text NOT NULL,
    name        text NOT NULL,
    type        text NOT NULL,
    subject     jsonb NOT NULL DEFAULT '{}'::jsonb,
    access      text NOT NULL DEFAULT 'default' CHECK (access IN ('default', 'restricted')),
    state       text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
    opened_at   timestamptz NOT NULL DEFAULT now(),
    closed_at   timestamptz,
    keep_until  timestamptz,
    keep        boolean NOT NULL DEFAULT false,
    manager     text NOT NULL,
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS cases_reference_lower ON cases (lower(reference));
CREATE INDEX IF NOT EXISTS cases_state_updated ON cases (state, updated_at DESC);
CREATE TABLE IF NOT EXISTS case_members (
    case_id   uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    "user"    text NOT NULL,
    role      text NOT NULL CHECK (role IN ('reader', 'contributor', 'manager')),
    added_by  text NOT NULL,
    added_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, "user")
);
CREATE INDEX IF NOT EXISTS case_members_user ON case_members ("user");
ALTER TABLE case_members ADD COLUMN IF NOT EXISTS username text NOT NULL DEFAULT '';
ALTER TABLE case_members ADD COLUMN IF NOT EXISTS name text NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS case_events (
    id       bigserial PRIMARY KEY,
    case_id  uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    "user"   text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now(),
    action   text NOT NULL,
    detail   jsonb NOT NULL DEFAULT '{}'::jsonb
);
-- A case's log newest first, and its latest line (``last_activity``), straight from the index.
DROP INDEX IF EXISTS case_events_case_at;
CREATE INDEX IF NOT EXISTS case_events_case_latest ON case_events (case_id, at DESC, id DESC);
CREATE TABLE IF NOT EXISTS case_pins (
    case_id   uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    "user"    text NOT NULL,
    pinned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, "user")
);
CREATE INDEX IF NOT EXISTS case_events_at ON case_events (at);
ALTER TABLE cases ADD COLUMN IF NOT EXISTS confidential boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS case_settings (
    key        text PRIMARY KEY,
    value      text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL DEFAULT ''
);
"""

SETTING_KEYS = ("default_access", "keep", "conversations_keep")  # what an administrator may change at runtime


class StrictlyConfidential(ValueError):
    """The change isn't allowed while the case is strictly confidential (docs/design/chat-ui.md §11)."""


class DuplicateReference(ValueError):
    """Another case already has this reference (the office's file numbers are unique)."""


@dataclass(frozen=True)
class CaseSettings:
    """Where cases are stored and the appliance's default access; build with ``from_env()``."""

    database_url: str = ""
    default_access: Literal["office", "members"] = "members"  # fail closed
    keep: Literal["6m", "1y", "5y", "manual"] = "manual"      # how long closed cases are kept; manual: until deleted by hand
    conversations_keep: Literal["6m", "1y", "5y", "manual"] = "manual"  # saved conversations, from their last change

    @property
    def office_wide(self) -> bool:
        return self.default_access == "office"

    @property
    def keep_period(self) -> timedelta | None:
        return KEEP_PERIODS[self.keep]

    def with_overrides(self, overrides: dict[str, str]) -> CaseSettings:
        """These settings with what an administrator chose since provisioning (``CaseStore.overrides``)
        on top; an unknown or invalid value is ignored, so a bad row can never lock the office out."""
        changes = {}
        if overrides.get("default_access") in ("office", "members"):
            changes["default_access"] = overrides["default_access"]
        if overrides.get("keep") in KEEP_PERIODS:
            changes["keep"] = overrides["keep"]
        if overrides.get("conversations_keep") in KEEP_PERIODS:
            changes["conversations_keep"] = overrides["conversations_keep"]
        return replace(self, **changes) if changes else self

    @classmethod
    def from_env(cls) -> CaseSettings:
        access = os.environ.get("SUVERYN_CASES_DEFAULT_ACCESS", "members").strip().lower() or "members"
        if access not in ("office", "members"):
            raise ValueError("SUVERYN_CASES_DEFAULT_ACCESS must be 'office' or 'members'")
        keep = os.environ.get("SUVERYN_CASES_KEEP", "manual").strip().lower() or "manual"
        if keep not in KEEP_PERIODS:
            raise ValueError("SUVERYN_CASES_KEEP must be '6m', '1y', '5y' or 'manual'")
        conversations = os.environ.get("SUVERYN_CONVERSATIONS_KEEP", "manual").strip().lower() or "manual"
        if conversations not in KEEP_PERIODS:
            raise ValueError("SUVERYN_CONVERSATIONS_KEEP must be '6m', '1y', '5y' or 'manual'")
        return cls(database_url=os.environ.get("SUVERYN_DATABASE_URL", ""), default_access=access, keep=keep,
                   conversations_keep=conversations)


class CaseIn(BaseModel):
    """Body of ``POST /v1/cases``: the office's file number, a name, the type and the subject."""

    reference: str = Field(min_length=1, max_length=100, pattern=r"^\S(.*\S)?$")
    name: str = Field(min_length=1, max_length=200, pattern=r"^\S(.*\S)?$")
    type: str = Field(min_length=1, max_length=50, pattern=r"^\S(.*\S)?$")
    subject: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    access: Access = "default"


class CaseUpdate(BaseModel):
    """Body of ``PATCH /v1/cases/{id}``: what a manager may change. Fields left out stay as they are."""

    reference: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^\S(.*\S)?$")
    name: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^\S(.*\S)?$")
    type: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^\S(.*\S)?$")
    subject: dict[str, str | int | float | bool | None] | None = None
    access: Access | None = None
    # Strictly confidential (docs/design/chat-ui.md §11): members only, no shared conversations,
    # watermarked exports, shielded titles in the lists. Turning it on restricts the access too.
    confidential: bool | None = None


class Case(BaseModel):
    """A case as the API returns it. ``my_role`` is the caller's: a member's role, ``reader`` for a
    non-member in an office-wide appliance, None for an administrator who only sees it exists."""

    id: str
    reference: str
    name: str
    type: str
    subject: dict
    access: Access
    state: State
    opened_at: datetime
    closed_at: datetime | None
    keep_until: datetime | None
    keep: bool
    manager: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    confidential: bool = False  # strictly confidential (docs/design/chat-ui.md §11)
    my_role: Role | None = None
    pinned: bool = False  # by the caller, for the sidebar's "pinned" section (docs/design/chat-ui.md)


class CaseOverview(Case):
    """A case as the Cases overview shows it (docs/design/chat-ui.md §4): with its members (the
    manager first) and its last activity, who and when, from the access log. For an administrator who
    isn't a member, no members: only that the case exists."""

    members: list[Member] = []
    last_activity_at: datetime | None = None
    last_activity_by: str = ""  # their name as the case knows it, or empty


class AdminCase(Case):
    """A case as the administrator's list shows it (stage 4): with its manager's name and how many
    members it has. Nothing from inside the case."""

    manager_username: str = ""
    manager_name: str = ""
    members: int = 0


class SettingsOut(BaseModel):
    """The office's case settings as they apply now (``GET /v1/admin/cases/settings``)."""

    default_access: Literal["office", "members"]
    keep: Literal["6m", "1y", "5y", "manual"]
    conversations_keep: Literal["6m", "1y", "5y", "manual"]
    updated_at: datetime | None = None  # None: as provisioned, never changed in the dashboard
    updated_by: str = ""


class SettingsIn(BaseModel):
    """Body of ``PUT /v1/admin/cases/settings``: what to change; a field left out stays."""

    default_access: Literal["office", "members"] | None = None
    keep: Literal["6m", "1y", "5y", "manual"] | None = None
    conversations_keep: Literal["6m", "1y", "5y", "manual"] | None = None


class Member(BaseModel):
    """One member of a case, as the API lists it (the name as it was when they were added)."""

    user: str
    username: str
    name: str
    role: Role
    added_by: str
    added_at: datetime
    admin: bool = False        # an administrator (the avatar's badge), from the directory
    avatar: str | None = None  # the ETag of their picture, None without one


class MemberIn(BaseModel):
    """Body of ``PUT /v1/cases/{id}/members/{user}``."""

    role: Role


class HandoverIn(BaseModel):
    """Body of ``POST /v1/cases/{id}/handover``: the member (or colleague) who takes the case over."""

    user: str = Field(min_length=1, max_length=200)


class PinIn(BaseModel):
    """Body of ``PUT /v1/cases/{id}/pin``: whether the caller pins the case in their sidebar."""

    pinned: bool


class KeepIn(BaseModel):
    """Body of ``POST /v1/cases/{id}/keep``: mark the case kept (never deleted by the period) or
    not, or extend its deletion by one period."""

    keep: bool | None = None
    extend: bool = False


class CaseEvent(BaseModel):
    """One line of a case's access log: who, when, what (never document text)."""

    id: int
    user: str
    at: datetime
    action: str
    detail: dict


@dataclass(frozen=True)
class Principal:
    """Who asks: their Keycloak id and whether they are an administrator."""

    sub: str
    admin: bool = False


def may(who: Principal, case: Case, role: Role | None, action: Action, office_wide: bool) -> bool:
    """Whether ``who``, with ``role`` in ``case`` (None: not a member), may do ``action``.

    The one place the rules in this module's docstring are decided. ``office_wide`` is the
    appliance's default access (rule 3).
    """
    if action == "read_log" and (who.admin or role == "manager"):
        return True  # decision 15: the manager and the administrators, open or closed
    if action == "set_keep":
        return case.state == "closed" and (who.admin or role == "manager")  # the keep period of a closed case
    if action in ADMIN:
        return who.admin  # rule 1: administrators, on every case; nobody else
    effective = role
    if effective is None and office_wide and case.access == "default":
        effective = "reader"  # rule 3
    if effective is None:
        return False
    if case.state == "closed":  # rule 4
        if action in ("reopen", "set_keep"):
            return effective == "manager"
        return action in READ
    return action in RIGHTS[effective] - {"reopen", "read_log", "set_keep"}


class CaseStore(PgStore):
    """Cases and their members in PostgreSQL. Creates its tables on connect.

    The store decides nothing: it stores and lists, and ``role_of`` says what a user is in a case;
    the gateway calls ``may`` before anything is read or changed.
    """

    schema = SCHEMA

    def __init__(self, settings: CaseSettings):
        super().__init__(settings.database_url)
        self.settings = settings
        self._overrides: dict[str, str] | None = None
        self._overrides_meta: tuple[datetime, str] | None = None

    COLUMNS = ("id", "reference", "name", "type", "subject", "access", "state", "opened_at", "closed_at",
               "keep_until", "keep", "manager", "created_by", "created_at", "updated_at", "confidential")
    _COLS = ", ".join(COLUMNS)
    _SELECT = "SELECT " + ", ".join(f"c.{c}" for c in COLUMNS)

    @classmethod
    def _case(cls, row, role: str | None = None, pinned: bool = False) -> Case:
        values = dict(zip(cls.COLUMNS, row))
        values["id"] = str(values["id"])
        return Case(**values, my_role=role, pinned=pinned)

    def create(self, body: CaseIn, user: str, username: str = "", name: str = "") -> Case:
        """A new open case, managed by its creator, who is its first member."""
        case_id = uuid.uuid4()
        try:
            with self.transaction():  # the case, its manager and the first log line: all or nothing
                row = self._execute(
                    "INSERT INTO cases (id, reference, name, type, subject, access, manager, created_by)"
                    f" VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {self._COLS}",
                    (case_id, body.reference, body.name, body.type, json.dumps(body.subject), body.access, user, user)).fetchone()
                self._execute('INSERT INTO case_members (case_id, "user", role, added_by, username, name)'
                              " VALUES (%s, %s, %s, %s, %s, %s)", (case_id, user, "manager", user, username, name))
                self.log(case_id, user, "created", {})
        except psycopg.errors.UniqueViolation as e:
            raise DuplicateReference(body.reference) from e
        return self._case(row, "manager")

    def get(self, case_id: uuid.UUID, user: str) -> Case | None:
        """The case with the user's role in it (None if not a member), or None if it doesn't exist."""
        row = self._execute(
            f'{self._SELECT}, m.role, (p."user" IS NOT NULL) FROM cases c'
            ' LEFT JOIN case_members m ON m.case_id = c.id AND m."user" = %s'
            ' LEFT JOIN case_pins p ON p.case_id = c.id AND p."user" = %s'
            " WHERE c.id = %s", (user, user, case_id)).fetchone()
        return self._case(row[:-2], row[-2], row[-1]) if row else None

    def role_of(self, case_id: uuid.UUID, user: str) -> Role | None:
        row = self._execute('SELECT role FROM case_members WHERE case_id = %s AND "user" = %s', (case_id, user)).fetchone()
        return row[0] if row else None

    def list(self, user: str, *, office_wide: bool, admin: bool = False, closed: bool = False) -> list[Case]:
        """The cases the user may see, open ones first, most recently changed first: their own
        (as a member), every unrestricted case in an office-wide appliance, and every case for an
        administrator (who sees it exists and who manages it; ``my_role`` says whether they may
        read it). Closed cases only with ``closed``."""
        visible = ["m.role IS NOT NULL"]
        if office_wide:
            visible.append("c.access = 'default'")
        if admin:
            visible.append("true")
        rows = self._execute(
            f'{self._SELECT}, m.role, (p."user" IS NOT NULL) FROM cases c'
            ' LEFT JOIN case_members m ON m.case_id = c.id AND m."user" = %s'
            ' LEFT JOIN case_pins p ON p.case_id = c.id AND p."user" = %s'
            f" WHERE ({' OR '.join(visible)}) AND (%s OR c.state = 'open')"
            " ORDER BY (c.state = 'open') DESC, c.updated_at DESC", (user, user, closed)).fetchall()
        cases = []
        for row in rows:
            role, pinned = row[-2], row[-1]
            if role is None and office_wide and row[5] == "default":
                role = "reader"
            cases.append(self._case(row[:-2], role, pinned))
        return cases

    def confidential_ids(self, case_ids: list[uuid.UUID]) -> set[str]:
        """Which of these cases are strictly confidential (their conversations' titles are shielded)."""
        if not case_ids:
            return set()
        rows = self._execute("SELECT id FROM cases WHERE confidential AND id = ANY(%s)", (case_ids,)).fetchall()
        return {str(r[0]) for r in rows}

    def set_pinned(self, case_id: uuid.UUID, user: str, pinned: bool) -> None:
        """Pin or unpin a case for one user (the sidebar's "pinned" section, docs/design/chat-ui.md)."""
        if pinned:
            self._execute('INSERT INTO case_pins (case_id, "user") VALUES (%s, %s) ON CONFLICT DO NOTHING', (case_id, user))
        else:
            self._execute('DELETE FROM case_pins WHERE case_id = %s AND "user" = %s', (case_id, user))

    def pinned_by(self, case_id: uuid.UUID, user: str) -> bool:
        return self._execute('SELECT 1 FROM case_pins WHERE case_id = %s AND "user" = %s', (case_id, user)).fetchone() is not None

    def update(self, case_id: uuid.UUID, body: CaseUpdate) -> Case | None:
        """Change what ``body`` sets; None if the case doesn't exist. Strictly confidential means
        members only: turning it on restricts the access, and the access can't be opened while it is
        on (``StrictlyConfidential``)."""
        fields = body.model_dump(exclude_none=True)
        # Opening the access is refused by the UPDATE itself while the label is on, not by a read before
        # it: two managers changing the case at once can't leave it confidential and open to the office
        # (external review, pass 6). Under READ COMMITTED a concurrent change to the row is waited for,
        # and the condition is checked again on what it wrote.
        opens = fields.get("access") == "default" and fields.get("confidential") is not False
        if fields.get("confidential"):
            fields["access"] = "restricted"
        if not fields:
            row = self._execute(f"{self._SELECT} FROM cases c WHERE c.id = %s", (case_id,)).fetchone()
            return self._case(row) if row else None
        if "subject" in fields:
            fields["subject"] = json.dumps(fields["subject"])
        sets = ", ".join(f"{k} = %s" for k in fields)
        guard = " AND NOT confidential" if opens else ""
        try:
            row = self._execute(
                f"UPDATE cases SET {sets}, updated_at = now() WHERE id = %s{guard} RETURNING {self._COLS}",
                (*fields.values(), case_id)).fetchone()
        except psycopg.errors.UniqueViolation as e:
            raise DuplicateReference(body.reference or "") from e
        if row is None and opens and self._execute("SELECT 1 FROM cases WHERE id = %s", (case_id,)).fetchone():
            raise StrictlyConfidential("a strictly confidential case is for its members only")
        return self._case(row) if row else None

    # ------------------------------------------------------------------ closing (stage 3)
    def close_case(self, case_id: uuid.UUID, period: timedelta | None) -> Case | None:
        """Close an open case: read-only from now, to be deleted after ``period`` (None: kept until
        deleted by hand). None if the case doesn't exist or isn't open."""
        now = datetime.now(UTC)
        row = self._execute(
            f"UPDATE cases SET state = 'closed', closed_at = %s, keep_until = %s, keep = false, updated_at = now()"
            f" WHERE id = %s AND state = 'open' RETURNING {self._COLS}",
            (now, now + period if period else None, case_id)).fetchone()
        return self._case(row) if row else None

    def reopen_case(self, case_id: uuid.UUID) -> Case | None:
        """Reopen a closed case: open again, no deletion planned. None if it doesn't exist or is open."""
        row = self._execute(
            f"UPDATE cases SET state = 'open', closed_at = NULL, keep_until = NULL, keep = false, updated_at = now()"
            f" WHERE id = %s AND state = 'closed' RETURNING {self._COLS}", (case_id,)).fetchone()
        return self._case(row) if row else None

    def set_keep(self, case_id: uuid.UUID, keep: bool | None, extend: bool, period: timedelta | None) -> Case | None:
        """Mark a closed case kept (``keep`` True: never deleted by the period) or not (False: deleted
        one period from now), and/or ``extend`` its deletion by one period from its current date (or
        from now, if that date has passed). None if the case doesn't exist or isn't closed."""
        with self.transaction():  # read, decide, write: with the row locked, two changes at once can't lose one
            row = self._execute("SELECT keep_until, keep FROM cases WHERE id = %s AND state = 'closed' FOR UPDATE",
                                (case_id,)).fetchone()
            if row is None:
                return None
            keep_until, kept = row
            now = datetime.now(UTC)
            if keep is not None:
                kept = keep
                if not keep:
                    keep_until = now + period if period else None
            if extend and period:
                keep_until = max(keep_until or now, now) + period
            row = self._execute(f"UPDATE cases SET keep_until = %s, keep = %s, updated_at = now() WHERE id = %s RETURNING {self._COLS}",
                                (keep_until, kept, case_id)).fetchone()
        return self._case(row) if row else None

    def due(self, user: str, *, admin: bool, within: timedelta = timedelta(days=DUE_WARNING_DAYS)) -> list[Case]:
        """Closed cases due for deletion within ``within`` (or overdue), not marked kept: for an
        administrator all of them, for anyone else those they manage. Soonest first."""
        rows = self._execute(
            f'{self._SELECT}, m.role FROM cases c LEFT JOIN case_members m ON m.case_id = c.id AND m."user" = %s'
            " WHERE c.state = 'closed' AND NOT c.keep AND c.keep_until IS NOT NULL AND c.keep_until <= now() + %s"
            "   AND (%s OR c.manager = %s) ORDER BY c.keep_until", (user, within, admin, user)).fetchall()
        return [self._case(r[:-1], r[-1]) for r in rows]

    def due_for_deletion(self) -> list[uuid.UUID]:
        """The closed cases whose keep period has passed and that aren't marked kept."""
        rows = self._execute("SELECT id FROM cases WHERE state = 'closed' AND NOT keep AND keep_until IS NOT NULL"
                             " AND keep_until <= now()").fetchall()
        return [r[0] for r in rows]

    def touch(self, case_id: uuid.UUID) -> None:
        """Note activity in the case (an upload, a question): the list is ordered by it."""
        self._execute("UPDATE cases SET updated_at = now() WHERE id = %s", (case_id,))

    def delete(self, case_id: uuid.UUID) -> bool:
        """Delete the case and its members. Its documents and conversations are the other stores'
        to delete (the gateway does, by ``case_id``), before this."""
        return self._execute("DELETE FROM cases WHERE id = %s", (case_id,)).rowcount > 0

    def list_all(self) -> list[AdminCase]:
        """Every case, open ones first, most recently changed first, with its manager's name and
        its member count: the administrator's list (stage 4). Nothing from inside a case."""
        rows = self._execute(
            f"{self._SELECT}, m.username, m.name, (SELECT count(*) FROM case_members x WHERE x.case_id = c.id)"
            ' FROM cases c LEFT JOIN case_members m ON m.case_id = c.id AND m."user" = c.manager'
            " ORDER BY c.state = 'closed', c.updated_at DESC").fetchall()
        return [AdminCase(**self._case(r[:-3]).model_dump(), manager_username=r[-3] or "", manager_name=r[-2] or "",
                          members=r[-1]) for r in rows]

    # ------------------------------------------------------------------ the office's settings (stage 4)
    def overrides(self) -> dict[str, str]:
        """What an administrator chose in the dashboard, by key (``SETTING_KEYS``); empty until
        they change something. Read once and kept in memory (one gateway per appliance), refreshed
        by ``set_overrides``."""
        if self._overrides is None:
            rows = self._execute("SELECT key, value, updated_at, updated_by FROM case_settings").fetchall()
            self._overrides = {r[0]: r[1] for r in rows if r[0] in SETTING_KEYS}
            self._overrides_meta = max(((r[2], r[3]) for r in rows), default=None)
        return dict(self._overrides)

    def overrides_meta(self) -> tuple[datetime, str] | None:
        """When and by whom the settings were last changed in the dashboard; None if never."""
        self.overrides()
        return self._overrides_meta

    def set_overrides(self, changes: dict[str, str], by: str) -> dict[str, str]:
        """Store what an administrator chose; returns the overrides as they are now."""
        with self.transaction():
            for key, value in changes.items():
                if key not in SETTING_KEYS:
                    raise ValueError(f"not a setting: {key}")
                self._execute("INSERT INTO case_settings (key, value, updated_at, updated_by) VALUES (%s, %s, now(), %s)"
                              " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by",
                              (key, value, by))
        self._overrides = None
        return self.overrides()

    def manages(self, user: str) -> int:
        """How many cases this user manages (an account can't go while it manages one, decision 6)."""
        return self._execute("SELECT count(*) FROM cases WHERE manager = %s", (user,)).fetchone()[0]

    # ------------------------------------------------------------------ members (stage 2)
    def members(self, case_id: uuid.UUID) -> list[Member]:
        """The case's members, its manager first, then by name."""
        rows = self._execute('SELECT "user", username, name, role, added_by, added_at FROM case_members WHERE case_id = %s'
                             " ORDER BY (role = 'manager') DESC, lower(name), username", (case_id,)).fetchall()
        return [Member(user=r[0], username=r[1], name=r[2], role=r[3], added_by=r[4], added_at=r[5]) for r in rows]

    def set_member(self, case_id: uuid.UUID, user: str, role: Role, by: str, username: str = "", name: str = "") -> Member:
        """Add a member, or change their role. Not for the manager role: use ``set_manager``
        (there is exactly one manager, decision 6)."""
        if role == "manager":
            raise ValueError("use set_manager")
        row = self._execute(
            'INSERT INTO case_members (case_id, "user", role, added_by, username, name) VALUES (%s, %s, %s, %s, %s, %s)'
            ' ON CONFLICT (case_id, "user") DO UPDATE SET role = EXCLUDED.role,'
            "   username = CASE WHEN EXCLUDED.username = '' THEN case_members.username ELSE EXCLUDED.username END,"
            "   name = CASE WHEN EXCLUDED.name = '' THEN case_members.name ELSE EXCLUDED.name END"
            " WHERE case_members.role <> 'manager'"
            ' RETURNING "user", username, name, role, added_by, added_at', (case_id, user, role, by, username, name)).fetchone()
        if row is None:
            raise ValueError("the manager's role is changed by handing the case over")
        return Member(user=row[0], username=row[1], name=row[2], role=row[3], added_by=row[4], added_at=row[5])

    def remove_member(self, case_id: uuid.UUID, user: str) -> bool:
        """Remove a member; never the manager (hand the case over first). False if not a member."""
        return self._execute('DELETE FROM case_members WHERE case_id = %s AND "user" = %s AND role <> \'manager\'',
                             (case_id, user)).rowcount > 0

    def set_manager(self, case_id: uuid.UUID, user: str, by: str, username: str = "", name: str = "") -> Case | None:
        """Hand the case over: ``user`` becomes its manager (added as a member if needed), the
        previous manager stays on as a contributor. One transaction. None if the case doesn't exist."""
        with self.transaction():
            row = self._execute("SELECT manager FROM cases WHERE id = %s FOR UPDATE", (case_id,)).fetchone()
            if row is None:
                return None
            previous = row[0]
            if previous != user:
                self._execute('UPDATE case_members SET role = %s WHERE case_id = %s AND "user" = %s',
                              ("contributor", case_id, previous))
                self._execute(
                    'INSERT INTO case_members (case_id, "user", role, added_by, username, name) VALUES (%s, %s, %s, %s, %s, %s)'
                    ' ON CONFLICT (case_id, "user") DO UPDATE SET role = EXCLUDED.role,'
                    "   username = CASE WHEN EXCLUDED.username = '' THEN case_members.username ELSE EXCLUDED.username END,"
                    "   name = CASE WHEN EXCLUDED.name = '' THEN case_members.name ELSE EXCLUDED.name END",
                    (case_id, user, "manager", by, username, name))
            row = self._execute(f"UPDATE cases SET manager = %s, updated_at = now() WHERE id = %s RETURNING {self._COLS}",
                                (user, case_id)).fetchone()
        return self._case(row, self.role_of(case_id, by))

    def members_of(self, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Member]]:
        """The members of several cases at once, the manager first, then by name (the overviews)."""
        rows = self._execute('SELECT case_id, "user", username, name, role, added_by, added_at FROM case_members'
                             " WHERE case_id = ANY(%s) ORDER BY case_id, (role = 'manager') DESC, lower(name), username",
                             (list(case_ids),)).fetchall()
        out: dict[uuid.UUID, list[Member]] = {c: [] for c in case_ids}
        for r in rows:
            out.setdefault(r[0], []).append(Member(user=r[1], username=r[2], name=r[3], role=r[4], added_by=r[5], added_at=r[6]))
        return out

    def last_activity(self, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[datetime, str]]:
        """Per case, the latest line of its access log: when, and who (their Keycloak id). One look in the
        index per case: ``DISTINCT ON`` over the log read every line of every case (1 s for 300 cases with
        3,000 lines each), and the log keeps 180 days."""
        rows = self._execute('SELECT c.id, e.at, e."user" FROM unnest(%s::uuid[]) AS c (id)'
                             ' CROSS JOIN LATERAL (SELECT at, "user" FROM case_events WHERE case_id = c.id'
                             "                     ORDER BY at DESC, id DESC LIMIT 1) AS e", (list(case_ids),)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    # ------------------------------------------------------------------ the access log (stage 2)
    def log(self, case_id: uuid.UUID, user: str, action: str, detail: dict | None = None) -> None:
        """One line: who did what in the case. ``detail`` names ids and roles, never text."""
        self._execute('INSERT INTO case_events (case_id, "user", action, detail) VALUES (%s, %s, %s, %s)',
                      (case_id, user, action, json.dumps(detail or {})))

    def events(self, case_id: uuid.UUID, limit: int = MAX_EVENTS) -> list[CaseEvent]:
        """The case's access log, newest first, within the retention."""
        self.purge_events()
        rows = self._execute('SELECT id, "user", at, action, detail FROM case_events WHERE case_id = %s'
                             " ORDER BY at DESC, id DESC LIMIT %s", (case_id, limit)).fetchall()
        return [CaseEvent(id=r[0], user=r[1], at=r[2], action=r[3], detail=r[4]) for r in rows]

    def purge_events(self) -> int:
        """Delete access-log lines older than the retention; how many."""
        return self._execute("DELETE FROM case_events WHERE at < now() - make_interval(days => %s)",
                             (EVENT_RETENTION_DAYS,)).rowcount
