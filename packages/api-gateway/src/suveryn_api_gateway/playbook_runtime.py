"""The playbook runtime: walks a run through its routine (docs/design/playbooks.md, "The routine").

The playbook's steps are a graph (``suveryn_playbooks.Step``: ``needs``). ``next_step`` is a pure
function: given the playbook and the state of every step, the first step, in the manifest's order,
that isn't done and whose needs all are. The runtime does that step's work and moves on until it
reaches one that waits — for the model (``read``) or for a person (``request``, ``ask``,
``checkpoint``) — or until nothing is left and the run is done. The model is asked only inside a
``read``, and never decides what comes next; a person's answer never becomes a confirmed fact
except at a checkpoint, by that person.

``advance`` is synchronous and takes its stores as arguments (the routes run it in the thread
pool), so the order of steps is tested without a request. The one thing it can't do itself is the
model call: when it reaches a ``read`` it marks the run ``reading`` and returns that step; the route
starts the call (``routes.playbooks._read``) and, when the answer is in, calls ``finish_read`` and
``advance`` again.

The thread (the run's conversation, its rows in ``turns``): the runtime writes the playbook's turns,
in the run's language, from the pack's wording; people's turns are written by the routes when they answer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from suveryn_harness.facts import RunFact
from suveryn_playbooks import Playbook, Step, entry, root
from suveryn_rag.store import Scope

from .playbooks import Run, RunStore, StepState, summary_text

log = logging.getLogger("suveryn.gateway")


def next_step(playbook: Playbook, states: dict[str, StepState]) -> Step | None:
    """The first step (manifest order) that is still to do and whose needs are all done or skipped."""
    for step in playbook.steps:
        state = states.get(step.id, StepState())
        if state.status in ("done", "skipped"):
            continue
        if all(states.get(n, StepState()).status in ("done", "skipped") for n in step.needs):
            return step
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Runtime:
    """One run's routine, over the stores it needs. ``documents`` is the document store (uploaded
    documents in the case, the summary written back); ``filenames_of`` is the gateway's list of a
    case's uploaded documents (id -> file name), checked each time a ``request`` or ``read`` looks."""

    def __init__(self, store: RunStore, documents, uploaded: callable):
        self.store, self.documents, self.uploaded = store, documents, uploaded

    # -- the walk

    def advance(self, run: Run, playbook: Playbook, reference: str) -> Step | None:
        """Do what can be done without anyone, until the run waits or ends. Returns the ``read``
        step when the model must be asked (the run is then ``reading``); else None."""
        states = dict(run.steps)
        rid = uuid.UUID(run.id)
        while True:
            step = next_step(playbook, states)
            if step is None:
                self.store.set_step(rid, None, "done", states)
                return None
            if step.kind == "request":
                if self._request_satisfied(run, step, states):
                    states[step.id] = StepState(status="done", at=_now())
                    continue
                if states.get(step.id, StepState()).status != "active":
                    states[step.id] = StepState(status="active", at=_now())
                    self.store.set_step(rid, step.id, "waiting", states)
                    self._say(run, playbook, step.id, playbook.wording(run.language).question(step.id))
                return None
            if step.kind == "read":
                states[step.id] = StepState(status="active", at=_now())
                self.store.set_step(rid, step.id, "reading", states)
                return step
            if step.kind == "ask":
                open_facts = self.unanswered(run, step)
                if not open_facts:
                    states[step.id] = StepState(status="skipped", at=_now())
                    continue
                if states.get(step.id, StepState()).status != "active":
                    states[step.id] = StepState(status="active", at=_now())
                    self.store.set_step(rid, step.id, "waiting", states)
                    self._say(run, playbook, step.id, *self.ask_turn(run, playbook, open_facts))
                return None
            if step.kind == "checkpoint":
                if states.get(step.id, StepState()).status != "active":
                    states[step.id] = StepState(status="active", at=_now())
                    self.store.set_step(rid, step.id, "waiting", states)
                    self._say(run, playbook, step.id, *self.checkpoint_turn(run))
                return None
            if step.kind == "produce":
                self._produce(run, playbook, reference, step, states)
                states[step.id] = StepState(status="done", at=_now())
                continue
            raise ValueError(f"unknown step kind {step.kind!r}")

    # -- what each step needs

    def _request_satisfied(self, run: Run, step: Step, states: dict[str, StepState]) -> bool:
        """A request is met once a person has answered it (with documents, or pointing to those already in the
        case) and the case has what it needs. It always asks first: a document left in the case was read as
        the agreement without anyone saying so (VM regression e0f2e26, question 1; decision, 1 November 2026)."""
        state = states.get(step.id, StepState())
        if state.status == "skipped":
            return True
        return state.by is not None and len(self.uploaded(uuid.UUID(run.case_id))) >= step.min

    def unanswered(self, run: Run, step: Step) -> list[str]:
        """The facts an ``ask`` step still has to ask about: not in the documents, and no person has answered."""
        current = self.store.current_versions(uuid.UUID(run.id))
        out = []
        for fact_id in step.facts:
            v = current.get(fact_id)
            if v is None:
                continue  # never read: nothing to ask about (the read step decides what exists)
            if v["status"] == "not_established" and v["source"].get("kind") == "none" and not has_entries(current, fact_id):
                out.append(fact_id)
        return out

    @staticmethod
    def askable(playbook: Playbook, open_facts: list[str], language: str) -> dict[str, str]:
        """What a person's answer in words may be placed on, with its label: each open fact; for a list the
        documents named nothing of, its first entry's values (``founders[1].name``), so an answer that names a
        founder lands as an entry, never as the list's one value."""
        words = playbook.wording(language)
        out: dict[str, str] = {}
        for fid in open_facts:
            f = playbook.fact(fid)
            if f is not None and f.kind == "list":
                for path in entry_paths(playbook, fid, 1):
                    out[path] = words.label(path)
            else:
                out[fid] = words.label(fid)
        return out

    # -- people's answers and the model's

    def documents_to_read(self, run: Run) -> dict[str, str]:
        """What the read step reads: the documents chosen at the start if any, else every uploaded
        document in the case now (id -> file name). Empty: nothing to read."""
        uploaded = self.uploaded(uuid.UUID(run.case_id))
        if run.documents:
            return {d: uploaded[d] for d in run.documents if d in uploaded}
        return dict(uploaded)

    def finish_read(self, run: Run, playbook: Playbook, step: Step, facts: list[RunFact], model: str | None,
                    suspicious: list[int]) -> Run | None:
        """The model answered: its reading becomes the facts' first versions (proposed, or
        not_established), the step is done. None if the run ended meanwhile."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        self.store.write_facts(cid, rid, step.id, [
            dict(fact_id=f.id, kind=playbook.leaf_kind(f.id), value=f.value if f.found else "",
                 status="proposed" if f.found else "not_established",
                 source={"kind": "document", "citations": [c.model_dump() for c in f.citations],
                         **({"needs": f.needs} if f.needs else {})} if f.found else {"kind": "none"},
                 issues=f.issues, by=playbook.id) for f in facts if root(f.id) in step.facts])
        states = dict(run.steps)
        states[step.id] = StepState(status="done", at=_now())
        # still ``reading`` until ``advance`` has found the next wait: a poll between the two must not see a half-moved run
        if not self.store.set_step(rid, step.id, "reading", states, model=model, suspicious=suspicious):
            return None
        return self.store.get(rid, cid)

    def answer_ask(self, run: Run, playbook: Playbook, step: Step, answers: dict[str, str], by: str) -> Run:
        """A person's answers to an ask: each non-empty one is a proposed fact from that person
        (replacing the not-established reading); the step is done either way."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        current = self.store.current_versions(rid)
        rows = [dict(fact_id=fid, kind=playbook.leaf_kind(fid), value=v.strip(), status="proposed", source={"kind": "person"},
                     by=by, replaces=current[fid]["id"] if fid in current else None)
                for fid, v in answers.items() if root(fid) in step.facts and playbook.leaf(fid) is not None and v and v.strip()]
        self.store.write_facts(cid, rid, step.id, rows)
        self._settle_lists(playbook, current, [r["fact_id"] for r in rows])
        states = dict(run.steps)
        states[step.id] = StepState(status="done", by=by, at=_now())
        self.store.set_step(rid, step.id, "waiting", states)
        return self.store.get(rid, cid)  # type: ignore[return-value]

    def answer_request(self, run: Run, step: Step, by: str, none: bool) -> Run:
        """A person says the documents are in (the runtime counts them) or, when allowed, that there is none."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        states = dict(run.steps)
        if none and step.allow_none:
            states[step.id] = StepState(status="skipped", by=by, at=_now())
        else:
            states[step.id] = StepState(status="active", by=by, at=_now())  # answered: met once the documents are there
        self.store.set_step(rid, step.id, "waiting", states)
        return self.store.get(rid, cid)  # type: ignore[return-value]

    def confirm(self, run: Run, playbook: Playbook, step: Step, confirmed: dict[str, str], by: str) -> Run:
        """The checkpoint: a version per fact, confirmed (or not_established when cleared), by this
        person, replacing the current one. Facts not named keep their value as read."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        current = self.store.current_versions(rid)
        rows = []
        known = {f.id for f in run.facts}
        # entries a person added at the checkpoint (``founders[3].name``): facts the read never made, confirmed now
        added = [fid for fid, v in confirmed.items() if fid not in known and playbook.leaf(fid) is not None and fid != root(fid) and v.strip()]
        for f in run.facts:
            if f.id == root(f.id) and (has_entries(current, f.id) or any(root(a) == f.id for a in added)):
                continue  # a list with entries: the entries are confirmed, not the list's "none"
            value = confirmed.get(f.id, f.value).strip()
            rows.append(dict(fact_id=f.id, kind=playbook.leaf_kind(f.id), value=value,
                             status="confirmed" if value else "not_established",
                             source={"kind": "person", "checkpoint": True}, by=by,
                             replaces=current[f.id]["id"] if f.id in current else None))
        for fid in added:
            rows.append(dict(fact_id=fid, kind=playbook.leaf_kind(fid), value=confirmed[fid].strip(), status="confirmed",
                             source={"kind": "person", "checkpoint": True}, by=by, replaces=None))
        self.store.write_facts(cid, rid, step.id, rows)
        self._settle_lists(playbook, current, added)
        self.store.set_confirmed(rid, by)
        states = dict(run.steps)
        states[step.id] = StepState(status="done", by=by, at=_now())
        self.store.set_step(rid, step.id, "waiting", states)
        return self.store.get(rid, cid)  # type: ignore[return-value]

    def correct(self, run: Run, playbook: Playbook, step: Step, corrections: dict[str, str], by: str) -> Run:
        """Corrections in words at the checkpoint: each a proposed version from this person, replacing
        the current one; the run stays at the checkpoint (the person still confirms)."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        current = self.store.current_versions(rid)
        rows = [dict(fact_id=fid, kind=playbook.leaf_kind(fid), value=v.strip(), status="proposed", source={"kind": "person"},
                     by=by, replaces=current[fid]["id"] if fid in current else None)
                for fid, v in corrections.items() if v.strip() and (fid in current or (playbook.leaf(fid) is not None and fid != root(fid)))]
        self.store.write_facts(cid, rid, step.id, rows)
        self._settle_lists(playbook, current, [r["fact_id"] for r in rows if r["fact_id"] not in current])
        return self.store.get(rid, cid)  # type: ignore[return-value]

    def _settle_lists(self, playbook: Playbook, current: dict[str, dict], written: list[str]) -> None:
        """A list the documents named nothing of (its own not-found version) gets entries from a person: that
        "none" is superseded, so the list is no longer open and the summary shows the entries."""
        roots = {root(fid) for fid in written if fid != root(fid)}
        self.store.supersede([current[r]["id"] for r in roots if r in current and current[r]["status"] == "not_established"])

    # -- what the playbook says (the UI words a turn from its ``meta``; ``text`` is the English for a log or an export)

    @staticmethod
    def counts(run: Run) -> tuple[int, int]:
        """How many facts have a value (read from the documents, or given by a person), of how many. A
        list with entries counts by its entries, not by its own "none"."""
        shown = shown_facts(run.facts)
        return sum(1 for f in shown if f.value), len(shown)

    def ask_turn(self, run: Run, playbook: Playbook, open_facts: list[str]) -> tuple[str, dict]:
        fresh = self.store.get(uuid.UUID(run.id), uuid.UUID(run.case_id)) or run
        found, total = self.counts(fresh)
        words = playbook.wording("en")
        missing = ", ".join(words.label(f) for f in open_facts)
        return (f"{found} of {total} facts found. Not in the documents: {missing}. Do you know them?",
                {"kind": "ask", "facts": open_facts, "found": found, "total": total})

    def checkpoint_turn(self, run: Run) -> tuple[str, dict]:
        fresh = self.store.get(uuid.UUID(run.id), uuid.UUID(run.case_id)) or run
        found, total = self.counts(fresh)
        issues = sum(1 for f in fresh.facts if f.issues)
        return (f"{found} of {total} facts found." + (f" {issues} need checking." if issues else ""),
                {"kind": "checkpoint", "found": found, "total": total, "issues": issues})

    # -- products and the thread

    def _produce(self, run: Run, playbook: Playbook, reference: str, step: Step, states: dict[str, StepState]) -> None:
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        fresh = self.store.get(rid, cid)
        if fresh is None:
            return
        # in the run's language, the run's version (never the installed one): "Akte-intake 2026/0417 (1.1)"
        # (VM regression e0f2e26, finding 8: it was the English name with ".txt")
        name = f"{playbook.wording(run.language).title} {reference} ({run.playbook_version})"
        try:
            document_id = self.documents.store_text(name, summary_text(playbook, reference, fresh, run.language), Scope.case(cid), "playbook",
                                                    {"playbook": playbook.id, "version": run.playbook_version, "run": run.id})
            self.store.set_result(rid, document_id)
        except Exception as e:  # noqa: BLE001 - the confirmation stands; the document can be made again
            log.error("playbook result not stored: %s", type(e).__name__)

    def _say(self, run: Run, playbook: Playbook, step_id: str | None, text: str, meta: dict | None = None) -> None:
        if text:
            self.store.say(run, "playbook", playbook.id, text, step_id, meta, once=True)


# ------------------------------------------------------------------ lists (format 3, suveryn_playbooks.paths)

def has_entries(current: dict[str, dict], list_id: str) -> bool:
    """Whether any entry of the list has a current version (``founders[1].name`` for ``founders``)."""
    return any(root(fid) == list_id and fid != list_id for fid in current)


def entry_paths(playbook: Playbook, list_id: str, index: int) -> list[str]:
    """The paths of one entry's values: its fields', or the one value of a list of plain values."""
    f = playbook.fact(list_id)
    if f is None or f.kind != "list":
        return []
    return [entry(list_id, index, x.id) for x in f.fields] if f.fields else [entry(list_id, index)]


def shown_facts(facts: list[RunFact]) -> list[RunFact]:
    """The facts as a person sees them: a list's own "the documents name none" is left out once the list has
    entries (from the read, or added by a person)."""
    with_entries = {root(f.id) for f in facts if f.id != root(f.id)}
    return [f for f in facts if f.id not in with_entries]
