"""Cases (suveryn-tracker#10): the case, its members, handover, the access log, closing and the
keep period. The rules are in ``cases.may``; ``common.case_for`` applies them per request."""

import uuid
from functools import partial
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..cases import (
    KEEP_PERIODS,
    AdminCase,
    Case,
    CaseEvent,
    CaseIn,
    CaseOverview,
    CaseUpdate,
    DuplicateReference,
    HandoverIn,
    KeepIn,
    Member,
    MemberIn,
    PinIn,
    SettingsIn,
    SettingsOut,
    SettingsPreview,
    StrictlyConfidential,
    may,
    shielded,
)
from ..directory import DirectoryUnavailable, Person
from .users import _do, as_admin
from .common import (
    LOCAL_OWNER,
    CleanupUnavailable,
    admin_or_403,
    case_for,
    case_settings,
    cases_or_503,
    delete_case_everywhere,
    history_or_none,
    log_access,
    owner_of,
    person_or_404,
    principal,
    remember_user,
    visible_case,
    who,
    with_faces,
)

router = APIRouter()


@router.get("/v1/cases", response_model=list[Case])
async def list_cases(request: Request, closed: bool = False):
    """The cases the caller may see: open ones first, most recently active first. Closed cases
    only with ``closed=true``. ``my_role`` is the caller's role in each."""
    store, caller = cases_or_503(request), principal(request)
    return await run_in_threadpool(store.list, caller.sub, office_wide=case_settings(request).office_wide,
                                   admin=caller.admin, closed=closed)


@router.get("/v1/cases/overview", response_model=list[CaseOverview])
async def cases_overview(request: Request):
    """Every case the caller may see, open and closed, as the Cases overview shows them
    (docs/design/chat-ui.md §4): each with its members (the manager first, with their pictures'
    ETags) and its last activity, who and when. An administrator who isn't a member sees no members."""
    store, caller = cases_or_503(request), principal(request)
    cases = await run_in_threadpool(store.list, caller.sub, office_wide=case_settings(request).office_wide,
                                    admin=caller.admin, closed=True)
    inside = [uuid.UUID(c.id) for c in cases if c.my_role is not None]
    members = await run_in_threadpool(store.members_of, inside) if inside else {}
    last = await run_in_threadpool(store.last_activity, inside) if inside else {}
    faced = {m.user: m for m in await with_faces(request, [m for ms in members.values() for m in ms], key="user")}
    out = []
    for c in cases:
        cid = uuid.UUID(c.id)
        people = [faced.get(m.user, m) for m in members.get(cid, [])]
        at, by = last.get(cid, (None, ""))
        name = next((m.name or m.username for m in people if m.user == by), "")
        out.append(CaseOverview(**c.model_dump(), members=people, last_activity_at=at or c.updated_at, last_activity_by=name))
    return out


@router.post("/v1/cases", response_model=Case, status_code=201, responses={409: {"description": "A case with this reference exists"}})
async def create_case(body: CaseIn, request: Request):
    """Open a new case. The caller becomes its manager and first member.
    The reference is the office's own file number, unique on this appliance; never put a client's
    name in it or the name."""
    store = cases_or_503(request)
    await remember_user(request)
    try:
        return await run_in_threadpool(store.create, body, owner_of(request), *who(request))
    except DuplicateReference:
        raise HTTPException(409, "A case with this reference already exists.") from None


@router.get("/v1/cases/due", response_model=list[Case])
async def due_cases(request: Request):
    """Closed cases due for deletion within a month (or overdue), soonest first: every one for an
    administrator, the ones they manage for anyone else. Shown so they can extend, reopen or keep."""
    store, caller = cases_or_503(request), principal(request)
    return await run_in_threadpool(store.due, caller.sub, admin=caller.admin)


@router.get("/v1/cases/{case_id}", response_model=Case, responses={404: {"description": "Unknown case"}})
async def get_case(case_id: str, request: Request):
    """One case the caller may see."""
    case = await case_for(request, case_id, "read")
    await log_access(request, uuid.UUID(case.id), "opened")
    return case


@router.patch("/v1/cases/{case_id}", response_model=Case, responses={
    403: {"description": "Not the case's manager, or the case is closed"}, 404: {"description": "Unknown case"},
    409: {"description": "A case with this reference exists, or the access can't be opened while strictly confidential"}})
async def update_case(case_id: str, body: CaseUpdate, request: Request):
    """Change a case's reference, name, type, subject, access or strictly confidential label (its
    manager only). Turning the label on restricts the access and unshares the case's conversations."""
    case = await case_for(request, case_id, "manage")
    try:
        changed = await run_in_threadpool(cases_or_503(request).update, uuid.UUID(case.id), body)
    except DuplicateReference:
        raise HTTPException(409, "A case with this reference already exists.") from None
    except StrictlyConfidential:
        raise HTTPException(409, "A strictly confidential case is for its members only.") from None
    fields = body.model_dump(exclude_none=True)
    if "confidential" in fields and fields["confidential"] != case.confidential:
        # Turning it on unshares the case's shared conversations; their owners keep them (§11).
        unshared = 0
        if fields["confidential"] and (history := history_or_none(request)) is not None:
            unshared = await run_in_threadpool(history.unshare_case, uuid.UUID(case.id))
        await log_access(request, uuid.UUID(case.id), "confidential_on" if fields["confidential"] else "confidential_off",
                         {"unshared": unshared} if fields["confidential"] else {})
    access = changed.access if changed else fields.get("access")
    if access is not None and access != case.access:
        await log_access(request, uuid.UUID(case.id), "access_changed", {"access": access})
    if set(fields) - {"access", "confidential"}:
        await log_access(request, uuid.UUID(case.id), "changed", {"fields": sorted(set(fields) - {"access", "confidential"})})
    # the caller's own view of it: their role and their pin (the sidebar keeps a pinned case pinned)
    return shielded(changed.model_copy(update={"my_role": case.my_role, "pinned": case.pinned})) if changed else changed


@router.delete("/v1/cases/{case_id}", status_code=204, responses={
    403: {"description": "Not the case's manager"}, 404: {"description": "Unknown case"},
    503: {"description": "A store the case is in can't be reached: nothing was deleted"}})
async def delete_case(case_id: str, request: Request):
    """Delete a case with its documents and conversations (its manager only). Closing and the
    keep period (docs/design/cases.md, stage 3) are the office's way; this is for a case opened
    by mistake. See ``Store.delete_document`` for what deletion does and doesn't guarantee."""
    case = await case_for(request, case_id, "manage")
    try:
        deleted = await delete_case_everywhere(request.app, uuid.UUID(case.id))
    except CleanupUnavailable as e:
        raise HTTPException(503, f"The case can't be deleted now ({e}); nothing was deleted. Try again shortly.") from e
    if not deleted:
        raise HTTPException(404, "Unknown case.")
    return Response(status_code=204)


@router.put("/v1/cases/{case_id}/pin", response_model=Case, responses={404: {"description": "Unknown case"}})
async def pin_case(case_id: str, body: PinIn, request: Request):
    """Pin or unpin the case in the caller's own sidebar (docs/design/chat-ui.md): anyone who may
    read it; per user, never shared, not in the access log."""
    case = await case_for(request, case_id, "read")
    store, cid = cases_or_503(request), uuid.UUID(case.id)
    await run_in_threadpool(store.set_pinned, cid, owner_of(request), body.pinned)
    return case.model_copy(update={"pinned": body.pinned})


# ------------------------------------------------------------------ closing and the keep period (stage 3)
@router.post("/v1/cases/{case_id}/close", response_model=Case, responses={
    403: {"description": "Not the case's manager"}, 404: {"description": "Unknown case"}, 409: {"description": "Already closed"}})
async def close_case(case_id: str, request: Request):
    """Close the case (its manager only): read-only from now, reopenable while it is kept, and
    deleted after the office's keep period (``SUVERYN_CASES_KEEP``; with ``manual``, kept until
    deleted by hand). ``keep_until`` says when."""
    case = await case_for(request, case_id, "close")
    closed = await run_in_threadpool(cases_or_503(request).close_case, uuid.UUID(case.id), case_settings(request).keep_period)
    if closed is None:
        raise HTTPException(409, "This case is already closed.")
    await log_access(request, uuid.UUID(case.id), "closed",
                     {"keep_until": closed.keep_until.isoformat() if closed.keep_until else None})
    return shielded(closed.model_copy(update={"my_role": case.my_role}))


@router.post("/v1/cases/{case_id}/reopen", response_model=Case, responses={
    403: {"description": "Not the case's manager"}, 404: {"description": "Unknown case"}, 409: {"description": "Not closed"}})
async def reopen_case(case_id: str, request: Request):
    """Reopen a closed case (its manager only): open again, no deletion planned."""
    case = await case_for(request, case_id, "reopen")
    reopened = await run_in_threadpool(cases_or_503(request).reopen_case, uuid.UUID(case.id))
    if reopened is None:
        raise HTTPException(409, "This case is not closed.")
    await log_access(request, uuid.UUID(case.id), "reopened")
    return shielded(reopened.model_copy(update={"my_role": case.my_role}))


@router.post("/v1/cases/{case_id}/keep", response_model=Case, responses={
    403: {"description": "Neither the case's manager nor an administrator"}, 404: {"description": "Unknown case"},
    409: {"description": "Not closed"}})
async def keep_case(case_id: str, body: KeepIn, request: Request):
    """On a closed case: ``{"keep": true}`` marks it kept (never deleted by the period), ``{"keep":
    false}`` plans its deletion one period from now again, ``{"extend": true}`` moves its
    deletion one period later. The manager's and the administrators' right (decision 11)."""
    store, cid, caller, case = await visible_case(request, case_id)
    if not may(caller, case, case.my_role, "set_keep", case_settings(request).office_wide):
        raise HTTPException(403, "Only the case's manager or an administrator can change how long it is kept."
                            if case.state == "closed" else "This case is open; close it first.")
    if body.keep is None and not body.extend:
        raise HTTPException(422, "Say what to change: keep, or extend.")
    changed = await run_in_threadpool(store.set_keep, cid, body.keep, body.extend, case_settings(request).keep_period)
    if changed is None:
        raise HTTPException(409, "This case is not closed.")
    await log_access(request, cid, "keep_changed", {"keep": changed.keep,
                                                    "keep_until": changed.keep_until.isoformat() if changed.keep_until else None})
    return shielded(changed.model_copy(update={"my_role": case.my_role}))


# ------------------------------------------------------------------ members and the office's directory (stage 2)
@router.get("/v1/users", response_model=list[Person], responses={503: {"description": "The directory is not available"}})
async def list_users(request: Request, q: str = ""):
    """The office's accounts (id, username, name) whose username, name or email contains ``q``,
    to add a colleague to a case. From Keycloak, through the ``suveryn-directory`` client."""
    try:
        people = await request.app.state.directory.search(q)
    except DirectoryUnavailable as e:
        raise HTTPException(503, f"The office's directory is not available right now: {e}.") from e
    return await with_faces(request, people)


@router.get("/v1/users/departed", response_model=dict[str, str])
async def departed_users(request: Request):
    """The names of accounts an administrator deleted, by id: what they did in the cases keeps their name
    (who added a document, whose shared conversation). Names only."""
    db = request.app.state.cases
    store = db.get() if db.configured else None
    return await run_in_threadpool(store.departed_names) if store is not None else {}


@router.get("/v1/cases/{case_id}/members", response_model=list[Member], responses={404: {"description": "Unknown case"}})
async def list_members(case_id: str, request: Request):
    """The case's members and their roles, the manager first (anyone who may read the case)."""
    case = await case_for(request, case_id, "read")
    members = await run_in_threadpool(cases_or_503(request).members, uuid.UUID(case.id))
    return await with_faces(request, members, key="user")


@router.put("/v1/cases/{case_id}/members/{user}", response_model=Member, responses={
    403: {"description": "Not the case's manager, or the case is closed"},
    404: {"description": "Unknown case or user"}, 422: {"description": "The manager's role is changed by handing over"}})
async def set_member(case_id: str, user: str, body: MemberIn, request: Request):
    """Add a colleague to the case as a reader or contributor, or change a member's role (the
    manager's right). The colleague must be one of the office's accounts. To make someone the
    manager, hand the case over (``POST .../handover``)."""
    case = await case_for(request, case_id, "manage")
    if body.role == "manager":
        raise HTTPException(422, "Hand the case over to make someone its manager.")
    person = await person_or_404(request, user)
    store, cid = cases_or_503(request), uuid.UUID(case.id)
    before = await run_in_threadpool(store.role_of, cid, user)
    try:
        member = await run_in_threadpool(store.set_member, cid, user, body.role, owner_of(request),
                                         person.username, person.name)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    await log_access(request, cid, "member_added" if before is None else "role_changed", {"user": user, "role": body.role})
    return member


@router.delete("/v1/cases/{case_id}/members/{user}", status_code=204, responses={
    403: {"description": "Not the case's manager, or the case is closed"},
    404: {"description": "Unknown case or not a member"}, 422: {"description": "The manager can't be removed"}})
async def remove_member(case_id: str, user: str, request: Request):
    """Take a member out of the case (the manager's right). The manager can't be removed: hand
    the case over first."""
    case = await case_for(request, case_id, "manage")
    if user == case.manager:
        raise HTTPException(422, "Hand the case over before removing its manager.")
    store, cid = cases_or_503(request), uuid.UUID(case.id)
    if not await run_in_threadpool(store.remove_member, cid, user):
        raise HTTPException(404, "Not a member of this case.")
    await log_access(request, cid, "member_removed", {"user": user})
    return Response(status_code=204)


@router.post("/v1/cases/{case_id}/handover", response_model=Case, responses={
    403: {"description": "Neither the case's manager nor an administrator"}, 404: {"description": "Unknown case or user"}})
async def handover(case_id: str, body: HandoverIn, request: Request):
    """Make another colleague the case's manager: the current manager may, and an administrator
    (decision 6: an account can't go while it manages a case). The previous manager stays on as
    a contributor."""
    store, cid, caller, case = await visible_case(request, case_id)
    office_wide = case_settings(request).office_wide
    if not (may(caller, case, case.my_role, "handover", office_wide) or may(caller, case, case.my_role, "manage", office_wide)):
        raise HTTPException(403, "Only the case's manager or an administrator can hand a case over.")
    person = await person_or_404(request, body.user)
    handed = await run_in_threadpool(store.set_manager, cid, body.user, caller.sub, person.username, person.name)
    if handed is None:
        raise HTTPException(404, "Unknown case.")
    await log_access(request, cid, "handed_over", {"manager": body.user})
    return shielded(handed, await run_in_threadpool(store.role_of, cid, caller.sub))


@router.get("/v1/cases/{case_id}/events", response_model=list[CaseEvent], responses={
    403: {"description": "Neither the case's manager nor an administrator"}, 404: {"description": "Unknown case"}})
async def case_events(case_id: str, request: Request):
    """The case's access log, newest first: who did what, when (decision 15). For its manager
    and the administrators; kept 180 days, as the sign-in events."""
    store, cid, caller, case = await visible_case(request, case_id)
    if not may(caller, case, case.my_role, "read_log", case_settings(request).office_wide):
        raise HTTPException(403, "Only the case's manager or an administrator can see its access log.")
    events = await run_in_threadpool(store.events, cid)
    # Someone who acted without being a member (an administrator handing a case over) has no name in the case:
    # it comes from the directory (VM regression of 29 October, finding 9). Never fatal: the id stays.
    nameless = {e.user for e in events if not e.name and e.user}
    names: dict[str, str] = {}
    directory = getattr(request.app.state, "directory", None)
    for sub in list(nameless)[:20] if directory is not None else []:
        try:
            person = await directory.get(sub)
        except Exception:  # noqa: BLE001 - a missing name is cosmetic
            person = None
        if person is not None:
            names[sub] = person.name or person.username
    return [e.model_copy(update={"name": names[e.user]}) if not e.name and e.user in names else e for e in events]


# ------------------------------------------------------------------ the administrator's pages (stage 4)
@router.get("/v1/admin/cases", response_model=list[AdminCase], responses={403: {"description": "Not an administrator"}})
async def admin_cases(request: Request):
    """Administrators: every case on the appliance, open ones first, with who manages it and how
    many members it has; nothing from inside a case. For handing cases over before an account
    goes (decision 6), and for seeing what is closed and due."""
    admin_or_403(request)
    return await run_in_threadpool(cases_or_503(request).list_all, owner_of(request))


@router.get("/v1/admin/cases/settings", response_model=SettingsOut, responses={403: {"description": "Not an administrator"}})
async def admin_case_settings(request: Request):
    """Administrators: the office's settings as they apply now: the default access of a new case,
    how long closed cases are kept, and how long saved conversations are kept (the data lifecycle,
    suveryn-tracker#31). As provisioned, until changed here."""
    admin_or_403(request)
    store, effective = cases_or_503(request), case_settings(request)
    meta = await run_in_threadpool(store.overrides_meta)
    return SettingsOut(default_access=effective.default_access, keep=effective.keep,
                       conversations_keep=effective.conversations_keep, two_step=effective.two_step,
                       updated_at=meta[0] if meta else None, updated_by=meta[1] if meta else "")


@router.get("/v1/admin/cases/settings/preview", response_model=SettingsPreview,
            responses={403: {"description": "Not an administrator"}})
async def preview_case_settings(request: Request, default_access: Literal["office", "members"] | None = None,
                                apply_to: Literal["new", "all"] = "new",
                                conversations_keep: Literal["6m", "1y", "5y", "manual"] | None = None):
    """Administrators: what saving these settings would do now, for the confirmation in Settings: how many
    cases become visible to everyone in the office or to their members only, and how many saved
    conversations a shorter keep period deletes. Counts only."""
    admin_or_403(request)
    store, now = cases_or_503(request), case_settings(request)
    counts = await run_in_threadpool(store.access_counts)
    out = SettingsPreview()
    if default_access == "office" and now.default_access == "members" and apply_to == "all":
        out.cases_opened = counts["default"] + counts["restricted"]
    elif default_access == "members" and now.default_access == "office":
        out.cases_closed = counts["default"]
    period = KEEP_PERIODS.get(conversations_keep or now.conversations_keep)
    current = KEEP_PERIODS.get(now.conversations_keep)
    history = history_or_none(request)
    if history is not None and period is not None and (current is None or period < current):
        out.conversations_deleted = await run_in_threadpool(history.older_than, period.days)
    return out


@router.put("/v1/admin/cases/settings", response_model=SettingsOut, responses={403: {"description": "Not an administrator"}})
async def set_admin_case_settings(body: SettingsIn, request: Request):
    """Administrators: change the default access (``office`` or ``members``), the keep period of
    closed cases and the keep period of saved conversations (each ``6m``, ``1y``, ``5y`` or ``manual``).
    Takes effect at once for new cases and for cases closed from now on; a case already closed keeps
    its date (extend or keep it from the case). The conversations period applies to every saved
    conversation from its last change: shortening it hides the older ones from lists at once and deletes them when it is saved (and by the hourly sweep).

    Opening the default access to the office applies to new cases (``apply_to: new``: the existing ones
    stay with their members, restricted, and a manager can open one) or to all of them (``all``: every case,
    restricted ones too, each with a line in its access log). Closing it to the members applies to every
    case that follows the default. Strictly confidential cases never change: their members decide."""
    admin_or_403(request)
    changes = body.model_dump(exclude_none=True, exclude={"apply_to"})
    if not changes:
        raise HTTPException(422, "Say what to change: default_access, keep, conversations_keep or two_step.")
    if "two_step" in changes:
        on = changes.pop("two_step")
        if on != case_settings(request).two_step:
            # Two-step sign-in for every account (Filip, 29 October: off by default, the administrator's choice).
            # Keycloak first, as the administrator: the setting is stored only once every account follows it.
            accounts, token = await as_admin(request)
            await _do(accounts.require_two_step(token, on))
        changes["two_step"] = "on" if on else "off"
    user = getattr(request.state, "user", None)
    opens = changes.get("default_access") == "office" and case_settings(request).default_access == "members"
    await run_in_threadpool(partial(cases_or_503(request).set_overrides, changes, user.username if user else "local-dev",
                                    keep_existing=opens and body.apply_to == "new", open_all=opens and body.apply_to == "all",
                                    by_user=user.sub if user else LOCAL_OWNER))
    if "conversations_keep" in changes and (history := history_or_none(request)) is not None:
        # At once, not at the next hourly sweep: the confirmation said they are deleted, and until then they would go
        # into the night's backup (VM check of 28 October, finding 4). history_or_none told it the new period.
        await run_in_threadpool(history.purge)
    return await admin_case_settings(request)
