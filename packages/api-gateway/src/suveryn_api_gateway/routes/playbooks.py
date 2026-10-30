"""Playbook runs in a case (suveryn-tracker#51, docs/design/playbooks.md): which playbooks fit,
start one, follow its thread, answer what it asks, confirm its checkpoint, pause, stop or cancel it.

Rights (cases.md): starting a run, answering and confirming are a contributor's; seeing runs is a
reader's; pausing and resuming anyone in the case may do who may contribute; stopping and
cancelling are the starter's or the case manager's; a closed case starts nothing. Every step is
in the case's access log. Only the case's uploaded documents are read.

One live run per playbook per case: a second start while one is reading, waiting or paused is
refused with 409 and the live run's id.

How many runs read at once is bounded (the audit of 25 October 2026, finding 3): each is a long model
call, and nothing limited how many anyone could start. At most ``MAX_RUNS_PER_USER`` of one person's
and ``MAX_RUNS`` in all read at the same time; one more is refused with 429 and a sentence, and can be
started again once one has finished. Counted in this process (one gateway per appliance).

The walk itself is the runtime's (``playbook_runtime``); these routes check rights, write the
people's turns, start the model call for a ``read`` and log.
"""

import asyncio
import logging
import os
import uuid
from collections import Counter

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from suveryn_harness import BackendError, DocumentsUnavailable
from suveryn_harness.facts import Unreadable, read_playbook
from suveryn_playbooks import PLAYBOOKS, Playbook, Step, by_slug, covered, find, for_case_type

from ..cases import Case
from ..playbook_runtime import Runtime
from ..playbooks import (
    ActiveIn,
    AnswerIn,
    CancelIn,
    ConfirmIn,
    PlaybookOut,
    Run,
    RunStore,
    RunSummary,
    StartIn,
    StepOut,
)
from .common import (
    DocumentNotFound,
    Scope,
    admin_or_403,
    case_for,
    docs_or_503,
    log_access,
    owner_of,
    readable_case_ids,
    touch_case,
    who,
)

log = logging.getLogger("suveryn.gateway")
router = APIRouter()

# Runs reading at once: per person, and in all (llama-server answers four requests side by side).
MAX_RUNS_PER_USER = int(os.environ.get("SUVERYN_PLAYBOOK_RUNS_PER_USER", "2"))
MAX_RUNS = int(os.environ.get("SUVERYN_PLAYBOOK_RUNS", "4"))


class RunSlots:
    """Places for runs that read, per owner. Taken before the read starts, in one step with the check
    (no await in between), and given back when its reading ends, however it ends."""

    def __init__(self):
        self.taken: Counter[str] = Counter()

    def take(self, owner: str) -> bool:
        if self.taken[owner] >= MAX_RUNS_PER_USER or sum(self.taken.values()) >= MAX_RUNS:
            return False
        self.taken[owner] += 1
        return True

    def give_back(self, owner: str) -> None:
        self.taken[owner] -= 1
        if self.taken[owner] <= 0:
            del self.taken[owner]


def slots_of(app) -> RunSlots:
    if not hasattr(app.state, "playbook_slots"):
        app.state.playbook_slots = RunSlots()
    return app.state.playbook_slots


def runs_or_503(request: Request) -> RunStore:
    db = request.app.state.runs
    if not db.configured:
        raise HTTPException(503, "Playbooks are not available on this server.")
    store = db.get()
    if store is None:
        raise HTTPException(503, f"Playbooks are not available right now: {db.error}.")
    return store


def _run_id(run_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(422, f"Not a run id: {run_id!r}") from None


def _out(p: Playbook, inactive: frozenset[str] | set[str] = frozenset()) -> PlaybookOut:
    return PlaybookOut(id=p.id, slug=p.slug, pack=p.pack, version=p.version, name=p.name, covered=covered(p.id),
                       facts=[f.id for f in p.facts], case_types=list(p.case_types), active=p.id not in inactive,
                       text={lang: {"title": w.title, "summary": w.summary, "labels": w.labels, "questions": w.questions}
                             for lang, w in p.text.items()},
                       steps=[StepOut(id=s.id, kind=s.kind, needs=list(s.needs), facts=list(s.facts)) for s in p.steps])


async def _inactive(request: Request) -> set[str]:
    """The playbooks an administrator switched off (docs/design/admin.md); none when the
    runs store isn't there, so the list of playbooks still answers."""
    db = request.app.state.runs
    store = db.get() if db.configured else None
    return set() if store is None else await run_in_threadpool(store.inactive)


def _uploaded_in(request: Request):
    """A function the runtime calls to see a case's uploaded documents now (id -> file name): only
    sources (cases.md decision 7), never sūveryn's own output (docs/design/chat-ui.md §6)."""
    docs = docs_or_503(request)

    def uploaded(case_id: uuid.UUID) -> dict[str, str]:
        stored = docs.documents(Scope.case(case_id))
        return {str(d["id"]): d["filename"] for d in stored if d.get("source", d.get("origin", "uploaded") == "uploaded")}

    return uploaded


def _runtime(request: Request) -> Runtime:
    return Runtime(runs_or_503(request), docs_or_503(request), _uploaded_in(request))


# ------------------------------------------------------------------------------ which playbooks

@router.get("/v1/cases/{case_id}/playbooks", response_model=list[PlaybookOut])
async def case_playbooks(case_id: str, request: Request):
    """The playbooks that fit this case's type and are switched on, each with whether it is covered
    by the appliance's support agreement (``covered`` false: it runs, with a warning; never a block)."""
    case = await case_for(request, case_id, "read")
    inactive = await _inactive(request)
    return [_out(p, inactive) for p in for_case_type(case.type) if p.id not in inactive]


@router.get("/v1/admin/playbooks", response_model=list[PlaybookOut])
async def admin_playbooks(request: Request):
    """Every installed playbook with its case types and whether it is switched on (an administrator's
    list; docs/design/admin.md)."""
    admin_or_403(request)
    inactive = await _inactive(request)
    return [_out(p, inactive) for p in PLAYBOOKS]


@router.put("/v1/admin/playbooks/{playbook}", response_model=PlaybookOut, responses={404: {"description": "No such playbook"}})
async def set_playbook_active(playbook: str, body: ActiveIn, request: Request):
    """Switch a playbook on or off for the whole office: off, it leaves every case's menu and can't
    be started; runs already made stay."""
    admin_or_403(request)
    pb = by_slug(playbook)
    if pb is None:
        raise HTTPException(404, "No such playbook.")
    store = runs_or_503(request)
    await run_in_threadpool(store.set_active, pb.id, body.active, who(request)[0])
    return _out(pb, await _inactive(request))


# ------------------------------------------------------------------------------ runs

@router.get("/v1/playbooks/runs/active", response_model=dict[str, RunSummary])
async def active_runs(request: Request):
    """The live run per case the caller may read, keyed by case id: the chip on the case lists."""
    case_ids = await readable_case_ids(request)
    if not case_ids:
        return {}
    return await run_in_threadpool(runs_or_503(request).active_in_cases, case_ids)


@router.get("/v1/cases/{case_id}/playbooks/runs", response_model=list[RunSummary])
async def list_runs(case_id: str, request: Request):
    """The case's runs, newest first (a reader's right)."""
    case = await case_for(request, case_id, "read")
    return await run_in_threadpool(runs_or_503(request).list, uuid.UUID(case.id))


@router.get("/v1/cases/{case_id}/playbooks/runs/{run_id}", response_model=Run)
async def get_run(case_id: str, run_id: str, request: Request):
    """One run: where it is, its thread, its facts as read and as confirmed with the passages they came from."""
    case = await case_for(request, case_id, "read")
    run = await run_in_threadpool(runs_or_503(request).get, _run_id(run_id), uuid.UUID(case.id))
    if run is None:
        raise HTTPException(404, "Unknown run.")
    return run


@router.post("/v1/cases/{case_id}/playbooks/{playbook}/runs", response_model=Run, status_code=202, responses={
    403: {"description": "Not a contributor, or the case is closed"},
    404: {"description": "No such case, playbook or document"},
    409: {"description": "A run of this playbook is already going in this case"},
})
async def start_run(case_id: str, playbook: str, body: StartIn, request: Request):
    """Start a run (a contributor's right, in an open case) and walk it to its first wait: a
    request for documents, or straight into reading when the case has them and the routine starts
    there. ``document_ids`` narrows what the read step reads (none: every uploaded document, at the
    time it reads). Answers with the run; poll it, or answer what it asks."""
    pb = by_slug(playbook)
    case = await case_for(request, case_id, "contribute")
    if pb is None or case.type not in pb.case_types or pb.id in await _inactive(request):
        raise HTTPException(404, "No such playbook for this case.")
    # Not covered by the support agreement? It runs anyway: the licensing model warns, never blocks
    # (development context §8); the UI shows the warning from GET …/playbooks.
    store, cid = runs_or_503(request), uuid.UUID(case.id)
    live = await run_in_threadpool(store.active, cid, pb.id)
    if live is not None:
        raise HTTPException(409, detail={"message": "This playbook is already going in this case.", "run": live.id})
    uploaded = await run_in_threadpool(_uploaded_in(request), cid)
    if any(d not in uploaded for d in body.document_ids):
        raise HTTPException(404, "Unknown document.")
    run = await run_in_threadpool(store.create, cid, pb, body.document_ids, who(request)[0], None, body.language, owner_of(request))
    await log_access(request, cid, "playbook_started", {"playbook": pb.id, "version": pb.version, "run": run.id,
                                                        "documents": body.document_ids})
    await touch_case(request, Scope.case(cid))
    return await _walk(request, run, pb, case)


async def _walk(request: Request, run: Run, pb: Playbook, case: Case) -> Run:
    """Advance the run as far as it goes without a person; start the model call if it reaches a read."""
    runtime, store, cid = _runtime(request), runs_or_503(request), uuid.UUID(case.id)
    step = await run_in_threadpool(runtime.advance, run, pb, case.reference)
    if step is not None:
        await _start_read(request, runtime, store, run, pb, step, case)
    fresh = await run_in_threadpool(store.get, uuid.UUID(run.id), cid)
    return fresh or run


async def _start_read(request: Request, runtime: Runtime, store: RunStore, run: Run, pb: Playbook, step: Step, case: Case) -> None:
    rid, owner = uuid.UUID(run.id), owner_of(request)
    filenames = await run_in_threadpool(runtime.documents_to_read, run)
    if not filenames:
        await run_in_threadpool(store.fail, rid, "document_missing")
        return
    await run_in_threadpool(store.set_documents, rid, list(filenames))
    slots = slots_of(request.app)
    if not slots.take(owner):
        await run_in_threadpool(store.fail, rid, "busy")
        raise HTTPException(429, "too many playbook runs are reading; start this one when one has finished")
    task = asyncio.create_task(_read(request.app, runtime, store, run, pb, step, filenames, owner, case.reference))
    request.app.state.running.add(task)
    task.add_done_callback(request.app.state.running.discard)
    task.add_done_callback(lambda _t: slots.give_back(owner))


async def _read(app, runtime: Runtime, store: RunStore, run: Run, pb: Playbook, step: Step, filenames: dict[str, str],
                owner: str, reference: str) -> None:
    """The model call for a read step, after the request has answered (``suveryn_harness.facts``:
    asked twice before the answer counts as unreadable). Errors are stored by kind only. When the
    answer is in, the run walks on (to the ask, or the checkpoint)."""
    run_id = uuid.UUID(run.id)
    try:
        facts, response = await read_playbook(lambda req: app.state.chat.answer(req, owner), pb, filenames, run.case_id,
                                              on_retry=lambda n, shape: log.info("playbook run %s: answer %d not readable as the table: %s",
                                                                                 run.id, n, " ".join(f"{k}={v}" for k, v in shape.items())))
    except (BackendError, DocumentsUnavailable, DocumentNotFound, Unreadable) as e:
        await run_in_threadpool(store.fail, run_id, {BackendError: "model_unavailable", DocumentsUnavailable: "documents_unavailable",
                                                     DocumentNotFound: "document_missing", Unreadable: "unreadable_answer"}[type(e)])
        return
    except Exception as e:  # noqa: BLE001 - the run must end in a state; the message may hold document text
        log.error("playbook run failed: %s", type(e).__name__)
        await run_in_threadpool(store.fail, run_id, "server_error")
        return
    fresh = await run_in_threadpool(runtime.finish_read, run, pb, step, facts, response.model, response.instruction_like_sources)
    if fresh is None:
        return  # stopped or cancelled while reading
    try:
        again = await run_in_threadpool(runtime.advance, fresh, pb, reference)
    except Exception as e:  # noqa: BLE001
        log.error("playbook run could not go on: %s", type(e).__name__)
        return
    if again is not None:  # a routine with a second read: not in any official playbook yet
        log.error("playbook run %s: a second read step is not supported yet", run.id)
        await run_in_threadpool(store.fail, run_id, "server_error")


async def _live_run(request: Request, case_id: str, run_id: str, action: str) -> tuple[Case, RunStore, Run, Playbook]:
    case = await case_for(request, case_id, action)
    store = runs_or_503(request)
    run = await run_in_threadpool(store.get, _run_id(run_id), uuid.UUID(case.id))
    if run is None:
        raise HTTPException(404, "Unknown run.")
    pb = find(run.playbook_id)
    if pb is None:
        raise HTTPException(409, "This run's playbook is no longer installed.")
    if not run.steps:
        raise HTTPException(409, "This run was made by an earlier version and can only be viewed. Start the playbook again.")
    return case, store, run, pb


def _waiting_on(run: Run, pb: Playbook, step_id: str, kinds: tuple[str, ...]) -> Step:
    if run.status != "waiting" or run.step != step_id:
        raise HTTPException(409, "The run isn't waiting on this step." if run.status != "paused" else "The run is paused.")
    step = pb.step(step_id)
    if step is None or step.kind not in kinds:
        raise HTTPException(409, "This step doesn't take an answer.")
    return step


@router.post("/v1/cases/{case_id}/playbooks/runs/{run_id}/answer", response_model=Run, responses={
    409: {"description": "The run isn't waiting on that step"},
})
async def answer_run(case_id: str, run_id: str, body: AnswerIn, request: Request):
    """A contributor answers the step the run waits on. An ``ask``: ``facts`` with a value per fact
    (empty: still unknown; the checkpoint can fill it). A ``request``: the documents are in the case
    now, or ``none`` when the step allows that. The answer is written in the thread and the run walks on."""
    case, store, run, pb = await _live_run(request, case_id, run_id, "contribute")
    step = _waiting_on(run, pb, body.step_id, ("ask", "request"))
    username = who(request)[0]
    runtime, rid, cid = _runtime(request), uuid.UUID(run.id), uuid.UUID(case.id)
    if step.kind == "ask":
        asked = set(await run_in_threadpool(runtime.unanswered, run, step))  # only what the playbook asked about
        given = {k: v for k, v in (body.facts or {}).items() if k in asked}
        if (body.facts or {}).keys() - asked:
            raise HTTPException(422, "A fact that isn't asked here.")
        text = body.text or "\n".join(f"{pb.wording(run.language).labels.get(k, k)}: {v}" for k, v in given.items() if v.strip())
        await run_in_threadpool(store.append, rid, "user", username, text or "—", step.id, {"facts": sorted(given)})
        run = await run_in_threadpool(runtime.answer_ask, run, pb, step, given, username)
    else:
        if body.none and not step.allow_none:
            raise HTTPException(422, "This step needs the document.")
        await run_in_threadpool(store.append, rid, "user", username, body.text or ("—" if body.none else "✓"), step.id, {"none": body.none})
        run = await run_in_threadpool(runtime.answer_request, run, step, username, body.none)
    await log_access(request, cid, "playbook_answered", {"playbook": pb.id, "run": run.id, "step": step.id})
    await touch_case(request, Scope.case(cid))
    return await _walk(request, run, pb, case)


@router.put("/v1/cases/{case_id}/playbooks/runs/{run_id}/facts", response_model=Run, responses={
    409: {"description": "The run isn't waiting at its checkpoint"},
})
async def confirm_run(case_id: str, run_id: str, body: ConfirmIn, request: Request):
    """The checkpoint (a contributor's right): every fact's confirmed value, a correction or empty.
    The run then walks on: the summary is stored in the case as a document with origin ``playbook``."""
    case, store, run, pb = await _live_run(request, case_id, run_id, "contribute")
    step = _waiting_on(run, pb, run.step or "", ("checkpoint",))
    known = {f.id for f in run.facts}
    if any(f.id not in known for f in body.facts):
        raise HTTPException(422, "A fact that isn't in this run.")
    username = who(request)[0]
    run = await run_in_threadpool(_runtime(request).confirm, run, pb, step, {f.id: f.confirmed for f in body.facts}, username)
    await log_access(request, uuid.UUID(case.id), "playbook_confirmed", {"playbook": pb.id, "run": run.id})
    await touch_case(request, Scope.case(uuid.UUID(case.id)))
    return await _walk(request, run, pb, case)


# ------------------------------------------------------------------------------ pause, stop, cancel

def _may_end(request: Request, case: Case, run: Run) -> None:
    """Stopping and cancelling: the starter's (by id, never by the shown name), or the case manager's."""
    me = owner_of(request)
    if run.starter != me and case.manager != me:
        raise HTTPException(403, "Only the person who started this run or the case manager can end it.")


@router.post("/v1/cases/{case_id}/playbooks/runs/{run_id}/pause", response_model=Run, responses={409: {"description": "Not waiting"}})
async def pause_run(case_id: str, run_id: str, request: Request):
    """Keep everything and wait (anyone who contributes to the case). A run that is reading can't be
    paused mid-call; pause it when it waits."""
    case, store, run, pb = await _live_run(request, case_id, run_id, "contribute")
    if not await run_in_threadpool(store.pause, uuid.UUID(run.id), who(request)[0]):
        raise HTTPException(409, "Only a run that is waiting can be paused.")
    await log_access(request, uuid.UUID(case.id), "playbook_paused", {"playbook": pb.id, "run": run.id})
    return await run_in_threadpool(store.get, uuid.UUID(run.id), uuid.UUID(case.id))


@router.post("/v1/cases/{case_id}/playbooks/runs/{run_id}/resume", response_model=Run, responses={409: {"description": "Not paused"}})
async def resume_run(case_id: str, run_id: str, request: Request):
    case, store, run, pb = await _live_run(request, case_id, run_id, "contribute")
    if not await run_in_threadpool(store.resume, uuid.UUID(run.id)):
        raise HTTPException(409, "This run isn't paused.")
    await log_access(request, uuid.UUID(case.id), "playbook_resumed", {"playbook": pb.id, "run": run.id})
    fresh = await run_in_threadpool(store.get, uuid.UUID(run.id), uuid.UUID(case.id))
    return await _walk(request, fresh, pb, case)


@router.post("/v1/cases/{case_id}/playbooks/runs/{run_id}/stop", response_model=Run, responses={
    403: {"description": "Not the starter or the manager"}, 409: {"description": "Already ended"}})
async def stop_run(case_id: str, run_id: str, request: Request):
    """End early, keeping what was achieved: confirmed facts stay the case's; proposed ones go;
    a product made so far stays as a document. A new run reads the confirmed facts and doesn't ask twice."""
    case, store, run, pb = await _live_run(request, case_id, run_id, "contribute")
    _may_end(request, case, run)
    rid = uuid.UUID(run.id)
    if not await run_in_threadpool(store.end, rid, "stopped", who(request)[0]):
        raise HTTPException(409, "This run has already ended.")
    await run_in_threadpool(store.discard_proposed, rid)
    await log_access(request, uuid.UUID(case.id), "playbook_stopped", {"playbook": pb.id, "run": run.id})
    return await run_in_threadpool(store.get, rid, uuid.UUID(case.id))


@router.post("/v1/cases/{case_id}/playbooks/runs/{run_id}/cancel", response_model=Run, responses={
    403: {"description": "Not the starter or the manager"}, 409: {"description": "Already ended"}})
async def cancel_run(case_id: str, run_id: str, body: CancelIn, request: Request):
    """The run should not have happened: its confirmed facts go back to proposed (kept, with their
    provenance), its product is marked withdrawn (never deleted), and the case shows no result from it."""
    case, store, run, pb = await _live_run(request, case_id, run_id, "contribute")
    _may_end(request, case, run)
    rid, username = uuid.UUID(run.id), who(request)[0]
    if not await run_in_threadpool(store.end, rid, "cancelled", username, body.reason):
        raise HTTPException(409, "This run has already ended.")
    await run_in_threadpool(store.revert_confirmed, rid, username)
    if run.result_document_id:
        try:
            await run_in_threadpool(docs_or_503(request).withdraw, run.result_document_id, Scope.case(uuid.UUID(case.id)), username, body.reason)
        except Exception as e:  # noqa: BLE001 - the cancel stands; the mark can be set again
            log.error("playbook result not marked withdrawn: %s", type(e).__name__)
    await log_access(request, uuid.UUID(case.id), "playbook_cancelled", {"playbook": pb.id, "run": run.id})
    return await run_in_threadpool(store.get, rid, uuid.UUID(case.id))
