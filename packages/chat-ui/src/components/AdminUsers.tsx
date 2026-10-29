/**
 * Administration › Users (docs/design/admin.md, artboards 32, 34 and 39): the office's accounts, managed here
 * so nobody needs Keycloak's console. The list (name and e-mail, administrator, last sign-in, on or off), *Add
 * user* (the page's one orange button), a row menu per account, and *Sign-ins and changes*.
 *
 * The appliance sends no e-mail, so adding someone or resetting a password shows a temporary password once, to
 * pass on; it works until its first use, when Keycloak asks for the person's own (no expiry kept beside Keycloak). Switching off someone who manages cases hands each case over inside the dialog first. There is
 * always one administrator: the menu item is disabled with the reason under it, and the gateway refuses too.
 */
import { AlertCircle, AlertTriangle, Copy, Folder, LogOut, MoreHorizontal, Printer, RefreshCw, RectangleEllipsis, Shield, ShieldOff, Smartphone, Trash2, UserPlus, UserRoundCheck, UserRoundX } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  accountDeletion, addAccount, deleteAccount, handOver, HttpError, listAccountEvents, listAccounts, listAdminCases, resetAccountPassword, resetAccountTwoStep,
  setAccountAdmin, setAccountEnabled, signAccountOut,
  type Account, type AccountDeletion, type AccountEvent, type AdminCase, type TemporaryPassword, type UsersList,
} from "../api";
import { locale, useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import {
  ActionMenu, Avatar, Button, Checkbox, DataTable, Dialog, FilterSelect, Form, InlineNotice, NARROW, Notice, SearchField, SelectField,
  TextButton, TextField, useMedia, type MenuEntry, type TableColumn,
} from "../ui";

type Filter = "on" | "off" | "all";
type Confirm = { kind: "admin_on" | "admin_off" | "password" | "two_step" | "sign_out" | "off" | "on" | "delete"; user: Account };

const timeLabel = (iso: string) => new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
const whenLabel = (iso: string) => `${dayLabel(iso)} ${timeLabel(iso)}`;

export function AdminUsers({ me, onLostAdministration }: { me: string; onLostAdministration: () => void }) {
  const m = useT();
  const narrow = useMedia(NARROW);
  const [list, setList] = useState<UsersList | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("on");
  const [adding, setAdding] = useState(false);
  const [temporary, setTemporary] = useState<TemporaryPassword | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [events, setEvents] = useState<AccountEvent[] | null>(null);
  const [allEvents, setAllEvents] = useState(false);

  const load = useCallback(async () => {
    try {
      setList(await listAccounts());
      setFailed(null);
    } catch (e) {
      setFailed((e as Error).message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { listAccountEvents(allEvents ? 200 : 20).then(setEvents).catch(() => setEvents(null)); }, [allEvents, list]);

  const users = list?.users ?? [];
  const counted = users.filter((u) => u.enabled).length;
  const admins = users.filter((u) => u.admin && u.enabled);
  const over = list?.agreement_users != null && counted > list.agreement_users;
  const query = q.trim().toLowerCase();
  const shown = users.filter((u) => (filter === "all" || (filter === "on") === u.enabled)
    && (!query || u.name.toLowerCase().includes(query) || u.email.toLowerCase().includes(query)));

  const menu = (u: Account): MenuEntry[] => {
    const self = u.sub === me;
    const lastAdmin = u.admin && admins.length === 1 && admins[0].sub === u.sub;
    return [
      u.admin
        ? { id: "admin_off", label: m.removeAdministratorRights, icon: <ShieldOff size={16} />, isDisabled: lastAdmin,
            ...(lastAdmin ? { description: m.onlyAdministrator } : {}) }
        : { id: "admin_on", label: m.makeAdministrator, icon: <Shield size={16} />, isDisabled: !u.enabled },
      { id: "password", label: m.resetPassword, icon: <RectangleEllipsis size={16} /> },
      { id: "two_step", label: m.resetTwoStep, icon: <Smartphone size={16} /> },
      { id: "sign_out", label: m.signOutEverywhere, icon: <LogOut size={16} /> },
      "-",
      u.enabled
        ? { id: "off", label: m.switchAccountOff, icon: <UserRoundX size={16} />, isDisabled: self || lastAdmin,
            ...(self ? { description: m.notForOwnAccount } : lastAdmin ? { description: m.onlyAdministrator } : {}) }
        : { id: "on", label: m.switchAccountOn, icon: <UserRoundCheck size={16} /> },
      // Deleting is a second step, once the account is off (Filip, 29 October).
      { id: "delete", label: m.deleteAccount, icon: <Trash2 size={16} />, isDisabled: self || u.enabled,
        ...(self ? { description: m.notForOwnAccount } : u.enabled ? { description: m.switchOffFirst } : {}) },
    ];
  };
  const rowMenu = (u: Account) => (
    <ActionMenu aria-label={m.rowActions(u.name)} menuLabel={m.rowActions(u.name)} entries={menu(u)} placement="bottom end"
                className="overview-row-menu" onAction={(id) => setConfirm({ kind: id as Confirm["kind"], user: u })}>
      <MoreHorizontal size={16} aria-hidden />
    </ActionMenu>
  );
  const face = (u: Account) => (
    <span className="user-cell" data-off={!u.enabled || undefined}>
      <Avatar name={u.name} sub={u.sub} admin={u.admin} adminLabel={m.administrator} size="small" />
      <span className="user-names"><b>{u.name}</b><span className="overview-dim">{u.email || u.username}</span></span>
    </span>
  );
  const columns: TableColumn<Account & { id: string }>[] = [
    { id: "user", label: m.colUser, rowHeader: true, render: face },
    { id: "admin", label: m.colAdministrator, render: (u) => (u.admin ? m.yes : <span className="overview-dim">{m.no}</span>) },
    { id: "last", label: m.colLastSignedIn,
      render: (u) => <span className="overview-dim">{(u.last_sign_in ? whenLabel(u.last_sign_in) : u.last_sign_in_unknown ? m.notSignedInLately : m.neverSignedIn)}</span> },
    { id: "account", label: m.colAccount, render: (u) => (u.enabled ? m.accountOn : <span className="overview-dim">{m.accountOff}</span>) },
    { id: "actions", label: m.colActions, hideLabel: true, width: "48px", render: rowMenu },
  ];

  if (failed && !list) {
    return (
      <>
        <Notice icon={<AlertCircle size={16} />} title={m.usersUnavailable}>{sentence(failed)}</Notice>
        <Button size="small" onPress={load}><RefreshCw size={14} aria-hidden /> {m.tryAgain}</Button>
      </>
    );
  }
  return (
    <>
      <div className="users-tools">
        <SearchField label={m.userSearch} value={q} onChange={setQ} className="users-search" />
        {!narrow && (
          <FilterSelect label={m.colAccount} value={filter} onChange={(v) => setFilter(v as Filter)} clearLabel={m.clearSearch}
                        options={(["on", "off", "all"] as Filter[]).map((id) => ({ id, label: m.accountFilter[id] }))} />
        )}
        {list && (
          <span className="users-count">
            {over && <AlertTriangle size={14} aria-hidden />}{m.usersCount(counted, list.agreement_users)}
          </span>
        )}
        <Button variant="primary" onPress={() => setAdding(true)} aria-label={narrow ? m.addUser : undefined}>
          <UserPlus size={16} aria-hidden />{!narrow && ` ${m.addUser}`}
        </Button>
      </div>

      {!list ? (
        <ul className="admin-checks" aria-busy="true">
          {[0, 1, 2].map((i) => <li key={i} className="admin-check admin-skeleton" aria-hidden><span /><span /></li>)}
        </ul>
      ) : users.length === 1 && !query ? (
        <div className="users-empty"><b>{m.onlyUser}</b></div>
      ) : shown.length === 0 && query ? (
        <p className="caption">{m.noUserFound(q.trim())} <TextButton link onPress={() => setQ("")}>{m.clearSearch}</TextButton></p>
      ) : narrow ? (
        <ul className="users-list">
          {shown.map((u) => (
            <li key={u.sub}>
              {face(u)}
              <span className="users-list-meta overview-dim">
                {[u.admin ? m.administrator : "", u.enabled ? ((u.last_sign_in ? whenLabel(u.last_sign_in) : u.last_sign_in_unknown ? m.notSignedInLately : m.neverSignedIn)) : m.accountOff]
                  .filter(Boolean).join(" · ")}
              </span>
              {rowMenu(u)}
            </li>
          ))}
        </ul>
      ) : (
        <DataTable label={m.adminUsers} columns={columns} rows={shown.map((u) => ({ ...u, id: u.sub }))} />
      )}
      {list && <p className="caption">{m.offDontCount}</p>}

      <section aria-labelledby="sign-ins" className="users-events">
        <h2 id="sign-ins" className="label">{m.signInsAndChanges}</h2>
        {events && events.length > 0 && (
          <table className="users-events-table">
            <tbody>
              {events.map((e, i) => (
                <tr key={i}>
                  <td className="overview-dim">{whenLabel(e.at)}</td>
                  <td>{e.name || m.unknownAccount}</td>
                  <td>{eventText(e, m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="caption">{m.kept180Days}{" "}
          {!allEvents && events && events.length >= 20 && <TextButton link onPress={() => setAllEvents(true)}>{m.showAll}</TextButton>}
        </p>
      </section>

      <AddUserDialog open={adding} counted={counted} max={list?.agreement_users ?? null} onClose={() => setAdding(false)}
                     onAdded={(t) => { setAdding(false); setTemporary(t); load(); }} />
      <TemporaryDialog temporary={temporary} onClose={() => setTemporary(null)} />
      <ConfirmDialog confirm={confirm} me={me} onClose={() => setConfirm(null)} onTemporary={setTemporary}
                     onDone={(lostAdministration) => { setConfirm(null); if (lostAdministration) onLostAdministration(); else load(); }} />
    </>
  );
}

function eventText(e: AccountEvent, m: ReturnType<typeof useT>) {
  if (e.kind === "sign_in_failed") {
    return <span className="status-warn"><AlertTriangle size={13} aria-hidden /> {m.signInFailed[e.reason ?? "other"]}</span>;
  }
  const what = m.accountEvent[e.kind];
  return e.by ? m.byWhom(what, e.by) : what;
}

function AddUserDialog({ open, counted, max, onClose, onAdded }: {
  open: boolean; counted: number; max: number | null; onClose: () => void; onAdded: (t: TemporaryPassword) => void;
}) {
  const m = useT();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [admin, setAdmin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setName(""); setEmail(""); setAdmin(false); setError(null); } }, [open]);
  const check = () => {
    const errors: Record<string, string> = {};
    if (!name.trim()) errors.name = m.required;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) errors.email = m.required;
    return errors;
  };
  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      onAdded(await addAccount(name.trim(), email.trim(), admin));
    } catch (e) {
      setError(e instanceof HttpError && e.status === 409 ? m.emailExists : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog isOpen={open} onClose={onClose} busy={busy} title={m.addUser} actions={<>
      <Button variant="primary" type="submit" form="add-user" isDisabled={busy}><UserPlus size={16} aria-hidden /> {m.add}</Button>
      <TextButton onPress={onClose} isDisabled={busy}>{m.cancel}</TextButton>
    </>}>
      <Form id="add-user" check={check} onValid={add} className="case-form">
        <TextField name="name" label={m.userName} value={name} onChange={setName} autoFocus maxLength={120} />
        <TextField name="email" type="email" label={m.userEmail} value={email} onChange={setEmail} maxLength={254} />
        <Checkbox name="admin" checked={admin} onChange={setAdmin}>
          {m.colAdministrator}<span className="ui-hint user-hint">{m.canOpenAdministration}</span>
        </Checkbox>
        {max !== null && counted + 1 > max
          ? <Notice icon={<AlertTriangle size={16} />}>{m.overAgreement(counted + 1, max)}</Notice>
          : <p className="caption">{m.temporaryPasswordNote}</p>}
        {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{sentence(error)}</InlineNotice>}
      </Form>
    </Dialog>
  );
}

function TemporaryDialog({ temporary, onClose }: { temporary: TemporaryPassword | null; onClose: () => void }) {
  const m = useT();
  const t = temporary;
  const text = t ? [`${m.address}: ${t.address}`, `${m.signInWith}: ${t.user.username}`, `${m.temporaryPassword}: ${t.password}`].join("\n") : "";
  const [copied, setCopied] = useState(false);
  return (
    <Dialog isOpen={t !== null} onClose={onClose} title={t ? m.passThisOn(t.user.name) : ""} actions={<>
      <Button variant="primary" autoFocus onPress={() => { setCopied(false); onClose(); }}>{m.done}</Button>
      <TextButton link onPress={async () => { try { await navigator.clipboard.writeText(text); setCopied(true); } catch { /* not allowed */ } }}>
        <Copy size={14} aria-hidden /> {copied ? m.copied : m.copy}
      </TextButton>
      <TextButton link onPress={() => window.print()}><Printer size={14} aria-hidden /> {m.print}</TextButton>
    </>}>
      {t && (
        <div className="temporary-password">
          <dl>
            <dt>{m.address}</dt><dd>{t.address}</dd>
            <dt>{m.signInWith}</dt><dd>{t.user.username}</dd>
            <dt>{m.temporaryPassword}</dt><dd className="temporary-password-value">{t.password}</dd>
          </dl>
          <p className="caption">{m.seenOnce}</p>
        </div>
      )}
    </Dialog>
  );
}

function ConfirmDialog({ confirm, me, onClose, onDone, onTemporary }: {
  confirm: Confirm | null; me: string; onClose: () => void; onDone: (lostAdministration: boolean) => void;
  onTemporary: (t: TemporaryPassword) => void;
}) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cases, setCases] = useState<AdminCase[] | null>(null);
  const [heirs, setHeirs] = useState<Record<string, string>>({});
  const [people, setPeople] = useState<Account[]>([]);
  const [goes, setGoes] = useState<AccountDeletion | null>(null);
  const c = confirm;
  useEffect(() => {
    setError(null);
    setHeirs({});
    setCases(null);
    setGoes(null);
    if (c?.kind === "delete") accountDeletion(c.user.sub).then(setGoes).catch((e: Error) => setError(e.message));
    if (c?.kind === "off") {
      listAdminCases().then((all) => setCases(all.filter((k) => k.manager === c.user.sub))).catch(() => setCases([]));
      listAccounts().then((l) => setPeople(l.users.filter((u) => u.enabled && u.sub !== c.user.sub))).catch(() => setPeople([]));
    }
  }, [c]);
  const managed = cases ?? [];
  const run = async () => {
    if (!c) return;
    setBusy(true);
    setError(null);
    try {
      const sub = c.user.sub;
      if (c.kind === "admin_on" || c.kind === "admin_off") await setAccountAdmin(sub, c.kind === "admin_on");
      if (c.kind === "password") onTemporary(await resetAccountPassword(sub));
      if (c.kind === "two_step") await resetAccountTwoStep(sub);
      if (c.kind === "sign_out") await signAccountOut(sub);
      if (c.kind === "on") await setAccountEnabled(sub, true);
      if (c.kind === "delete") await deleteAccount(sub);
      if (c.kind === "off") {
        for (const k of managed) await handOver(k.id, heirs[k.id]);
        await setAccountEnabled(sub, false);
      }
      onDone(c.kind === "admin_off" && sub === me);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const named = useMemo(() => c?.user.name ?? "", [c]);
  if (!c) return null;
  const self = c.user.sub === me;
  const text: Record<Confirm["kind"], { title: string; body?: string; action: string }> = {
    admin_on: { title: m.makeAdministrator, body: m.canOpenAdministration, action: m.makeAdministrator },
    admin_off: { title: self ? m.youNoLongerAdminTitle : m.noLongerAdminTitle(named),
                 body: self ? m.administrationClosesForYou : m.noLongerOpensAdministration(named), action: m.removeRights },
    password: { title: m.resetPasswordTitle(named), body: m.resetPasswordBody, action: m.reset },
    two_step: { title: m.resetTwoStepTitle(named), body: m.resetTwoStepBody(named), action: m.reset },
    sign_out: { title: m.signOutTitle(named), body: m.signOutBody(named), action: m.signOutEverywhere },
    off: { title: m.switchOffTitle(named), body: managed.length ? m.chooseTakeOver(managed.length) : m.conversationsStay,
           action: managed.length ? m.handOverAndSwitchOff : m.switchOff },
    on: { title: m.switchAccountOn, action: m.switchAccountOn },
    delete: { title: m.deleteAccountTitle(named), action: m.deleteAccountAction },
  };
  const waiting = (c.kind === "off" && (cases === null || managed.some((k) => !heirs[k.id]))) || (c.kind === "delete" && goes === null);
  return (
    <Dialog isOpen onClose={onClose} busy={busy} title={text[c.kind].title} actions={<>
      <TextButton onPress={onClose} isDisabled={busy}>{m.cancel}</TextButton>
      <Button variant="primary" onPress={run} isDisabled={busy || waiting}>{text[c.kind].action}</Button>
    </>}>
      {text[c.kind].body && <p>{text[c.kind].body}</p>}
      {c.kind === "delete" && goes && (
        <>
          <p>{m.deleteAccountGoes(goes.documents, goes.conversations)}</p>
          <p>{m.deleteAccountStays(goes.shared_conversations)}</p>
        </>
      )}
      {c.kind === "off" && managed.length > 0 && (
        <table className="handover-table">
          <thead><tr><th scope="col">{m.colCase}</th><th scope="col">{m.colNewManager}</th></tr></thead>
          <tbody>
            {managed.map((k) => (
              <tr key={k.id}>
                <th scope="row"><Folder size={13} aria-hidden /> <b>{k.reference}</b> {k.name}</th>
                <td>
                  <SelectField name={`heir-${k.id}`} label={m.colNewManager} hideLabel size="small" value={heirs[k.id] ?? ""}
                               placeholder={m.chooseSomeone} onChange={(v) => setHeirs({ ...heirs, [k.id]: v })}
                               options={people.map((p) => ({ id: p.sub, label: p.name }))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{sentence(error)}</InlineNotice>}
    </Dialog>
  );
}

/** An error's text as a sentence of its own: a capital first, a full stop last (VM check of 28 October, finding 11). */
const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1) + (/[.!?…]$/.test(text) ? "" : ".");
