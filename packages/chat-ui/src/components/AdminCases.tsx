/**
 * Cases, stage 4 (suveryn-tracker#10): the administrator's case pages.
 *
 * The office's two settings for cases (who sees a new case, how long closed cases are kept), as
 * provisioned until an administrator changes them here; every case on the appliance with who
 * manages it, so a case can be handed over before an account goes (decision 6); and what is due
 * for deletion. Nothing from inside a case: an administrator who isn't a member reads no documents.
 */
import { AlertCircle, ArrowRightLeft, Check, Lock, Folder } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCaseSettings, handOver, listAdminCases, searchUsers, setCaseSettings,
  type AdminCase, type CaseSettings, type KeepPeriod, type Person,
} from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { Button, ComboBoxField, Dialog, InlineNotice, SelectField, TextButton } from "../ui";
import { keepPeriodLabel } from "./CaseDialogs";
import { fateLabel, isDue } from "./CaseState";

export function AdminCases() {
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
      <SettingsForm />
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
                  <td>{c.state === "closed" ? fateLabel(c, m) : ""}</td>
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

function SettingsForm() {
  const m = useT();
  const [settings, setSettings] = useState<CaseSettings | null>(null);
  const [access, setAccess] = useState<"office" | "members">("members");
  const [keep, setKeep] = useState<KeepPeriod>("manual");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getCaseSettings().then((s) => { setSettings(s); setAccess(s.default_access); setKeep(s.keep); })
      .catch((e: Error) => setError(m.settingsFailed(e.message)));
  }, [m]);
  const changed = settings !== null && (access !== settings.default_access || keep !== settings.keep);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await setCaseSettings({ default_access: access, keep });
      setSettings(s);
      setSaved(true);
    } catch (e) { setError(m.settingsFailed((e as Error).message)); } finally { setBusy(false); }
  };
  const keepLabel = (p: KeepPeriod) => (p === "manual" ? m.keepManual : m.keepFor(keepPeriodLabel(p, m) ?? p));
  return (
    <section className="case-settings" aria-labelledby="case-settings-title">
      <h2 id="case-settings-title" className="label">{m.caseSettingsTitle}</h2>
      <div className="case-settings-row">
        <SelectField name="default_access" label={m.settingDefaultAccess} value={access} size="small"
                     onChange={(v) => { setAccess(v as "office" | "members"); setSaved(false); }}
                     options={[{ id: "members", label: m.accessMembers }, { id: "office", label: m.accessOffice }]} />
        <SelectField name="keep" label={m.settingKeep} value={keep} size="small"
                     onChange={(v) => { setKeep(v as KeepPeriod); setSaved(false); }}
                     options={(["6m", "1y", "5y", "manual"] as KeepPeriod[]).map((p) => ({ id: p, label: keepLabel(p) }))} />
        <Button size="small" onPress={save} isDisabled={busy || !changed}>{busy ? m.saving : m.save}</Button>
      </div>
      <p className="caption">
        {saved ? <><Check size={12} aria-hidden /> {m.settingsSaved}</> :
         settings?.updated_at ? m.settingsChangedBy(settings.updated_by, dayLabel(settings.updated_at)) : m.settingsAsProvisioned}
      </p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </section>
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
