"""Playbook runs (suveryn-tracker#51): the first playbook, deed intake, hand-built. Design:
docs/design/playbooks.md; the playbooks' content and identity: ``suveryn_playbooks``.

A run is the playbook's state, keyed by its case (cases.md, decision 9: the case stays open or
closed; the playbook's progress is in its run). It reads the case's uploaded documents with one
grounded model call, like a chat question with the playbook's own instructions and no history;
the answer is a Markdown table, one row per fact, each cell citing the excerpts it comes from as
[n]. Reading that table, with its cited passages and the check of every cited figure, date and
name, is the harness's (``suveryn_harness.facts``, docs/harness.md); this module stores runs.
Then the checkpoint: a person
confirms or corrects every fact (``confirm``), and the summary is stored in the case as a document
with origin ``playbook`` (never a source for answers: cases.md, decision 7).

Identity and provenance: every run records ``playbook_id`` and ``playbook_version``; so does the
result document's name. ``suveryn_playbooks.covered`` is reported with the playbooks; an uncovered
playbook runs with a warning, never a block (the licensing model, development context §8).

Review notes:
- The model's answer and the passages are document text: never logged. Errors are stored by kind.
- Only ``uploaded`` documents in the run's case are read (the retriever checks the scope again).
- A run's facts are JSON in PostgreSQL; deleting the case deletes its runs (``delete_case``).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from suveryn_harness.facts import MAX_VALUE, RunFact
from suveryn_playbooks import Playbook

from .db import PgStore

log = logging.getLogger("suveryn.gateway")

SCHEMA = """
CREATE TABLE IF NOT EXISTS playbook_runs (
    id uuid PRIMARY KEY,
    case_id uuid NOT NULL,
    playbook_id text NOT NULL,
    playbook_version text NOT NULL,
    status text NOT NULL,
    documents uuid[] NOT NULL DEFAULT '{}',
    started_by text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    confirmed_by text,
    confirmed_at timestamptz,
    facts jsonb NOT NULL DEFAULT '[]',
    model text,
    error text,
    result_document_id uuid,
    out_of_date boolean NOT NULL DEFAULT false,
    instruction_like_sources jsonb NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS playbook_runs_case ON playbook_runs (case_id, started_at DESC);
CREATE TABLE IF NOT EXISTS playbook_settings (
    playbook_id text PRIMARY KEY,
    active boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL DEFAULT ''
);
"""

Status = Literal["reading", "checkpoint", "confirmed", "failed"]
MAX_RUNS_LISTED = 100


class RunSummary(BaseModel):
    id: str
    case_id: str
    playbook_id: str
    playbook_version: str
    status: Status
    documents: list[str]
    started_by: str                      # the username, as the UI shows it (the access log holds the id)
    started_at: datetime
    finished_at: datetime | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    model: str | None = None
    error: str | None = None
    result_document_id: str | None = None
    out_of_date: bool = False


class Run(RunSummary):
    facts: list[RunFact] = Field(default_factory=list)
    instruction_like_sources: list[int] = Field(default_factory=list)


class StartIn(BaseModel):
    """Body of ``POST /v1/cases/{id}/playbooks/{playbook}/runs``: which documents to read; none: all
    the case's uploaded documents."""

    document_ids: list[str] = Field(default_factory=list, max_length=50)


class ConfirmedFact(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    confirmed: str = Field(max_length=MAX_VALUE)


class ConfirmIn(BaseModel):
    """Body of ``PUT …/runs/{run}/facts``: every fact's confirmed value (a correction, the value as
    read, or empty), and the language of the summary document."""

    facts: list[ConfirmedFact] = Field(min_length=1, max_length=100)
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")  # one of LANGUAGES; another falls back to English


class PlaybookWords(BaseModel):
    """A playbook's words in one language (``suveryn_playbooks.Wording``)."""

    title: str
    summary: str
    labels: dict[str, str]


class PlaybookOut(BaseModel):
    """One playbook that fits a case (``GET /v1/cases/{id}/playbooks``), or one of all of them for the
    administrator (``GET /v1/admin/playbooks``, with ``active``)."""

    id: str
    slug: str
    pack: str
    version: str
    name: str
    covered: bool   # certified and in the appliance's manifest; false: runs with a warning, never blocked (§8)
    facts: list[str]
    case_types: list[str] = Field(default_factory=list)
    text: dict[str, PlaybookWords] = Field(default_factory=dict)  # per language: what the UI shows (docs/translations.md)
    active: bool = True   # an administrator switched it off: it leaves the composer's menu (docs/design/sidebar.md, 15)


class ActiveIn(BaseModel):
    """Body of ``PUT /v1/admin/playbooks/{slug}``."""

    active: bool


def summary_text(playbook: Playbook, reference: str, run: Run, language: str) -> str:
    """The confirmed facts as the result document's text: a heading, one paragraph per fact, the
    sources. Stored in the case with origin ``playbook`` and offered as a Word download by the UI.

    Provenance: the id and version written are the **run's** (what read the documents), never the
    playbook as installed now: a run started under 1.0 and confirmed after an upgrade says 1.0
    (review 2026-10-17). ``playbook`` only supplies the labels."""
    words = playbook.wording(language)
    labels = words.labels
    lines = [f"{words.title} {reference}", f"{run.playbook_id} {run.playbook_version}"]
    for f in run.facts:
        value = f.confirmed if f.confirmed is not None else f.value
        sources = ", ".join(f"{c.filename}{f' p. {c.page}' if c.page else ''}" for c in f.citations)
        lines.append(f"{labels.get(f.id, f.id)}: {value or '—'}" + (f" ({sources})" if sources and value else ""))
    return "\n\n".join(lines)


# ------------------------------------------------------------------------- the store

class RunStore(PgStore):
    """Playbook runs in PostgreSQL; creates its table on connect. The store decides nothing about
    rights: the gateway checks ``cases.may`` before anything is read or changed."""

    schema = SCHEMA
    COLUMNS = ("id, case_id, playbook_id, playbook_version, status, documents, started_by, started_at, finished_at,"
               " confirmed_by, confirmed_at, model, error, result_document_id, out_of_date")

    def create(self, case_id: uuid.UUID, playbook: Playbook, documents: list[str], started_by: str, model: str | None) -> Run:
        run_id = uuid.uuid4()
        self._execute("INSERT INTO playbook_runs (id, case_id, playbook_id, playbook_version, status, documents, started_by, model)"
                      " VALUES (%s, %s, %s, %s, 'reading', %s, %s, %s)",
                      (run_id, case_id, playbook.id, playbook.version, [uuid.UUID(d) for d in documents], started_by, model))
        return self.get(run_id, case_id)  # type: ignore[return-value]

    def get(self, run_id: uuid.UUID, case_id: uuid.UUID) -> Run | None:
        r = self._execute(f"SELECT {self.COLUMNS}, facts, instruction_like_sources FROM playbook_runs WHERE id = %s AND case_id = %s",
                          (run_id, case_id)).fetchone()
        if r is None:
            return None
        return Run(**self._summary(r).model_dump(), facts=[RunFact(**f) for f in r[15]], instruction_like_sources=r[16])

    def list(self, case_id: uuid.UUID) -> list[RunSummary]:
        rows = self._execute(f"SELECT {self.COLUMNS} FROM playbook_runs WHERE case_id = %s ORDER BY started_at DESC LIMIT %s",
                             (case_id, MAX_RUNS_LISTED)).fetchall()
        return [self._summary(r) for r in rows]

    @staticmethod
    def _summary(r) -> RunSummary:
        return RunSummary(id=str(r[0]), case_id=str(r[1]), playbook_id=r[2], playbook_version=r[3], status=r[4],
                          documents=[str(d) for d in r[5]], started_by=r[6], started_at=r[7], finished_at=r[8],
                          confirmed_by=r[9], confirmed_at=r[10], model=r[11], error=r[12],
                          result_document_id=str(r[13]) if r[13] else None, out_of_date=r[14])

    def read(self, run_id: uuid.UUID, facts: list[RunFact], model: str | None, suspicious: list[int]) -> None:
        """The model has answered: the facts, waiting for a person (status ``checkpoint``)."""
        self._execute("UPDATE playbook_runs SET status = 'checkpoint', facts = %s, model = coalesce(%s, model),"
                      " instruction_like_sources = %s, finished_at = now() WHERE id = %s AND status = 'reading'",
                      (json.dumps([f.model_dump() for f in facts]), model, json.dumps(suspicious), run_id))

    def fail(self, run_id: uuid.UUID, error: str) -> None:
        """The run couldn't be read; ``error`` is a kind, never text."""
        self._execute("UPDATE playbook_runs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s AND status = 'reading'",
                      (error, run_id))

    def interrupt(self, older_than_s: int = 0) -> int:
        """Runs still ``reading`` whose model call can no longer be running: ``failed``, error
        ``interrupted``; how many. The call lives in the gateway's process (one per appliance), so at
        start-up every reading run is dead (``older_than_s`` 0), and the hourly sweep gives up on one
        that has been reading for longer than any model call takes (review 2026-10-17: a restart
        used to leave a run spinning forever)."""
        return self._execute("UPDATE playbook_runs SET status = 'failed', error = 'interrupted', finished_at = now()"
                             " WHERE status = 'reading' AND started_at <= now() - make_interval(secs => %s)",
                             (older_than_s,)).rowcount

    def confirm(self, run_id: uuid.UUID, case_id: uuid.UUID, confirmed: dict[str, str], by: str) -> Run | None:
        """The checkpoint passed: every fact's confirmed value; None if the run isn't at the checkpoint."""
        with self.transaction():
            r = self._execute("SELECT facts FROM playbook_runs WHERE id = %s AND case_id = %s AND status = 'checkpoint' FOR UPDATE",
                              (run_id, case_id)).fetchone()
            if r is None:
                return None
            facts = [RunFact(**f) for f in r[0]]
            for f in facts:
                f.confirmed = confirmed.get(f.id, f.value)[:MAX_VALUE]
            self._execute("UPDATE playbook_runs SET status = 'confirmed', facts = %s, confirmed_by = %s, confirmed_at = now() WHERE id = %s",
                          (json.dumps([f.model_dump() for f in facts]), by, run_id))
        return self.get(run_id, case_id)

    def set_result(self, run_id: uuid.UUID, document_id: str) -> None:
        self._execute("UPDATE playbook_runs SET result_document_id = %s WHERE id = %s", (uuid.UUID(document_id), run_id))

    def mark_out_of_date(self, case_id: uuid.UUID, document_id: str) -> int:
        """A document a run read was deleted (cases.md): the run stays, marked; how many."""
        return self._execute("UPDATE playbook_runs SET out_of_date = true WHERE case_id = %s AND %s = ANY(documents) AND NOT out_of_date",
                             (case_id, uuid.UUID(document_id))).rowcount

    def delete_case(self, case_id: uuid.UUID) -> int:
        return self._execute("DELETE FROM playbook_runs WHERE case_id = %s", (case_id,)).rowcount

    def inactive(self) -> set[str]:
        """The playbook ids an administrator switched off (``playbook_settings``); every other is active."""
        return {r[0] for r in self._execute("SELECT playbook_id FROM playbook_settings WHERE NOT active").fetchall()}

    def set_active(self, playbook_id: str, active: bool, by: str) -> None:
        self._execute("INSERT INTO playbook_settings (playbook_id, active, updated_at, updated_by) VALUES (%s, %s, now(), %s)"
                      " ON CONFLICT (playbook_id) DO UPDATE SET active = EXCLUDED.active, updated_at = now(), updated_by = EXCLUDED.updated_by",
                      (playbook_id, active, by))
