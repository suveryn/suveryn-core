/**
 * Cases, stage 2 (suveryn-tracker#10): the members of a case and its access log.
 *
 * MembersDialog: who is in the case and as what. Its manager adds a colleague from the office's
 * directory (a combo box that searches as you type), changes a member's role, removes one, hands
 * the case over, and restricts the case to its members or opens it to the office. Everyone else
 * who may read the case sees the list only. An administrator who isn't a member sees the manager
 * and can hand the case over (decision 6), nothing more.
 *
 * AccessLogDialog: who did what in the case, newest first (decision 15), for the manager and the
 * administrators. Names come from the member list; a user no longer a member is shown by id.
 */
import { AlertCircle, ArrowRightLeft, Folder, ScrollText, Trash2, UserPlus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  handOver, listCaseEvents, listMembers, removeMember, searchUsers, setMember, updateCase,
  type Case, type CaseEvent, type Member, type Person,
} from "../api";
import { locale, useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { Avatar, Button, ComboBoxField, Dialog, IconBadge, InlineNotice, Segmented, Select, Switch, TextButton } from "../ui";

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
};

export function roleLabel(role: string | null, m: ReturnType<typeof useT>): string {
  return role === "manager" ? m.roleManager : role === "contributor" ? m.roleContributor : role === "reader" ? m.roleReader : "";
}

export function MembersDialog({ open, kase, canManage, canHandOver, officeWide, onChanged, onClose, sharedCount = 0 }: Props) {
  const m = useT();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Person[]>([]);
  const [newRole, setNewRole] = useState<"reader" | "contributor">("contributor");
  const [handingOver, setHandingOver] = useState<string | null>(null); // the member chosen to take over
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try { setMembers(await listMembers(kase.id)); } catch (e) { setError((e as Error).message); }
  }, [kase.id]);
  useEffect(() => { if (open) { setError(null); setQuery(""); setFound([]); setHandingOver(null); refresh(); } }, [open, refresh]);

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
  const setAccess = (access: string) => act(async () => onChanged(await updateCase(kase.id, { access: access as Case["access"] })));
  const setConfidential = (on: boolean) => act(async () => onChanged(await updateCase(kase.id, { confidential: on })));

  const roleOptions = [
    { id: "reader", label: m.roleReader }, { id: "contributor", label: m.roleContributor }, { id: "manager", label: m.roleManager },
  ];
  const taking = members?.find((x) => x.user === handingOver);

  return (
    <Dialog isOpen={open} onClose={onClose} busy={busy} title={m.membersTitle(kase.reference)} actions={<>
      <TextButton onPress={onClose} isDisabled={busy}>{m.close}</TextButton>
    </>}>
      {canManage && (
        // Strictly confidential (docs/design/chat-ui.md §11): the manager's switch, with what it changes.
        <div className="case-confidential">
          <Switch label={m.strictlyConfidential} checked={!!kase.confidential} onChange={setConfidential} isDisabled={busy} />
          <p className="ui-hint">{m.confidentialHint}{" "}
            {!kase.confidential && sharedCount > 0 && m.confidentialUnshares(sharedCount)}</p>
        </div>
      )}
      {canManage && officeWide && (
        <div className="case-access">
          <span className="ui-label">{m.caseAccess}</span>
          <Segmented label={m.caseAccess} value={kase.access} onChange={setAccess} isDisabled={!!kase.confidential}
                     options={[{ value: "default", label: m.accessOffice }, { value: "restricted", label: m.accessMembers }]} />
          <p className="ui-hint">{kase.access === "restricted" ? m.accessMembersHint : m.accessOfficeHint}</p>
        </div>
      )}
      {members === null ? <p className="caption">{m.loading}</p> : (
        <ul className="member-list">
          {members.map((member) => (
            <li key={member.user} className="member">
              <Avatar name={member.name || member.username || member.user} sub={member.user} etag={member.avatar} admin={member.admin}
                      adminLabel={m.administrator} size="small" className="member-avatar" />
              <span className="member-name">{member.name || member.username || member.user}</span>
              <span className="member-user">{member.username}</span>
              {canManage && member.role !== "manager" ? (
                <Select label={m.roleOf(member.name)} options={roleOptions} value={member.role} className="member-role"
                        onChange={(role) => changeRole(member, role)} />
              ) : (
                <span className="member-role-text">{roleLabel(member.role, m)}</span>
              )}
              {canManage && member.role !== "manager" && (
                <TextButton link onPress={() => act(() => removeMember(kase.id, member.user))} isDisabled={busy}>
                  <Trash2 size={14} aria-hidden /> {m.remove}
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
          {m.handOverConfirm(taking.name || taking.username)}{" "}
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
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}

/** What an access-log action means, in the interface language. */
export function eventLabel(e: CaseEvent, m: ReturnType<typeof useT>): string {
  const d = e.detail as Record<string, string | string[]>;
  switch (e.action) {
    case "created": return m.eventCreated;
    case "opened": return m.eventOpened;
    case "documents": return m.eventDocuments;
    case "uploaded": return m.eventUploaded;
    case "asked": return m.eventAsked(Array.isArray(d.documents) ? d.documents.length : 0);
    case "document_deleted": return m.eventDocumentDeleted;
    case "source_confirmed": return m.eventSourceConfirmed;
    case "answer_saved": return m.eventAnswerSaved;
    case "conversation_moved_in": return m.eventConversationMovedIn;
    case "changed": return m.eventChanged;
    case "access_changed": return d.access === "restricted" ? m.eventRestricted : m.eventOpenedToOffice;
    case "member_added": return m.eventMemberAdded(roleLabel(String(d.role ?? ""), m));
    case "role_changed": return m.eventRoleChanged(roleLabel(String(d.role ?? ""), m));
    case "member_removed": return m.eventMemberRemoved;
    case "handed_over": return m.eventHandedOver;
    case "closed": return m.eventClosed;
    case "reopened": return m.eventReopened;
    case "keep_changed": return m.eventKeepChanged;
    case "conversation_shared": return m.eventConversationShared;
    case "conversation_unshared": return m.eventConversationUnshared;
    case "playbook_started": return m.eventPlaybookStarted;
    case "playbook_answered": return m.eventPlaybookAnswered;
    case "playbook_confirmed": return m.eventPlaybookConfirmed;
    case "playbook_paused": return m.eventPlaybookPaused;
    case "playbook_resumed": return m.eventPlaybookResumed;
    case "playbook_stopped": return m.eventPlaybookStopped;
    case "playbook_cancelled": return m.eventPlaybookCancelled;
    default: return e.action;
  }
}

export function AccessLogDialog({ open, kase, onClose }: { open: boolean; kase: Case; onClose: () => void }) {
  const m = useT();
  const [events, setEvents] = useState<CaseEvent[] | null>(null);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    setError(null);
    setEvents(null);
    listCaseEvents(kase.id).then(setEvents).catch((e: Error) => setError(e.message));
    listMembers(kase.id).then((ms) => setNames(new Map(ms.map((x) => [x.user, x.name || x.username])))).catch(() => {});
  }, [open, kase.id]);
  return (
    <Dialog isOpen={open} onClose={onClose} title={m.accessLogTitle(kase.reference)} actions={<>
      <TextButton onPress={onClose}>{m.close}</TextButton>
    </>}>
      <p>{m.accessLogIntro}</p>
      {events === null && !error && <p className="caption">{m.loading}</p>}
      {events && events.length === 0 && <p className="caption">{m.accessLogEmpty}</p>}
      {events && events.length > 0 && (
        <ol className="event-list">
          {events.map((e) => (
            <li key={e.id} className="event">
              <span className="event-when">{dayLabel(e.at)} {new Date(e.at).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })}</span>
              <span className="event-who">{e.name || names.get(e.user) || e.user}</span>
              <span className="event-what"><ScrollText size={12} aria-hidden /> {eventLabel(e, m)}</span>
            </li>
          ))}
        </ol>
      )}
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
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
    <Avatar key={x.user} name={x.name || x.username} sub={x.user} etag={x.avatar} admin={x.admin} adminLabel={m.administrator} size="small" />
  );
  return (
    <span className="case-faces" aria-hidden>
      {manager && <IconBadge badge={<Folder />} tone="neutral">{face(manager)}</IconBadge>}
      {others.length > 0 && (
        <span className="case-faces-stack">
          {others.slice(0, 3).map(face)}
          {others.length > 3 && <span className="case-faces-more">{m.moreMembers(others.length - 3)}</span>}
        </span>
      )}
    </span>
  );
}
