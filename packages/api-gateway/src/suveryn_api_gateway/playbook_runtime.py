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

from suveryn_harness.checks import evaluate
from suveryn_harness.facts import RunFact, option_of
from suveryn_playbooks import Playbook, Step, entry, root
from suveryn_playbooks.conditions import parse_when
from suveryn_playbooks.rules import parse_rule
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
        step when the model must be asked (the run is then ``reading``); else None. A wait is announced
        in the thread before the run is set to ``waiting``: a poll that sees the run waiting sees what
        it waits for (the question, the ask, the checkpoint), never a run waiting on nothing yet."""
        states = dict(run.steps)
        rid = uuid.UUID(run.id)
        while True:
            step = next_step(playbook, states)
            if step is None:
                self.store.set_step(rid, None, "done", states)
                return None
            if step.when:
                because = self.skipped_because(run, playbook, step)
                if because is not None:
                    states[step.id] = StepState(status="skipped", at=_now(), because=because)
                    self._say(run, playbook, step.id, *self.skipped_turn(run, playbook, step, because))
                    continue
            if step.kind == "request":
                if self._request_satisfied(run, step, states):
                    states[step.id] = StepState(status="done", at=_now())
                    continue
                if states.get(step.id, StepState()).status != "active":
                    states[step.id] = StepState(status="active", at=_now())
                    self._say(run, playbook, step.id, playbook.wording(run.language).question(step.id))
                    self.store.set_step(rid, step.id, "waiting", states)
                return None
            if step.kind == "read":
                if step.documents and not self.documents_to_read(run, step):
                    # aimed at requests that were skipped (no such document): nothing to read, its facts are not
                    # established without a model call, and an ask step may still ask about them
                    self.store.write_facts(uuid.UUID(run.case_id), rid, step.id, [
                        dict(fact_id=f, kind=playbook.leaf_kind(f), value="", status="not_established", source={"kind": "none"},
                             by=playbook.id) for f in step.facts])
                    states[step.id] = StepState(status="done", at=_now())
                    continue
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
                    self._say(run, playbook, step.id, *self.ask_turn(run, playbook, open_facts))
                    self.store.set_step(rid, step.id, "waiting", states)
                return None
            if step.kind == "checkpoint":
                if states.get(step.id, StepState()).status != "active":
                    states[step.id] = StepState(status="active", at=_now())
                    self._say(run, playbook, step.id, *self.checkpoint_turn(run))
                    self.store.set_step(rid, step.id, "waiting", states)
                return None
            if step.kind == "check":
                self.recheck(run, playbook)
                states[step.id] = StepState(status="done", at=_now())
                continue
            if step.kind == "produce":
                self.recheck(run, playbook)  # on the values as confirmed
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
        if state.by is None:
            return False
        if step.expects:  # a named request: the documents that answered it, still in the case
            uploaded = self.uploaded(uuid.UUID(run.case_id))
            return sum(1 for d in run.requested.get(step.id, []) if d in uploaded) >= step.min
        return len(self.uploaded(uuid.UUID(run.case_id))) >= step.min

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

    # -- conditions (format 3, "Choices"): a step runs when its choice has the option it names; else it is skipped and says why

    def choice_value(self, run: Run, fact_id: str) -> str:
        """A choice fact's value as it stands (read, answered or confirmed), or empty."""
        v = self.store.current_versions(uuid.UUID(run.id)).get(fact_id)
        return v["value"] if v and v["status"] in ("proposed", "confirmed") else ""

    def skipped_because(self, run: Run, playbook: Playbook, step: Step) -> str | None:
        """Why the step is skipped, or None when it runs: its ``when`` doesn't hold for the choice's value, or
        the choice isn't known (the steps that could settle it are done, so nothing will)."""
        w = parse_when(step.when, playbook)
        value = self.choice_value(run, w.fact)
        holds = w.holds(value)
        if holds:
            return None
        return f"{w}; {value or '?'}"

    def skipped_turn(self, run: Run, playbook: Playbook, step: Step, because: str) -> tuple[str, dict]:
        w = parse_when(step.when, playbook)
        value = because.rsplit("; ", 1)[-1]
        words = playbook.wording("en")
        said = (f"{words.step(step.id)}: not needed, {words.label(w.fact)} is {words.option(w.fact, value)}." if value != "?"
                else f"{words.step(step.id)}: skipped, {words.label(w.fact)} is not known.")
        return said, {"kind": "skipped_step", "step": step.id, "fact": w.fact, "value": "" if value == "?" else value, "when": str(w)}

    def normalise(self, playbook: Playbook, fact_id: str, value: str, language: str) -> str:
        """A person's value for a choice as its option id, from the id or the option's words in the run's
        language or English; anything else is no value. Other kinds pass as written."""
        f = playbook.leaf(fact_id)
        if f is None or f.kind != "choice":
            return value.strip()
        for lang in (language, *playbook.text):  # the run's language first, then every language the pack has
            labels = {o: playbook.wording(lang).option(fact_id, o) for o in f.options}
            found = option_of(value.strip(), f.options, labels)
            if found:
                return found
        return ""

    # -- the checks (format 3, "Checks"): computed by the server on the values as they stand, never a block

    def recheck(self, run: Run, playbook: Playbook) -> dict[str, dict]:
        """Every check step's rule, evaluated on the run's current values (the newest version of each fact
        that has one: read, answered or confirmed); stored on the run and returned. Called when a check
        step is reached and whenever a value changes, so the checkpoint shows the state of things now."""
        rid = uuid.UUID(run.id)
        current = self.store.current_versions(rid)
        values = {fid: v["value"] for fid, v in current.items() if v["status"] in ("proposed", "confirmed")}
        out: dict[str, dict] = {}
        for step in playbook.steps:
            if step.kind != "check":
                continue
            if step.when and parse_when(step.when, playbook).holds(values.get(parse_when(step.when, playbook).fact, "")) is not True:
                continue  # a check whose condition doesn't hold (or isn't known) has no result
            r = evaluate(parse_rule(step.rule, playbook), values)
            out[step.id] = {"status": r.status, "rule": step.rule, "left": r.left, "right": r.right, "missing": list(r.missing)}
        if any(s.kind == "check" for s in playbook.steps):
            self.store.set_checks(rid, out)  # a check whose condition no longer holds loses its result
        return out

    # -- people's answers and the model's

    def documents_to_read(self, run: Run, step: Step | None = None) -> dict[str, str]:
        """What a read step reads (id -> file name): aimed at named requests (``documents``), the documents
        that answered those requests; else the documents chosen at the start if any, else every uploaded
        document in the case now. Empty: nothing to read."""
        uploaded = self.uploaded(uuid.UUID(run.case_id))
        if step is not None and step.documents:
            playbook_requests = {s.expects: s.id for s in self._playbook_steps(run) if s.kind == "request" and s.expects}
            ids = [d for name in step.documents for d in run.requested.get(playbook_requests.get(name, ""), [])]
            return {d: uploaded[d] for d in dict.fromkeys(ids) if d in uploaded}
        if run.documents:
            return {d: uploaded[d] for d in run.documents if d in uploaded}
        return dict(uploaded)

    def _playbook_steps(self, run: Run) -> tuple[Step, ...]:
        pb = self.store.playbook_of(uuid.UUID(run.id), uuid.UUID(run.case_id))
        if pb is None:
            from suveryn_playbooks import find
            pb = find(run.playbook_id)
        return pb.steps if pb else ()

    def finish_read(self, run: Run, playbook: Playbook, step: Step, facts: list[RunFact], model: str | None,
                    suspicious: list[int], complete: bool | None = None, documents: list[str] | None = None) -> Run | None:
        """The model answered: its reading becomes the facts' first versions (proposed, or
        not_established), the step is done. None if the run ended meanwhile. ``complete`` False: the
        documents (``documents``, their names) were longer than one reading takes and the model saw the
        passages that best match the facts; the step keeps their names and the thread says so, before
        anything waits on what was found."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        self.store.write_facts(cid, rid, step.id, [
            dict(fact_id=f.id, kind=playbook.leaf_kind(f.id), value=f.value if f.found else "",
                 status="proposed" if f.found else "not_established",
                 source={"kind": "document", "citations": [c.model_dump() for c in f.citations],
                         **({"needs": f.needs} if f.needs else {}), **({"computed": f.computed} if f.computed else {})}
                 if f.found else {"kind": "none"},
                 issues=f.issues, by=playbook.id) for f in facts if root(f.id) in step.facts])
        states = dict(run.steps)
        in_part = list(documents or []) if complete is False else []
        states[step.id] = StepState(status="done", at=_now(), in_part=in_part)
        if in_part:
            self._say(run, playbook, step.id, *self.in_part_turn(step, in_part))
        # still ``reading`` until ``advance`` has found the next wait: a poll between the two must not see a half-moved run
        if not self.store.set_step(rid, step.id, "reading", states, model=model, suspicious=suspicious):
            return None
        return self.store.get(rid, cid)

    def answer_ask(self, run: Run, playbook: Playbook, step: Step, answers: dict[str, str], by: str) -> Run:
        """A person's answers to an ask: each non-empty one is a proposed fact from that person
        (replacing the not-established reading); the step is done either way."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        current = self.store.current_versions(rid)
        answers = {fid: self.normalise(playbook, fid, v, run.language) for fid, v in answers.items() if v}
        rows = [dict(fact_id=fid, kind=playbook.leaf_kind(fid), value=v, status="proposed", source={"kind": "person"},
                     by=by, replaces=current[fid]["id"] if fid in current else None)
                for fid, v in answers.items() if root(fid) in step.facts and playbook.leaf(fid) is not None and v]
        self.store.write_facts(cid, rid, step.id, rows)
        self._settle_lists(playbook, current, [r["fact_id"] for r in rows])
        states = dict(run.steps)
        states[step.id] = StepState(status="done", by=by, at=_now())
        self.store.set_step(rid, step.id, "waiting", states)
        return self.store.get(rid, cid)  # type: ignore[return-value]  # the checks follow in ``advance``

    def answer_request(self, run: Run, step: Step, by: str, none: bool, documents: list[str] | None = None) -> Run:
        """A person says the documents are in (the runtime counts them) or, when allowed, that there is none.
        A named request (``expects``) records which documents answered it: those that came with the turn, or,
        when none did, the case's uploaded documents no other request has yet."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        states = dict(run.steps)
        if none and step.allow_none:
            states[step.id] = StepState(status="skipped", by=by, at=_now())
        else:
            states[step.id] = StepState(status="active", by=by, at=_now())  # answered: met once the documents are there
            if step.expects:
                uploaded = self.uploaded(cid)
                given = [d for d in (documents or []) if d in uploaded]
                if not given:
                    taken = {d for ds in run.requested.values() for d in ds}
                    given = [d for d in uploaded if d not in taken]
                if given:
                    self.store.assign_documents(rid, step.id, given)
        self.store.set_step(rid, step.id, "waiting", states)
        return self.store.get(rid, cid)  # type: ignore[return-value]

    def confirm(self, run: Run, playbook: Playbook, step: Step, confirmed: dict[str, str], by: str) -> Run:
        """The checkpoint: a version per fact, confirmed (or not_established when cleared), by this
        person, replacing the current one. Facts not named keep their value as read."""
        rid, cid = uuid.UUID(run.id), uuid.UUID(run.case_id)
        current = self.store.current_versions(rid)
        rows = []
        confirmed = {fid: self.normalise(playbook, fid, v, run.language) for fid, v in confirmed.items()}
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
        corrections = {fid: self.normalise(playbook, fid, v, run.language) for fid, v in corrections.items()}
        rows = [dict(fact_id=fid, kind=playbook.leaf_kind(fid), value=v, status="proposed", source={"kind": "person"},
                     by=by, replaces=current[fid]["id"] if fid in current else None)
                for fid, v in corrections.items() if v and (fid in current or (playbook.leaf(fid) is not None and fid != root(fid)))]
        self.store.write_facts(cid, rid, step.id, rows)
        self._settle_lists(playbook, current, [r["fact_id"] for r in rows if r["fact_id"] not in current])
        self.recheck(run, playbook)  # a corrected value may settle a check, or fail one
        return self.store.get(rid, cid)  # type: ignore[return-value]

    def _settle_lists(self, playbook: Playbook, current: dict[str, dict], written: list[str]) -> None:
        """A list the documents named nothing of (its own not-found version) gets entries from a person: that
        "none" is superseded, so the list is no longer open and the summary shows the entries."""
        roots = {root(fid) for fid in written if fid != root(fid)}
        self.store.supersede([current[r]["id"] for r in roots if r in current and current[r]["status"] == "not_established"])

    # -- what the playbook says (the UI words a turn from its ``meta``; ``text`` is the English for a log or an export)

    @staticmethod
    def counts(run: Run) -> tuple[int, int]:
        """How many facts have a value (read from the documents, or given by a person), of how many. A list is one
        fact, found when it has an entry with a value (board P01: "12 of 13", not its entries and fields, "14 of 15")."""
        found: dict[str, bool] = {}
        for f in shown_facts(run.facts):
            found[root(f.id)] = found.get(root(f.id), False) or bool(f.value)
        return sum(found.values()), len(found)

    def in_part_turn(self, step: Step, documents: list[str]) -> tuple[str, dict]:
        return (f"{', '.join(documents)}: longer than sūveryn reads at once. It read the passages that best match the facts, "
                "not every page: a fact not found may still be in them.",
                {"kind": "read_in_part", "step": step.id, "documents": documents})

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
        failing = sum(1 for c in fresh.checks.values() if c.status == "fails")
        return (f"{found} of {total} facts found." + (f" {issues} need checking." if issues else "") + (f" {failing} check(s) do not hold." if failing else ""),
                {"kind": "checkpoint", "found": found, "total": total, "issues": issues, "failing": failing})

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
