"""Playbook runs (suveryn-tracker#51): the record of a playbook at work in a case. Design:
docs/design/playbooks.md; the playbooks' content and identity: ``suveryn_playbooks``; the routine
that walks a run's steps: ``playbook_runtime``.

A run is the playbook's state, keyed by its case (cases.md, decision 9: the case stays open or
closed; the playbook's progress is in its run). The runtime moves it from step to step: a
``request`` waits for documents, a ``read`` asks the model once over the case's uploaded documents
(``suveryn_harness.facts``, as before), an ``ask`` waits for a person's answers about what the
documents didn't contain, a ``checkpoint`` waits for a person to confirm every fact, a ``produce``
writes the summary into the case as a document with origin ``playbook`` (never a source for
answers: cases.md, decision 7). This module stores runs, their facts and their thread; it decides
nothing about rights (the gateway checks ``cases.may`` first) and nothing about order (the runtime).

**Facts have a record of their own** (``case_facts``): one row per version, never rewritten. The
model's reading is ``proposed`` (or ``not_established`` when the documents don't contain it); a
person's answer to an ``ask`` is ``proposed`` from a person; the checkpoint writes ``confirmed``
(or ``not_established`` when the person clears it). A version that replaces another points at it
(``replaces``) and the older one becomes ``superseded``. The model never writes ``confirmed``.
``Run.facts`` keeps the shape the UI has always had (``RunFact``: as read, confirmed, citations),
assembled from the current versions; runs made before this table keep their facts in
``playbook_runs.facts`` and are read from there.

**The thread** is in ``turns`` (``conversations.TurnStore``): the playbook's questions and the
people's answers, one row each, appended, stamped with who and when.

Identity and provenance: every run records ``playbook_id`` and ``playbook_version``; so does the
result document's name. ``suveryn_playbooks.covered`` is reported with the playbooks; an uncovered
playbook runs with a warning, never a block (the licensing model, development context §8).

Review notes:
- The model's answer, the passages, the people's answers: document text, never logged. Errors are
  stored by kind.
- Only ``uploaded`` documents in the run's case are read (the retriever checks the scope again).
- Everything a run holds (its facts, its turns) goes with the case (``delete_case``).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from suveryn_harness.facts import MAX_VALUE, FactCitation, RunFact
from suveryn_playbooks import Playbook

from .conversations import TURNS_SCHEMA, Turn, TurnStore

log = logging.getLogger("suveryn.gateway")

SCHEMA = TURNS_SCHEMA + """
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
-- The routine (docs/design/playbooks.md, "The routine"): where the run is, each step's state, and
-- the pauses and endings. Runs made before these columns read as they were (``_legacy``).
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS step text;
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS steps jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'en';
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS paused_by text;
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS paused_at timestamptz;
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS ended_by text;
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS ended_reason text;
ALTER TABLE playbook_runs ADD COLUMN IF NOT EXISTS starter text;  -- the starter's id: who may stop or cancel (started_by is the shown name)
CREATE TABLE IF NOT EXISTS playbook_settings (
    playbook_id text PRIMARY KEY,
    active boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS case_facts (
    id uuid PRIMARY KEY,
    case_id uuid NOT NULL,
    run_id uuid NOT NULL,
    step_id text NOT NULL,
    fact_id text NOT NULL,
    kind text NOT NULL,
    value text NOT NULL DEFAULT '',
    status text NOT NULL CHECK (status IN ('proposed', 'confirmed', 'not_established', 'superseded')),
    source jsonb NOT NULL,
    issues jsonb NOT NULL DEFAULT '[]'::jsonb,
    "by" text NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    replaces uuid,
    seq bigserial                    -- insertion order: ``at`` is one instant for every row of a transaction
);
CREATE INDEX IF NOT EXISTS case_facts_case_fact ON case_facts (case_id, fact_id, seq DESC);
CREATE INDEX IF NOT EXISTS case_facts_run ON case_facts (run_id, seq);
"""

# reading: a model call in flight. waiting: for a person (a request, an ask, the checkpoint).
# paused, done, stopped, cancelled, failed as docs/design/playbooks.md defines them.
Status = Literal["reading", "waiting", "paused", "done", "stopped", "cancelled", "failed"]
ACTIVE: tuple[str, ...] = ("reading", "waiting", "paused")
StepStatus = Literal["pending", "active", "done", "skipped"]
FactStatus = Literal["proposed", "confirmed", "not_established", "superseded"]
MAX_RUNS_LISTED = 100
MAX_ANSWER = 4000

# Runs made before the routine stored these statuses; they read as the nearest new one.
_LEGACY_STATUS = {"checkpoint": "waiting", "confirmed": "done"}


class StepState(BaseModel):
    status: StepStatus = "pending"
    by: str | None = None
    at: datetime | None = None


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
    step: str | None = None              # the step the run is on (None: not started, or a run from before the routine)
    language: str = "en"                 # the thread's language: the starter's interface language at the start
    paused_by: str | None = None
    paused_at: datetime | None = None
    ended_by: str | None = None          # who stopped or cancelled it
    ended_reason: str | None = None      # the reason given for a cancel
    starter: str | None = None           # the starter's Keycloak id (rights); None for a run from before the routine


class Run(RunSummary):
    facts: list[RunFact] = Field(default_factory=list)
    instruction_like_sources: list[int] = Field(default_factory=list)
    steps: dict[str, StepState] = Field(default_factory=dict)
    turns: list[Turn] = Field(default_factory=list)


class StartIn(BaseModel):
    """Body of ``POST /v1/cases/{id}/playbooks/{playbook}/runs``: which documents to read (none: all
    the case's uploaded documents, at the time the read step runs) and the thread's language."""

    document_ids: list[str] = Field(default_factory=list, max_length=50)
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")


class AnswerIn(BaseModel):
    """Body of ``POST …/runs/{run}/answer``: a person's answer to the step the run is waiting on.
    For an ``ask``: ``facts`` (a value per fact asked; empty: not known yet). For a ``request``:
    nothing (the documents are in the case; the runtime counts them) or ``none: true`` (there is no
    such document, when the step allows it). ``text`` is what is written in the thread."""

    step_id: str = Field(min_length=1, max_length=50)
    text: str = Field(default="", max_length=MAX_ANSWER)
    facts: dict[str, str] | None = None
    none: bool = False


class ConfirmedFact(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    confirmed: str = Field(max_length=MAX_VALUE)


class ConfirmIn(BaseModel):
    """Body of ``PUT …/runs/{run}/facts``: every fact's confirmed value (a correction, the value as
    read, or empty). ``language`` is accepted from earlier UIs and ignored: the summary is written in
    the run's language, the thread's."""

    facts: list[ConfirmedFact] = Field(min_length=1, max_length=100)
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class PlaybookWords(BaseModel):
    """A playbook's words in one language (``suveryn_playbooks.Wording``)."""

    title: str
    summary: str
    labels: dict[str, str]
    questions: dict[str, str] = Field(default_factory=dict)


class StepOut(BaseModel):
    id: str
    kind: str
    needs: list[str]
    facts: list[str] = Field(default_factory=list)


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
    active: bool = True   # an administrator switched it off: it leaves the composer's menu (docs/design/admin.md)
    steps: list[StepOut] = Field(default_factory=list)  # the routine, so the UI can name the step a run is on


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

class RunStore(TurnStore):
    """Playbook runs, their facts and their thread in PostgreSQL; creates its tables on connect. The
    store decides nothing about rights: the gateway checks ``cases.may`` before anything is read or
    changed. ``TurnStore`` gives it the thread on the same connection."""

    schema = SCHEMA
    COLUMNS = ("id, case_id, playbook_id, playbook_version, status, documents, started_by, started_at, finished_at,"
               " confirmed_by, confirmed_at, model, error, result_document_id, out_of_date,"
               " step, language, paused_by, paused_at, ended_by, ended_reason, starter")
    _N = 22  # columns above; ``facts``, ``instruction_like_sources`` and ``steps`` follow in ``get``

    # -- runs

    def create(self, case_id: uuid.UUID, playbook: Playbook, documents: list[str], started_by: str, model: str | None,
               language: str = "en", starter: str | None = None) -> Run:
        """A new run at its first step (the runtime sets the step and status straight after).
        ``started_by`` is the name shown; ``starter`` the id rights are checked against."""
        run_id = uuid.uuid4()
        steps = {s.id: StepState().model_dump(mode="json") for s in playbook.steps}
        self._execute("INSERT INTO playbook_runs (id, case_id, playbook_id, playbook_version, status, documents, started_by, model,"
                      " steps, language, starter) VALUES (%s, %s, %s, %s, 'waiting', %s, %s, %s, %s, %s, %s)",
                      (run_id, case_id, playbook.id, playbook.version, [uuid.UUID(d) for d in documents], started_by, model,
                       json.dumps(steps), language, starter))
        return self.get(run_id, case_id)  # type: ignore[return-value]

    def active(self, case_id: uuid.UUID, playbook_id: str) -> RunSummary | None:
        """The one run of this playbook in this case that is still going (reading, waiting or paused), if any."""
        r = self._execute(f"SELECT {self.COLUMNS} FROM playbook_runs WHERE case_id = %s AND playbook_id = %s"
                          " AND status IN ('reading', 'waiting', 'paused', 'checkpoint') ORDER BY started_at DESC LIMIT 1",
                          (case_id, playbook_id)).fetchone()
        return self._summary(r) if r else None

    def active_in_cases(self, case_ids: list[uuid.UUID]) -> dict[str, RunSummary]:
        """The live run per case (any playbook; the newest), for the case list's chip."""
        if not case_ids:
            return {}
        rows = self._execute(f"SELECT DISTINCT ON (case_id) {self.COLUMNS} FROM playbook_runs WHERE case_id = ANY(%s)"
                             " AND status IN ('reading', 'waiting', 'paused', 'checkpoint') ORDER BY case_id, started_at DESC",
                             (case_ids,)).fetchall()
        return {str(r[1]): self._summary(r) for r in rows}

    def get(self, run_id: uuid.UUID, case_id: uuid.UUID) -> Run | None:
        r = self._execute(f"SELECT {self.COLUMNS}, facts, instruction_like_sources, steps FROM playbook_runs WHERE id = %s AND case_id = %s",
                          (run_id, case_id)).fetchone()
        if r is None:
            return None
        summary = self._summary(r)
        legacy_facts, suspicious, steps = r[self._N], r[self._N + 1], r[self._N + 2]
        facts = self.facts_for_run(run_id) if steps else [RunFact(**f) for f in legacy_facts]  # a run from before the routine
        return Run(**summary.model_dump(), facts=facts, instruction_like_sources=suspicious,
                   steps={k: StepState(**v) for k, v in steps.items()}, turns=self.for_run(run_id))

    def list(self, case_id: uuid.UUID) -> list[RunSummary]:
        rows = self._execute(f"SELECT {self.COLUMNS} FROM playbook_runs WHERE case_id = %s ORDER BY started_at DESC LIMIT %s",
                             (case_id, MAX_RUNS_LISTED)).fetchall()
        return [self._summary(r) for r in rows]

    @staticmethod
    def _summary(r) -> RunSummary:
        status, step = r[4], r[15]
        if status in _LEGACY_STATUS:  # a run from before the routine: it was at, or past, its checkpoint
            status, step = _LEGACY_STATUS[status], step or "confirm"
        return RunSummary(id=str(r[0]), case_id=str(r[1]), playbook_id=r[2], playbook_version=r[3], status=status,
                          documents=[str(d) for d in r[5]], started_by=r[6], started_at=r[7], finished_at=r[8],
                          confirmed_by=r[9], confirmed_at=r[10], model=r[11], error=r[12],
                          result_document_id=str(r[13]) if r[13] else None, out_of_date=r[14],
                          step=step, language=r[16], paused_by=r[17], paused_at=r[18], ended_by=r[19], ended_reason=r[20], starter=r[21])

    def set_step(self, run_id: uuid.UUID, step: str | None, status: Status, steps: dict[str, StepState],
                 model: str | None = None, suspicious: list[int] | None = None) -> bool:
        """Where the run is now and the state of every step; the model and the suspicious sources when
        a read ended. False when the run is no longer going (stopped or cancelled while a read was in
        flight): nothing is written then."""
        self._execute("UPDATE playbook_runs SET step = %s, status = %s, steps = %s, model = coalesce(%s, model),"
                      " instruction_like_sources = coalesce(%s, instruction_like_sources),"
                      " finished_at = CASE WHEN %s IN ('done', 'stopped', 'cancelled', 'failed') THEN now() ELSE finished_at END"
                      " WHERE id = %s AND status IN ('reading', 'waiting', 'paused')",  # never reopens a run that ended meanwhile
                      (step, status, json.dumps({k: v.model_dump(mode="json") for k, v in steps.items()}), model,
                       json.dumps(suspicious) if suspicious is not None else None, status, run_id))
        return self._execute("SELECT 1 FROM playbook_runs WHERE id = %s AND status = %s", (run_id, status)).fetchone() is not None

    def set_documents(self, run_id: uuid.UUID, documents: list[str]) -> None:
        """Which documents the read step read (chosen at the start, or every upload when it runs)."""
        self._execute("UPDATE playbook_runs SET documents = %s WHERE id = %s", ([uuid.UUID(d) for d in documents], run_id))

    def fail(self, run_id: uuid.UUID, error: str) -> None:
        """The run couldn't go on; ``error`` is a kind, never text."""
        self._execute("UPDATE playbook_runs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s AND status = 'reading'",
                      (error, run_id))

    def interrupt(self, older_than_s: int = 0) -> int:
        """Runs still ``reading`` whose model call can no longer be running: ``failed``, error
        ``interrupted``; how many. The call lives in the gateway's process (one per appliance), so at
        start-up every reading run is dead (``older_than_s`` 0), and the hourly sweep gives up on one
        that has been reading for longer than any model call takes."""
        return self._execute("UPDATE playbook_runs SET status = 'failed', error = 'interrupted', finished_at = now()"
                             " WHERE status = 'reading' AND coalesce((steps -> step ->> 'at')::timestamptz, started_at)"
                             " <= now() - make_interval(secs => %s)", (older_than_s,)).rowcount

    def pause(self, run_id: uuid.UUID, by: str) -> bool:
        return self._execute("UPDATE playbook_runs SET status = 'paused', paused_by = %s, paused_at = now()"
                             " WHERE id = %s AND status = 'waiting'", (by, run_id)).rowcount == 1

    def resume(self, run_id: uuid.UUID) -> bool:
        return self._execute("UPDATE playbook_runs SET status = 'waiting', paused_by = NULL, paused_at = NULL"
                             " WHERE id = %s AND status = 'paused'", (run_id,)).rowcount == 1

    def end(self, run_id: uuid.UUID, status: Literal["stopped", "cancelled"], by: str, reason: str = "") -> bool:
        """Stop or cancel: terminal. The facts' fate is the caller's (``discard_proposed``, ``revert_confirmed``)."""
        return self._execute("UPDATE playbook_runs SET status = %s, ended_by = %s, ended_reason = %s, finished_at = now(),"
                             " paused_by = NULL, paused_at = NULL WHERE id = %s AND status IN ('waiting', 'paused', 'reading')",
                             (status, by, reason or None, run_id)).rowcount == 1

    def set_confirmed(self, run_id: uuid.UUID, by: str) -> None:
        self._execute("UPDATE playbook_runs SET confirmed_by = %s, confirmed_at = now() WHERE id = %s", (by, run_id))

    def set_result(self, run_id: uuid.UUID, document_id: str) -> None:
        self._execute("UPDATE playbook_runs SET result_document_id = %s WHERE id = %s", (uuid.UUID(document_id), run_id))

    def mark_out_of_date(self, case_id: uuid.UUID, document_id: str) -> int:
        """A document a run read was deleted (cases.md): the run stays, marked; how many."""
        return self._execute("UPDATE playbook_runs SET out_of_date = true WHERE case_id = %s AND %s = ANY(documents) AND NOT out_of_date",
                             (case_id, uuid.UUID(document_id))).rowcount

    def delete_case(self, case_id: uuid.UUID) -> int:
        """Everything the case's runs hold goes with them: turns, facts, runs."""
        with self.transaction():
            run_ids = [r[0] for r in self._execute("SELECT id FROM playbook_runs WHERE case_id = %s", (case_id,)).fetchall()]
            self.delete_for_runs(run_ids)
            self._execute("DELETE FROM case_facts WHERE case_id = %s", (case_id,))
            return self._execute("DELETE FROM playbook_runs WHERE case_id = %s", (case_id,)).rowcount

    def inactive(self) -> set[str]:
        """The playbook ids an administrator switched off (``playbook_settings``); every other is active."""
        return {r[0] for r in self._execute("SELECT playbook_id FROM playbook_settings WHERE NOT active").fetchall()}

    def set_active(self, playbook_id: str, active: bool, by: str) -> None:
        self._execute("INSERT INTO playbook_settings (playbook_id, active, updated_at, updated_by) VALUES (%s, %s, now(), %s)"
                      " ON CONFLICT (playbook_id) DO UPDATE SET active = EXCLUDED.active, updated_at = now(), updated_by = EXCLUDED.updated_by",
                      (playbook_id, active, by))

    # -- facts (case_facts): one row per version

    def write_facts(self, case_id: uuid.UUID, run_id: uuid.UUID, step_id: str, rows: list[dict]) -> None:
        """Append versions. Each row: fact_id, kind, value, status, source (dict), issues, by, replaces (id or None).
        A replaced version becomes ``superseded``."""
        with self.transaction():
            for row in rows:
                if row.get("replaces"):
                    self._execute("UPDATE case_facts SET status = 'superseded' WHERE id = %s AND status <> 'superseded'", (row["replaces"],))
                self._execute("INSERT INTO case_facts (id, case_id, run_id, step_id, fact_id, kind, value, status, source, issues, \"by\", replaces)"
                              " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                              (uuid.uuid4(), case_id, run_id, step_id, row["fact_id"], row["kind"], row.get("value", "")[:MAX_VALUE],
                               row["status"], json.dumps(row["source"]), json.dumps(row.get("issues", [])), row["by"], row.get("replaces")))

    def fact_rows(self, run_id: uuid.UUID) -> list[dict]:
        """Every version a run wrote, oldest first."""
        rows = self._execute("SELECT id, step_id, fact_id, kind, value, status, source, issues, \"by\", at, replaces FROM case_facts"
                             " WHERE run_id = %s ORDER BY seq", (run_id,)).fetchall()
        return [dict(id=r[0], step_id=r[1], fact_id=r[2], kind=r[3], value=r[4], status=r[5], source=r[6], issues=r[7], by=r[8], at=r[9],
                     replaces=r[10]) for r in rows]

    def current_versions(self, run_id: uuid.UUID) -> dict[str, dict]:
        """Per fact, the newest version that isn't superseded."""
        out: dict[str, dict] = {}
        for row in self.fact_rows(run_id):
            if row["status"] != "superseded":
                out[row["fact_id"]] = row
        return out

    def facts_for_run(self, run_id: uuid.UUID, checkpoint_steps: set[str] | None = None) -> list[RunFact]:
        """``Run.facts`` as the UI knows them, from the versions: the value as read (the model's, or a
        person's answer to an ask), its citations and issues, whether the documents contained it, and
        what a checkpoint confirmed. Order: as first written (the playbook's)."""
        rows = self.fact_rows(run_id)
        by_fact: dict[str, dict[str, dict]] = {}
        order: list[str] = []
        for row in rows:
            slot = by_fact.setdefault(row["fact_id"], {})
            if row["fact_id"] not in order:
                order.append(row["fact_id"])
            kind, at_checkpoint = row["source"].get("kind"), bool(row["source"].get("checkpoint"))
            if kind in ("document", "none") and not at_checkpoint and "read" not in slot:
                slot["read"] = row                       # the model's reading: the first version
            elif kind == "person" and not at_checkpoint:
                slot["answer"] = row                     # a person's answer to an ask: the newest
            if at_checkpoint and row["status"] in ("confirmed", "not_established"):
                slot["confirmed"] = row                  # what the checkpoint settled; a cancel supersedes it
        out: list[RunFact] = []
        for fact_id in order:
            slot = by_fact[fact_id]
            read, answer, confirmed = slot.get("read"), slot.get("answer"), slot.get("confirmed")
            found = bool(read and read["status"] != "not_established" and read["source"].get("kind") == "document")
            value = answer["value"] if answer else (read["value"] if read else "")
            citations = [FactCitation(**c) for c in (read or {}).get("source", {}).get("citations", [])] if found else []
            out.append(RunFact(id=fact_id, value=value, citations=citations, issues=list((read or {}).get("issues", [])) if found else [],
                               found=found, confirmed=confirmed["value"] if confirmed else None,
                               source="person" if answer else ("document" if found else "none")))
        return out

    def discard_proposed(self, run_id: uuid.UUID) -> int:
        """A stopped run: what a person confirmed stays the case's; what was only proposed goes."""
        return self._execute("UPDATE case_facts SET status = 'superseded' WHERE run_id = %s AND status = 'proposed'", (run_id,)).rowcount

    def revert_confirmed(self, run_id: uuid.UUID, by: str) -> int:
        """A cancelled run: its confirmed facts are no longer the case's. Each gets a new version,
        ``proposed`` again, same source, pointing at the confirmed one (provenance is kept)."""
        rows = [r for r in self.fact_rows(run_id) if r["status"] == "confirmed"]
        self.write_facts(uuid.UUID(str(self._case_of(run_id))), run_id, "cancel", [
            dict(fact_id=r["fact_id"], kind=r["kind"], value=r["value"], status="proposed",
                 source={**r["source"], "reverted": True}, issues=r["issues"], by=by, replaces=r["id"]) for r in rows])
        return len(rows)

    def _case_of(self, run_id: uuid.UUID):
        return self._execute("SELECT case_id FROM playbook_runs WHERE id = %s", (run_id,)).fetchone()[0]
