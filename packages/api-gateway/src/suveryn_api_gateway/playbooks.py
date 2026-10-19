"""Playbook runs (suveryn-tracker#51): the first playbook, deed intake, hand-built. Design:
docs/design/playbooks.md; the playbooks' content and identity: ``suveryn_playbooks``.

A run is the playbook's state, keyed by its case (cases.md, decision 9: the case stays open or
closed; the playbook's progress is in its run). It reads the case's uploaded documents with one
grounded model call, like a chat question with the playbook's own instructions and no history;
the answer is a Markdown table, one row per fact, each cell citing the excerpts it comes from as
[n]. The gateway parses it (``read_facts``), keeps the cited passages with the fact (so a run can
be shown after a document is deleted), and checks every cited figure, date and name against its
passage with the chat's rule-based check (``suveryn_chat.support``). Then the checkpoint: a person
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
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from suveryn_chat.grounding import cited_numbers
from suveryn_chat.support import citation_issues
from suveryn_engine import ChatResponse, Citation
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
MAX_VALUE = 2000        # characters of one fact's value, as read or as confirmed
MAX_RUNS_LISTED = 100


class FactCitation(BaseModel):
    """A passage a fact was read from: enough to show it later, also after the document is deleted."""

    n: int
    document_id: str
    filename: str
    page: int | None = None
    location: str | None = None
    text: str


class RunFact(BaseModel):
    id: str
    value: str = ""                      # as the model read it, copied from the documents
    citations: list[FactCitation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)   # figures, dates or names not in the cited passages
    found: bool = True                   # False: the model said the documents don't contain it
    confirmed: str | None = None         # what the person confirmed (a correction, the value, or "")


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


# ------------------------------------------------------------------------- reading the model's table

_ROW = re.compile(r"^\s*\|?\s*([^|]+?)\s*\|(.*?)\|(.*?)\|?\s*$")
_MARKER = re.compile(r"\[(\d{1,2})\]")
_NOT_FOUND = re.compile(r"^\s*(-|—|n/?a|none|niet (gevonden|vermeld)|non (trouvé|mentionné)|not (found|mentioned|stated))\s*\.?\s*$", re.IGNORECASE)


def read_facts(playbook: Playbook, response: ChatResponse, filenames: dict[str, str]) -> list[RunFact] | None:
    """The facts in the model's table, in the playbook's order, with their cited passages and the
    check's findings; None if the answer isn't the table (``error: unreadable_answer``).

    The check reuses the chat's, both halves: ``citation_issues`` (a figure, date or name that is in
    a passage but not the cited one) works on the whole answer and reports by marker occurrence, so
    markers are counted here in the same order to map them to facts; ``unverified_figures`` (a figure
    in no passage at all: made up or worked out) is matched to the fact whose value writes it, a
    substring match that can attach a figure to two facts that both write it (tolerable: both get
    the warning, and a person looks at both).

    The first column names the fact: its id as given, or, since a small model sometimes translates
    or paraphrases, its label in any of the playbook's languages (review 2026-10-17). Rows are never
    taken by position: a skipped row would shift every fact after it onto the wrong label, silently,
    which is worse than a run that fails and is started again."""
    citations = response.citations
    rows: dict[str, tuple[str, list[int]]] = {}
    marker_facts: list[str] = []  # which fact the i-th valid marker (in text order) belongs to
    names = _fact_names(playbook)
    for line in response.answer.splitlines():
        m = _ROW.match(line)
        if not m or m.group(1) in ("id",) or set(m.group(2).strip()) <= {"-", ":"}:
            continue
        fact_id, value, source = names.get(_fold(m.group(1))), m.group(2).strip(), m.group(3)
        if fact_id is None or fact_id in rows:
            continue
        # markers in the value cell count first (text order), then the source cell
        numbers = cited_numbers(value, len(citations)) + cited_numbers(source, len(citations))
        marker_facts += [fact_id] * (len(_valid(value, len(citations))) + len(_valid(source, len(citations))))
        rows[fact_id] = (_MARKER.sub("", value).strip(" *_"), list(dict.fromkeys(numbers)))
    if len(rows) < max(1, len(playbook.facts) // 2):
        return None
    issues_by_fact: dict[str, list[str]] = {}
    for issue in citation_issues(response.answer, citations, response.calculations):
        if issue.marker < len(marker_facts):
            issues_by_fact.setdefault(marker_facts[issue.marker], []).append(issue.item)
    for fact_id, (value, _) in rows.items():
        issues_by_fact.setdefault(fact_id, []).extend(u for u in response.unverified_figures if u in value)
    facts = []
    for f in playbook.facts:
        value, numbers = rows.get(f.id, ("", []))
        found = bool(value) and not _NOT_FOUND.match(value)
        cited = [_cite(n, citations[n - 1], filenames) for n in numbers if 0 < n <= len(citations)]
        # a value is kept to MAX_VALUE characters: a fact is a line, not a page; what is cut is still in the passage
        facts.append(RunFact(id=f.id, value=value[:MAX_VALUE] if found else "", citations=cited if found else [],
                             issues=list(dict.fromkeys(issues_by_fact.get(f.id, []))) if found else [], found=found))
    return facts


def _fold(text: str) -> str:
    """A fact's name as the model may write it: case, accents, surrounding marks and spacing ignored."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[\s_*`'\"()-]+", " ", text).strip()


def _fact_names(playbook: Playbook) -> dict[str, str]:
    """Every way the first column may name a fact (id, label in each language, id with spaces) -> id."""
    names = {}
    for f in playbook.facts:
        names[_fold(f.id)] = f.id
        for words in playbook.text.values():
            if f.id in words.labels:
                names[_fold(words.labels[f.id])] = f.id
    return names


def _valid(text: str, available: int) -> list[int]:
    return [int(n) for n in _MARKER.findall(text) if 0 < int(n) <= available]


def _cite(n: int, c: Citation, filenames: dict[str, str]) -> FactCitation:
    s = c.source
    return FactCitation(n=n, document_id=s.document_id if s else "", filename=filenames.get(s.document_id, "") if s else "",
                        page=s.page if s else None, location=s.location if s else None, text=c.text)


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
