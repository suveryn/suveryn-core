/**
 * Cases, stage 4 (suveryn-tracker#10): the administrator's case pages.
 *
 * The office's settings for cases (who sees a case, how long closed cases and conversations are kept), shown
 * here and changed in Settings (docs/design/admin.md); every case on the appliance with who
 * manages it, so a case can be handed over before an account goes (decision 6); and what is due
 * for deletion. Nothing from inside a case: an administrator who isn't a member reads no documents.
 */
import { AlertCircle, ArrowRightLeft, Folder, Lock, MessageSquare, Users } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCaseSettings, handOver, listAdminCases, searchUsers,
  type AdminCase, type CaseSettings, type KeepPeriod, type Person,
} from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { Button, ComboBoxField, Dialog, Facts, InlineNotice, TextButton } from "../ui";
import type { AdminPage } from "./Admin";
import { keepPeriodLabel } from "./CaseDialogs";
import { fateLabel, isDue } from "./CaseState";

export function AdminCases({ onOpen }: { onOpen: (page: AdminPage) => void }) {
  const m = useT();
  const [cases, setCases] = useState<AdminCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [handing, setHanding] = useState<AdminCase | null>(null);
  const refresh = useCallback(async () => {
    try { setCases(await listAdminCases()); setError(null); } catch (e) { setError(m.casesLoadFailed((e as Error).message)); }
  }, [m]);
  useEffect(() => { refresh(); }, [refresh]);
  const due = (cases ?? []).filter((c) => isDue(c));
  return (
    <>
      <p className="view-intro">{m.adminCasesIntro}</p>
      <SettingsFacts onOpen={onOpen} />
      {due.length > 0 && (
        <InlineNotice icon={<AlertCircle size={14} />}>
          {m.casesDue(due.length)}: {due.map((c) => c.reference).join(", ")}
        </InlineNotice>
      )}
      <h2 className="label">{m.adminCases}</h2>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      {cases && cases.length === 0 && <p className="caption">{m.noCasesYet}</p>}
      {cases && cases.length > 0 && (
        <div className="table-wrap">
          <table className="usage-table cases-table">
            <thead><tr>
              <th scope="col">{m.colReference}</th><th scope="col">{m.colName}</th><th scope="col">{m.colState}</th>
              <th scope="col">{m.colManager}</th><th scope="col">{m.colMembers}</th><th scope="col">{m.colFate}</th><th scope="col"></th>
            </tr></thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} data-due={isDue(c) || undefined}>
                  <th scope="row">{c.state === "closed" ? <Lock size={12} aria-hidden /> : <Folder size={12} aria-hidden />} {c.reference}</th>
                  <td className="cases-name" title={c.name}>{c.name}</td>
                  <td>{c.state === "closed" ? `${m.caseClosed} ${dayLabel(c.closed_at!)}` : m.stateOpen}</td>
                  <td title={c.manager_username}>{c.manager_name || c.manager_username || c.manager}</td>
                  <td>{c.members}</td>
                  <td>{c.state !== "closed" ? "" : isDue(c) ? <b>{fateLabel(c, m)}</b> : fateLabel(c, m)}</td>
                  <td><TextButton onPress={() => setHanding(c)}><ArrowRightLeft size={12} aria-hidden /> {m.handOver}</TextButton></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <HandOverDialog kase={handing} onClose={() => setHanding(null)} onDone={() => { setHanding(null); refresh(); }} />
    </>
  );
}

/** The office's settings for cases as they apply now; changed in Administration › Settings. */
function SettingsFacts({ onOpen }: { onOpen: (page: AdminPage) => void }) {
  const m = useT();
  const [settings, setSettings] = useState<CaseSettings | null>(null);
  useEffect(() => { getCaseSettings().then(setSettings).catch(() => setSettings(null)); }, []);
  if (!settings) return null;
  const period = (p: KeepPeriod) => {
    const l = keepPeriodLabel(p, m);
    return l ? l.charAt(0).toUpperCase() + l.slice(1) : m.keepUntilDeleted;
  };
  return (
    <Facts facts={[
      { icon: <Users size={16} />, label: m.whoSeesACase, value: settings.default_access === "office" ? m.accessEveryone : m.accessMembersOnly },
      { icon: <Lock size={16} />, label: m.keepClosedCase, value: period(settings.keep) },
      { icon: <MessageSquare size={16} />, label: m.keepConversations, value: period(settings.conversations_keep) },
    ]} footer={<TextButton onPress={() => onOpen("settings")}>{m.changeInSettings}</TextButton>} />
  );
}

/** Hand a case over to one of the office's accounts, searched as you type (as MembersDialog does). */
function HandOverDialog({ kase, onClose, onDone }: { kase: AdminCase | null; onClose: () => void; onDone: () => void }) {
  const m = useT();
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Person[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const open = kase !== null;
  useEffect(() => { if (open) { setQuery(""); setFound([]); setError(null); } }, [open]);
  const labelOf = (p: Person) => (p.name === p.username ? p.name : `${p.name} (${p.username})`);
  const typed = query.trim();
  const candidates = found.filter((p) => p.sub !== kase?.manager);
  const chosen = candidates.find((p) => labelOf(p) === typed || p.username === typed || p.name === typed);
  useEffect(() => {
    if (!open || (typed && found.some((p) => labelOf(p) === typed))) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { setFound(await searchUsers(typed)); } catch { setFound([]); }
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [typed, open]);  // eslint-disable-line react-hooks/exhaustive-deps -- `found` is what the search sets
  const confirm = async () => {
    if (!kase || !chosen) return;
    setBusy(true);
    setError(null);
    try { await handOver(kase.id, chosen.sub); onDone(); } catch (e) { setError(m.handOverFailed((e as Error).message)); } finally { setBusy(false); }
  };
  return (
    <Dialog isOpen={open} onClose={onClose} busy={busy} title={m.handOverTo(kase?.reference ?? "")} actions={<>
      <TextButton onPress={onClose} isDisabled={busy}>{m.cancel}</TextButton>
      <Button variant="primary" onPress={confirm} isDisabled={busy || !chosen}><ArrowRightLeft size={16} aria-hidden /> {m.handOver}</Button>
    </>}>
      <p>{m.handOverHint}</p>
      <ComboBoxField name="colleague" label={m.newManager} value={query} onChange={setQuery}
                     options={candidates.map((p) => ({ id: p.sub, label: labelOf(p) }))} />
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}
