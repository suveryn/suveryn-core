/**
 * Cases, stage 2 (suveryn-tracker#10): the members of a case and its access log.
 *
 * MembersDialog: the case's settings and members (board 80; suveryn-tracker#228, #229, #230), in three
 * sections: its type, its access (who sees it, and Strictly confidential), its members. Its manager
 * chooses the type from the server's list and sets the access, both applied by Save; adds a colleague
 * from the office's directory (a combo box that searches as you type), changes a member's role, removes
 * one and hands the case over, at once. Everyone else who may read the case sees the same, to read, with
 * who can change it. An administrator who isn't a member can hand the case over (decision 6), nothing
 * more. Opened at a section (``focus``): the band's *Change access*, the playbook menu's *Change the case
 * type*.
 *
 * AccessLogDialog: who did what in the case, newest first (decision 15), for the manager and the
 * administrators. Names come from the member list; a user no longer a member is shown by id.
 */
import { ArrowRightLeft, CircleAlert, Folder, Info, ScrollText, Trash, UserPlus } from "lucide-react";
import { caseTypeLabel, useCaseTypes } from "../lib/caseTypes";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  casePlaybooks, handOver, listCaseEvents, listMembers, removeMember, searchUsers, setMember, updateCase,
  type Case, type CaseEvent, type Member, type Person,
} from "../api";
import { lang, locale, useT } from "../i18n";
import { playbookWords } from "../lib/playbooks";
import { dayLabel } from "../lib/conversations";
import { Avatar, Button, ComboBoxField, Dialog, IconBadge, InlineNotice, Segmented, Select, SelectField, Switch, TextButton } from "../ui";

type Props = {
  open: boolean;
  kase: Case;
  canManage: boolean;      // the manager
  canHandOver: boolean;    // the manager, or an administrator
  officeWide: boolean;     // the appliance's default access is office-wide (shows the restriction control)
  onChanged: (c: Case) => void;  // the case after a handover or an access change
  onClose: () => void;
  /** How many of the case's conversations are shared: turning Strictly confidential on unshares them. */
  sharedCount?: number;
  /** The section to open at, its control focused: the type (the playbook menu) or the access (the band). */
  focus?: "type" | "access" | null;
};

/** What Save sends (board 80): only what was changed; a stored type no longer offered isn't sent back. */
export function caseChanges(kase: Case, now: { type: string; confidential: boolean; access: Case["access"] }) {
  return {
    ...(now.type !== kase.type ? { type: now.type } : {}),
    ...(now.confidential !== !!kase.confidential ? { confidential: now.confidential } : {}),
    ...(now.access !== kase.access ? { access: now.access } : {}),
  };
}

export function roleLabel(role: string | null, m: ReturnType<typeof useT>): string {
  return role === "manager" ? m.roleManager : role === "contributor" ? m.roleContributor : role === "reader" ? m.roleReader : "";
}

export function MembersDialog({ open, kase, canManage, canHandOver, officeWide, onChanged, onClose, sharedCount = 0, focus = null }: Props) {
  const m = useT();
  const types = useCaseTypes();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Person[]>([]);
  const [newRole, setNewRole] = useState<"reader" | "contributor">("contributor");
  const [handingOver, setHandingOver] = useState<string | null>(null); // the member chosen to take over
  // Strictly confidential and the access wait for *Save* (board G21): unsharing conversations isn't easy to undo
  const [confidential, setConfidential] = useState<boolean | null>(null);
  const [access, setAccess] = useState<Case["access"] | null>(null);
  const [type, setType] = useState<string | null>(null);
  const typeAt = useRef<HTMLElement>(null);
  const accessAt = useRef<HTMLElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try { setMembers(await listMembers(kase.id)); } catch (e) { setError((e as Error).message); }
  }, [kase.id]);
  useEffect(() => {
    if (open) { setError(null); setQuery(""); setFound([]); setHandingOver(null); setConfidential(null); setAccess(null); setType(null); refresh(); }
  }, [open, refresh]);
  const confidentialNow = confidential ?? !!kase.confidential;
  const accessNow = access ?? kase.access;
  const typeNow = type ?? kase.type;
  const changes = caseChanges(kase, { type: typeNow, confidential: confidentialNow, access: accessNow });
  // Opened at a section: its control takes the focus once the dialog has placed its own (on its first field or ×).
  useEffect(() => {
    if (!open || !focus) return;
    const at = (focus === "type" ? typeAt : accessAt).current;
    const t = setTimeout(() => {
      at?.scrollIntoView({ block: "nearest" });
      // the type's button (its field's hidden select isn't a control), the access's switch
      at?.querySelector<HTMLElement>(focus === "type" ? "button" : "input")?.focus();
    }, 60);
    return () => clearTimeout(t);
  }, [open, focus]);
  const manager = members?.find((x) => x.role === "manager");
  // The server's list; a stored type it no longer offers stays shown as stored (suveryn-tracker#229)
  const typeOptions = [...types.map((t) => ({ id: t.id, label: caseTypeLabel(t.id, types) })),
                       ...(types.some((t) => t.id === kase.type) ? [] : [{ id: kase.type, label: kase.type }])];
  const changed = Object.keys(changes).length > 0;

  const labelOf = (p: Person) => (p.name === p.username ? p.name : `${p.name} (${p.username})`);
  const typed = query.trim();
  const inCase = new Set((members ?? []).map((x) => x.user));
  const candidates = found.filter((p) => !inCase.has(p.sub));
  const chosen = candidates.find((p) => labelOf(p) === typed || p.username === typed || p.name === typed);

  // The directory, searched as you type (after a short pause). A chosen suggestion (its whole label
  // in the field) isn't searched for again: the field holds the choice until the next keystroke.
  useEffect(() => {
    if (!open || !canManage || (typed && found.some((p) => labelOf(p) === typed))) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { setFound(await searchUsers(typed)); } catch { setFound([]); }
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [typed, open, canManage]);  // eslint-disable-line react-hooks/exhaustive-deps -- `found` is what the search sets

  const act = async (what: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try { await what(); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const add = () => chosen && act(async () => { await setMember(kase.id, chosen.sub, newRole); setQuery(""); });
  const changeRole = (member: Member, role: string) => {
    if (role === "manager") { setHandingOver(member.user); return; }
    act(() => setMember(kase.id, member.user, role as "reader" | "contributor"));
  };
  const confirmHandOver = () => handingOver && act(async () => { onChanged(await handOver(kase.id, handingOver)); setHandingOver(null); });
  const save = () => act(async () => { onChanged(await updateCase(kase.id, changes)); onClose(); });

  const roleOptions = [
    { id: "reader", label: m.roleReader }, { id: "contributor", label: m.roleContributor }, { id: "manager", label: m.roleManager },
  ];
  const taking = members?.find((x) => x.user === handingOver);

  const body = (
    <>
      {/* who may change the type and the access: the manager, or, said to everyone else, by name (board 80) */}
      {/* a closed case changes for nobody: no line */}
      {kase.state === "open" && (
        <p className="caption case-settings-who">{canManage ? m.youManageCase : manager ? m.onlyManagerChanges({ name: manager.name || manager.username }) : ""}</p>
      )}
      <section className="case-settings-section" ref={typeAt}>
        <h3 className="ui-label">{m.caseType}</h3>
        {canManage
          ? <SelectField name="type" label={m.caseType} hideLabel description={m.caseTypeDecides} options={typeOptions} value={typeNow} onChange={setType} />
          : <>
            <p className="case-settings-value">{caseTypeLabel(kase.type, types)}</p>
            <p className="ui-hint">{m.caseTypeDecides}</p>
          </>}
        {typeNow !== kase.type && (
          <InlineNotice icon={<Info size={14} />} status>{m.caseTypeWillOffer({ type: caseTypeLabel(typeNow, types) })}</InlineNotice>
        )}
      </section>
      <section className="case-settings-section" ref={accessAt}>
        <h3 className="ui-label">{m.caseSectionAccess}</h3>
        {canManage ? <>
          {/* Strictly confidential (docs/design/chat-ui.md §11; boards G21, 24): the manager's switch, and what Save will do. */}
          <div className="case-confidential">
            <Switch label={m.strictlyConfidential} checked={confidentialNow} onChange={setConfidential} isDisabled={busy} />
            <p className="ui-hint">{m.confidentialHint}</p>
            {confidentialNow && !kase.confidential && sharedCount > 0 && (
              <InlineNotice icon={<Info size={14} />} status>{m.confidentialWillUnshare({ n: sharedCount })}</InlineNotice>
            )}
            {!confidentialNow && kase.confidential && (
              // what it lifts; opening to the whole office only where the office's appliance allows it
              <InlineNotice icon={<Info size={14} />} status>{officeWide ? m.confidentialOffNotice : m.confidentialOffNoticeMembers}</InlineNotice>
            )}
          </div>
          {officeWide && (
            <div className="case-access">
              <span className="ui-label">{m.caseAccess}</span>
              <Segmented label={m.caseAccess} value={accessNow} onChange={(v) => setAccess(v as Case["access"])} isDisabled={confidentialNow}
                         options={[{ value: "default", label: m.accessOffice }, { value: "restricted", label: m.accessMembers }]} />
              <p className="ui-hint">{accessNow === "restricted" ? m.accessMembersHint : m.accessOfficeHint}</p>
            </div>
          )}
        </> : <>
          <p className="case-settings-value">{kase.confidential ? m.strictlyConfidential : kase.access === "restricted" ? m.accessMembers : m.accessOffice}</p>
          <p className="ui-hint">{kase.confidential ? m.confidentialHint : kase.access === "restricted" ? m.accessMembersHint : m.accessOfficeHint}</p>
        </>}
      </section>
      <h3 className="ui-label case-settings-members">{m.members}</h3>
      {members === null ? <p className="caption">{m.loading}</p> : (
        <ul className="member-list">
          {members.map((member) => (
            <li key={member.user} className="member">
              <Avatar name={member.name || member.username || member.user} sub={member.user} etag={member.avatar} admin={member.admin}
                      adminLabel={m.administrator} size="small" className="member-avatar" />
              <span className="member-name">{member.name || member.username || member.user}</span>
              <span className="member-user">{member.username}</span>
              {canManage && member.role !== "manager" ? (
                <Select label={m.roleOf({ name: member.name })} options={roleOptions} value={member.role} className="member-role"
                        onChange={(role) => changeRole(member, role)} />
              ) : (
                <span className="member-role-text">{roleLabel(member.role, m)}</span>
              )}
              {canManage && member.role !== "manager" && (
                <TextButton link onPress={() => act(() => removeMember(kase.id, member.user))} isDisabled={busy}>
                  <Trash size={14} aria-hidden /> {m.remove}
                </TextButton>
              )}
              {canHandOver && !canManage && member.role !== "manager" && (
                <TextButton link onPress={() => setHandingOver(member.user)} isDisabled={busy}>
                  <ArrowRightLeft size={14} aria-hidden /> {m.makeManager}
                </TextButton>
              )}
            </li>
          ))}
        </ul>
      )}
      {taking && (
        <InlineNotice icon={<ArrowRightLeft size={14} />}>
          {m.handOverConfirm({ name: taking.name || taking.username })}{" "}
          <TextButton link onPress={confirmHandOver} isDisabled={busy}>{m.handOver}</TextButton>{" "}
          <TextButton onPress={() => setHandingOver(null)} isDisabled={busy}>{m.cancel}</TextButton>
        </InlineNotice>
      )}
      {canManage && (
        <div className="member-add">
          <ComboBoxField name="colleague" label={m.addColleague} description={m.addColleagueHint} value={query} onChange={setQuery}
                         options={candidates.map((p) => ({ id: p.sub, label: labelOf(p) }))} />
          <div className="member-add-row">
            <Select label={m.caseRole} value={newRole} onChange={(r) => setNewRole(r as "reader" | "contributor")}
                    options={roleOptions.slice(0, 2)} />
            <Button size="small" onPress={add} isDisabled={busy || !chosen}><UserPlus size={14} aria-hidden /> {m.add}</Button>
          </div>
        </div>
      )}
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
    </>
  );
  // the manager changes the type and the access, applied by Save (boards 80, G21); everyone else reads them
  return canManage ? (
    <Dialog isOpen={open} onClose={onClose} busy={busy} closeLabel={m.close} kind="form" title={m.caseSettingsTitle({ reference: kase.reference })}
            cancel={{ label: m.cancel }} primary={{ label: m.save, onPress: save, disabled: !changed }}>
      {body}
    </Dialog>
  ) : (
    <Dialog isOpen={open} onClose={onClose} busy={busy} closeLabel={m.close} kind="information" title={m.caseSettingsTitle({ reference: kase.reference })}>
      {body}
    </Dialog>
  );
}

/** What an access-log action means, in the interface language. */
/** One row of the access log as a whole sentence, in pieces: the person (``who``, as the screen draws it) where the
 *  language puts it, and the words around it. */
export function eventParts<T extends object>(e: CaseEvent, m: ReturnType<typeof useT>, who: T | string, nameOf: (user: string) => string = () => "",
                                             playbookTitle: (id: string) => string = () => ""): (string | T)[] {
  const d = e.detail;
  switch (e.action) {
    case "created": return m.eventCreated.parts({ who });
    case "opened": return m.eventOpened.parts({ who });
    case "uploaded": return m.eventUploaded.parts({ who });
    case "asked": return m.eventAsked.parts({ who, n: Array.isArray(d.documents) ? d.documents.length : 0 });
    case "upload_cancelled": return m.eventUploadCancelled.parts({ who });
    case "document_opened": return m.eventDocumentOpened.parts({ who });
    case "document_deleted": return m.eventDocumentDeleted.parts({ who });
    case "confidential_on": return m.eventConfidentialOn.parts({ who });
    case "confidential_off": return m.eventConfidentialOff.parts({ who });
    case "source_confirmed": return m.eventSourceConfirmed.parts({ who });
    case "answer_saved": return m.eventAnswerSaved.parts({ who });
    case "conversation_moved_in": return m.eventConversationMovedIn.parts({ who });
    case "changed": return m.eventChanged.parts({ who });
    case "access_changed": return d.access === "restricted" ? m.eventRestricted.parts({ who }) : m.eventOpenedToOffice.parts({ who });
    case "member_added": return m.eventMemberAdded.parts({ who, role: String(d.role ?? "") });
    case "role_changed": return m.eventRoleChanged.parts({ who, role: String(d.role ?? "") });
    case "member_removed": return m.eventMemberRemoved.parts({ who });
    // to whom, and which playbook (VM regression e0f2e26, finding 12)
    case "handed_over": return nameOf(String(d.manager ?? "")) ? m.eventHandedOverTo.parts({ who, name: nameOf(String(d.manager)) }) : m.eventHandedOver.parts({ who });
    case "closed": return m.eventClosed.parts({ who });
    case "reopened": return m.eventReopened.parts({ who });
    case "keep_changed": return m.eventKeepChanged.parts({ who });
    case "conversation_shared": return m.eventConversationShared.parts({ who });
    case "conversation_unshared": return m.eventConversationUnshared.parts({ who });
    case "playbook_started": return playbookTitle(String(d.playbook ?? "")) ? m.eventPlaybookStartedNamed.parts({ who, title: playbookTitle(String(d.playbook)) }) : m.eventPlaybookStarted.parts({ who });
    case "playbook_answered": return m.eventPlaybookAnswered.parts({ who });
    case "playbook_confirmed": return m.eventPlaybookConfirmed.parts({ who });
    case "playbook_paused": return m.eventPlaybookPaused.parts({ who });
    case "playbook_resumed": return m.eventPlaybookResumed.parts({ who });
    case "playbook_stopped": return m.eventPlaybookStopped.parts({ who });
    case "playbook_cancelled": return m.eventPlaybookCancelled.parts({ who });
    default: return [who, ` ${e.action}`];
  }
}

export function AccessLogDialog({ open, kase, onClose }: { open: boolean; kase: Case; onClose: () => void }) {
  const m = useT();
  const [events, setEvents] = useState<CaseEvent[] | null>(null);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [titles, setTitles] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    setError(null);
    setEvents(null);
    listCaseEvents(kase.id).then(setEvents).catch((e: Error) => setError(e.message));
    listMembers(kase.id).then((ms) => setNames(new Map(ms.map((x) => [x.user, x.name || x.username])))).catch(() => {});
    casePlaybooks(kase.id).then((ps) => setTitles(new Map(ps.map((p) => [p.id, playbookWords(p, lang()).title])))).catch(() => {});
  }, [open, kase.id]);
  return (
    <Dialog isOpen={open} onClose={onClose} kind="information" title={m.accessLogTitle({ reference: kase.reference })} closeLabel={m.close} error={error}>
      <p>{m.accessLogIntro}</p>
      {events === null && !error && <p className="caption">{m.loading}</p>}
      {events && events.length === 0 && <p className="caption">{m.accessLogEmpty}</p>}
      {events && events.length > 0 && (
        <ol className="event-list">
          {events.map((e) => (
            <li key={e.id} className="event">
              <span className="event-when">{dayLabel(e.at)} {new Date(e.at).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })}</span>
              <span className="event-what"><ScrollText size={12} aria-hidden />
                {/* one sentence, the person in bold where the language puts them */}
                <span>{eventParts(e, m, { who: e.name || names.get(e.user) || e.user }, (u) => names.get(u) ?? "", (id) => titles.get(id) ?? "")
                  .map((part, i) => (typeof part === "string" ? part : <b key={i} className="event-who">{part.who}</b>))}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Dialog>
  );
}

/** A case's members as faces (the case header, docs/design/chat-ui.md §5): the manager first, set apart
 *  with the folder badge, then up to three others overlapping, then "+n". Decorative: the button
 *  around it names everyone. */
export function CaseFaces({ members }: { members: Member[] }) {
  const m = useT();
  const manager = members.find((x) => x.role === "manager");
  const others = members.filter((x) => x !== manager);
  const face = (x: Member) => (
    <Avatar key={x.user} name={x.name || x.username} sub={x.user} etag={x.avatar} admin={x.admin} adminLabel={m.administrator} size="small"
            shield={x !== manager} />
  );
  return (
    <span className="case-faces" aria-hidden>
      {manager && <IconBadge badge={<Folder />} host="small" tone="role">{face(manager)}</IconBadge>}
      {others.length > 0 && (
        <span className="case-faces-stack">
          {others.slice(0, 3).map(face)}
          {others.length > 3 && <span className="case-faces-more">{m.moreMembers({ n: others.length - 3 })}</span>}
        </span>
      )}
    </span>
  );
}
