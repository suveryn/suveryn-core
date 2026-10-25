"""Playbook runs in a case (suveryn-tracker#51, docs/design/playbooks.md): which playbooks fit,
start one, follow it, confirm its checkpoint.

Rights (cases.md): starting a run and confirming are a contributor's; seeing runs is a reader's;
a closed case starts nothing. Every step is in the case's access log. Only the case's uploaded
documents are read.

How many runs read at once is bounded (the audit of 25 October 2026, finding 3): each is a long model
call, and nothing limited how many anyone could start. At most ``MAX_RUNS_PER_USER`` of one person's
and ``MAX_RUNS`` in all read at the same time; one more is refused with 429 and a sentence, and can be
started again once one has finished. Counted in this process (one gateway per appliance).
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
from suveryn_playbooks import PLAYBOOKS, Playbook, by_slug, covered, for_case_type

from ..playbooks import (
    ActiveIn,
    ConfirmIn,
    PlaybookOut,
    Run,
    RunStore,
    RunSummary,
    StartIn,
    summary_text,
)
from .common import (
    DocumentNotFound,
    Scope,
    admin_or_403,
    case_for,
    docs_or_503,
    log_access,
    owner_of,
    touch_case,
    who,
)

log = logging.getLogger("suveryn.gateway")
router = APIRouter()

# Runs reading at once: per person, and in all (llama-server answers four requests side by side).
MAX_RUNS_PER_USER = int(os.environ.get("SUVERYN_PLAYBOOK_RUNS_PER_USER", "2"))
MAX_RUNS = int(os.environ.get("SUVERYN_PLAYBOOK_RUNS", "4"))


class RunSlots:
    """Places for runs that read, per owner. Taken before the run is created, in one step with the check
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
                       text={lang: {"title": w.title, "summary": w.summary, "labels": w.labels} for lang, w in p.text.items()})


async def _inactive(request: Request) -> set[str]:
    """The playbooks an administrator switched off (docs/design/sidebar.md, 15); none when the
    runs store isn't there, so the list of playbooks still answers."""
    db = request.app.state.runs
    store = db.get() if db.configured else None
    return set() if store is None else await run_in_threadpool(store.inactive)


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
    list; docs/design/sidebar.md, 15)."""
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


@router.get("/v1/cases/{case_id}/playbooks/runs", response_model=list[RunSummary])
async def list_runs(case_id: str, request: Request):
    """The case's runs, newest first (a reader's right)."""
    case = await case_for(request, case_id, "read")
    return await run_in_threadpool(runs_or_503(request).list, uuid.UUID(case.id))


@router.get("/v1/cases/{case_id}/playbooks/runs/{run_id}", response_model=Run)
async def get_run(case_id: str, run_id: str, request: Request):
    """One run with its facts, as read and as confirmed, and the passages they came from."""
    case = await case_for(request, case_id, "read")
    run = await run_in_threadpool(runs_or_503(request).get, _run_id(run_id), uuid.UUID(case.id))
    if run is None:
        raise HTTPException(404, "Unknown run.")
    return run


@router.post("/v1/cases/{case_id}/playbooks/{playbook}/runs", response_model=Run, status_code=202, responses={
    403: {"description": "Not a contributor, or the case is closed"},
    404: {"description": "No such case, playbook or document"},
})
async def start_run(case_id: str, playbook: str, body: StartIn, request: Request):
    """Start a run (a contributor's right, in an open case): it reads the case's uploaded documents
    (``document_ids``, or all of them) and answers at once with the run in status ``reading``; poll
    the run until it reaches ``checkpoint`` (or ``failed``)."""
    pb = by_slug(playbook)
    case = await case_for(request, case_id, "contribute")
    if pb is None or case.type not in pb.case_types or pb.id in await _inactive(request):
        raise HTTPException(404, "No such playbook for this case.")
    # Not covered by the support agreement? It runs anyway: the licensing model warns, never blocks
    # (development context §8); the UI shows the warning from GET …/playbooks.
    docs, store, cid = docs_or_503(request), runs_or_503(request), uuid.UUID(case.id)
    scope = Scope.case(cid)
    stored = await run_in_threadpool(docs.documents, scope)
    # Only sources (cases.md decision 7): uploads, never sūveryn's own output (docs/design/sidebar.md §6).
    uploaded = {str(d["id"]): d["filename"] for d in stored if d.get("source", d.get("origin", "uploaded") == "uploaded")}
    wanted = body.document_ids or list(uploaded)
    if not wanted or any(d not in uploaded for d in wanted):
        raise HTTPException(404, "Unknown document." if wanted else "This case has no documents to read.")
    owner, slots = owner_of(request), slots_of(request.app)
    if not slots.take(owner):
        raise HTTPException(429, "too many playbook runs are reading; start this one when one has finished")
    try:
        run = await run_in_threadpool(store.create, cid, pb, wanted, who(request)[0], None)  # the username: shown, as confirmed_by
    except BaseException:
        slots.give_back(owner)
        raise
    # The reading starts at once, so the place taken above is given back however the run ends.
    task = asyncio.create_task(_read(request.app, store, run, pb, {d: uploaded[d] for d in wanted}, owner))
    request.app.state.running.add(task)
    task.add_done_callback(request.app.state.running.discard)
    task.add_done_callback(lambda _t: slots.give_back(owner))
    await log_access(request, cid, "playbook_started", {"playbook": pb.id, "version": pb.version, "run": run.id,
                                                        "documents": wanted})
    await touch_case(request, scope)
    return run


async def _read(app, store: RunStore, run: Run, pb: Playbook, filenames: dict[str, str], owner: str) -> None:
    """The model call for a run, after the request has answered (``suveryn_harness.facts``: asked
    twice before the answer counts as unreadable). Errors are stored by kind only."""
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
    await run_in_threadpool(store.read, run_id, facts, response.model, response.instruction_like_sources)


@router.put("/v1/cases/{case_id}/playbooks/runs/{run_id}/facts", response_model=Run, responses={
    409: {"description": "The run isn't waiting at its checkpoint"},
})
async def confirm_run(case_id: str, run_id: str, body: ConfirmIn, request: Request):
    """The checkpoint (a contributor's right): every fact's confirmed value, a correction or empty.
    The summary is then stored in the case as a document with origin ``playbook``."""
    case = await case_for(request, case_id, "contribute")
    store, cid, rid = runs_or_503(request), uuid.UUID(case.id), _run_id(run_id)
    current = await run_in_threadpool(store.get, rid, cid)
    if current is None:
        raise HTTPException(404, "Unknown run.")
    pb = by_slug(current.playbook_id.rsplit("/", 1)[1])
    known = {f.id for f in current.facts}
    if any(f.id not in known for f in body.facts):
        raise HTTPException(422, "A fact that isn't in this run.")
    username, _ = who(request)
    run = await run_in_threadpool(store.confirm, rid, cid, {f.id: f.confirmed for f in body.facts}, username)
    if run is None:
        raise HTTPException(409, "This run isn't waiting to be confirmed.")
    if pb is not None:
        docs = docs_or_503(request)
        name = f"{pb.name} {case.reference} ({run.playbook_version}).txt"  # the run's version, never the installed one
        try:
            document_id = await run_in_threadpool(docs.store_text, name, summary_text(pb, case.reference, run, body.language),
                                                  Scope.case(cid), "playbook",
                                                  {"playbook": pb.id, "version": run.playbook_version, "run": run.id})
            await run_in_threadpool(store.set_result, rid, document_id)
            run = run.model_copy(update={"result_document_id": document_id})
        except Exception as e:  # noqa: BLE001 - the confirmation stands; the document can be made again
            log.error("playbook result not stored: %s", type(e).__name__)
    await log_access(request, cid, "playbook_confirmed", {"playbook": current.playbook_id, "run": run.id})
    await touch_case(request, Scope.case(cid))
    return run
