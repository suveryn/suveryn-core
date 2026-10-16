"""Cases (dossiers), suveryn-tracker#10: the file a confidential profession works on, with its
documents and conversations. Design: docs/design/cases.md.

This is stage 1 of that design: a case with a single member (its creator, who manages it), the
personal space (``case_id`` null) for everything outside a case, "ask about this case", and the
authorisation function ``may`` with its rules. Members and roles beyond the creator, the access
log, closing and the keep period, and shared conversations come in the later stages; the data
model already has their columns so nothing is migrated twice.

What is stored: the office's own file number (``reference``), a name, the case type, a short
subject, who manages it and when it was opened. Never a client's name as a label (decision 2):
the parties are information inside the case's documents. The gateway never reads a case's
documents here; they live in the rag store, keyed by ``case_id``.

Authorisation (``may``): every request about a case goes through this one function, on the
server. The rules, from the design:

1. An administrator (Keycloak role ``suveryn-admin``) may list cases, hand one over, read its
   access log and set its keep period; nothing else without membership.
2. A member's role gives the rights of the roles table: a reader reads and exports, a
   contributor also uploads, asks and runs playbooks, a manager also manages the case.
3. In an office-wide appliance (``SUVERYN_CASES_DEFAULT_ACCESS=office``) everyone signed in is a
   reader of an unrestricted case. Membership adds rights, never takes them away.
4. A closed case allows reading and exporting only, for everyone, and ``reopen`` for its manager.
5. The personal space is its owner's only, as before cases existed.

Fail closed: the default access, when the appliance hasn't chosen one, is members only.
"""

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import psycopg
from pydantic import BaseModel, Field

from .db import PgStore

Access = Literal["default", "restricted"]
State = Literal["open", "closed"]
Role = Literal["reader", "contributor", "manager"]
Action = Literal["read", "contribute", "manage", "reopen", "list", "handover", "read_log", "set_keep"]

READ: frozenset[str] = frozenset({"read"})
CONTRIBUTE: frozenset[str] = READ | {"contribute"}
MANAGE: frozenset[str] = CONTRIBUTE | {"manage", "reopen"}
ADMIN: frozenset[str] = frozenset({"list", "handover", "read_log", "set_keep"})
RIGHTS: dict[str, frozenset[str]] = {"reader": READ, "contributor": CONTRIBUTE, "manager": MANAGE}
MAX_SUBJECT_BYTES = 8 * 1024

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
"""


class DuplicateReference(ValueError):
    """Another case already has this reference (the office's file numbers are unique)."""


@dataclass(frozen=True)
class CaseSettings:
    """Where cases are stored and the appliance's default access; build with ``from_env()``."""

    database_url: str = ""
    default_access: Literal["office", "members"] = "members"  # fail closed

    @property
    def office_wide(self) -> bool:
        return self.default_access == "office"

    @classmethod
    def from_env(cls) -> "CaseSettings":
        access = os.environ.get("SUVERYN_CASES_DEFAULT_ACCESS", "members").strip().lower() or "members"
        if access not in ("office", "members"):
            raise ValueError("SUVERYN_CASES_DEFAULT_ACCESS must be 'office' or 'members'")
        return cls(database_url=os.environ.get("SUVERYN_DATABASE_URL", ""), default_access=access)


class CaseIn(BaseModel):
    """Body of ``POST /v1/cases``: the office's file number, a name, the type and the subject."""

    reference: str = Field(min_length=1, max_length=100, pattern=r"^\S(.*\S)?$")
    name: str = Field(min_length=1, max_length=200, pattern=r"^\S(.*\S)?$")
    type: str = Field(min_length=1, max_length=50, pattern=r"^[\w-]+$")
    subject: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    access: Access = "default"


class CaseUpdate(BaseModel):
    """Body of ``PATCH /v1/cases/{id}``: what a manager may change. Fields left out stay as they are."""

    reference: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^\S(.*\S)?$")
    name: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^\S(.*\S)?$")
    type: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[\w-]+$")
    subject: dict[str, str | int | float | bool | None] | None = None
    access: Access | None = None


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
    my_role: Role | None = None


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
    if action in ADMIN:
        return who.admin  # rule 1: administrators, on every case; nobody else
    effective = role
    if effective is None and office_wide and case.access == "default":
        effective = "reader"  # rule 3
    if effective is None:
        return False
    if case.state == "closed":  # rule 4
        if action == "reopen":
            return effective == "manager"
        return action in READ
    return action in RIGHTS[effective] - {"reopen"}


class CaseStore(PgStore):
    """Cases and their members in PostgreSQL. Creates its tables on connect.

    The store decides nothing: it stores and lists, and ``role_of`` says what a user is in a case;
    the gateway calls ``may`` before anything is read or changed.
    """

    schema = SCHEMA

    def __init__(self, settings: CaseSettings):
        super().__init__(settings.database_url)
        self.settings = settings

    COLUMNS = ("id", "reference", "name", "type", "subject", "access", "state", "opened_at", "closed_at",
               "keep_until", "keep", "manager", "created_by", "created_at", "updated_at")
    _COLS = ", ".join(COLUMNS)
    _SELECT = "SELECT " + ", ".join(f"c.{c}" for c in COLUMNS)

    @classmethod
    def _case(cls, row, role: str | None = None) -> Case:
        values = dict(zip(cls.COLUMNS, row))
        values["id"] = str(values["id"])
        return Case(**values, my_role=role)

    def create(self, body: CaseIn, user: str) -> Case:
        """A new open case, managed by its creator, who is its only member (stage 1)."""
        case_id = uuid.uuid4()
        try:
            row = self._execute(
                "INSERT INTO cases (id, reference, name, type, subject, access, manager, created_by)"
                f" VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {self._COLS}",
                (case_id, body.reference, body.name, body.type, json.dumps(body.subject), body.access, user, user)).fetchone()
        except psycopg.errors.UniqueViolation as e:
            raise DuplicateReference(body.reference) from e
        self._execute('INSERT INTO case_members (case_id, "user", role, added_by) VALUES (%s, %s, %s, %s)',
                      (case_id, user, "manager", user))
        return self._case(row, "manager")

    def get(self, case_id: uuid.UUID, user: str) -> Case | None:
        """The case with the user's role in it (None if not a member), or None if it doesn't exist."""
        row = self._execute(
            f'{self._SELECT}, m.role FROM cases c LEFT JOIN case_members m ON m.case_id = c.id AND m."user" = %s'
            " WHERE c.id = %s", (user, case_id)).fetchone()
        return self._case(row[:-1], row[-1]) if row else None

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
            f'{self._SELECT}, m.role FROM cases c LEFT JOIN case_members m ON m.case_id = c.id AND m."user" = %s'
            f" WHERE ({' OR '.join(visible)}) AND (%s OR c.state = 'open')"
            " ORDER BY (c.state = 'open') DESC, c.updated_at DESC", (user, closed)).fetchall()
        cases = []
        for row in rows:
            role = row[-1]
            if role is None and office_wide and row[5] == "default":
                role = "reader"
            cases.append(self._case(row[:-1], role))
        return cases

    def update(self, case_id: uuid.UUID, body: CaseUpdate) -> Case | None:
        """Change what ``body`` sets; None if the case doesn't exist."""
        fields = body.model_dump(exclude_none=True)
        if not fields:
            row = self._execute(f"{self._SELECT} FROM cases c WHERE c.id = %s", (case_id,)).fetchone()
            return self._case(row) if row else None
        if "subject" in fields:
            fields["subject"] = json.dumps(fields["subject"])
        sets = ", ".join(f"{k} = %s" for k in fields)
        try:
            row = self._execute(
                f"UPDATE cases SET {sets}, updated_at = now() WHERE id = %s RETURNING {self._COLS}",
                (*fields.values(), case_id)).fetchone()
        except psycopg.errors.UniqueViolation as e:
            raise DuplicateReference(body.reference or "") from e
        return self._case(row) if row else None

    def touch(self, case_id: uuid.UUID) -> None:
        """Note activity in the case (an upload, a question): the list is ordered by it."""
        self._execute("UPDATE cases SET updated_at = now() WHERE id = %s", (case_id,))

    def delete(self, case_id: uuid.UUID) -> bool:
        """Delete the case and its members. Its documents and conversations are the other stores'
        to delete (the gateway does, by ``case_id``), before this."""
        return self._execute("DELETE FROM cases WHERE id = %s", (case_id,)).rowcount > 0

    def manages(self, user: str) -> int:
        """How many cases this user manages (an account can't go while it manages one, decision 6)."""
        return self._execute("SELECT count(*) FROM cases WHERE manager = %s", (user,)).fetchone()[0]
