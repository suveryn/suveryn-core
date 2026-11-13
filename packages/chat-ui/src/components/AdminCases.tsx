/**
 * Cases, stage 4 (suveryn-tracker#10): the administrator's case pages.
 *
 * The office's settings for cases (who sees a case, how long closed cases and conversations are kept), shown
 * here and changed in Settings (docs/design/admin.md); every case on the appliance with who
 * manages it, so a case can be handed over before an account goes (decision 6); and what is due
 * for deletion. Nothing from inside a case: an administrator who isn't a member reads no documents.
 */
import { ArrowRightLeft, Check, CircleAlert, Folder, FolderKey, Lock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCaseSettings, handOver, listAdminCases, previewCaseSettings, searchUsers, setCaseSettings,
  type AdminCase, type CaseSettings, type KeepPeriod, type Person, type SettingsPreview,
} from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { Button, ComboBoxField, Dialog, InlineNotice, SelectField, TextButton } from "../ui";
import { keepPeriodOptions, SettingsConsequences } from "./AdminSettings";
import { isDue, onDay } from "./CaseState";

export function AdminCases() {
  const m = useT();
  const [cases, setCases] = useState<AdminCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [handing, setHanding] = useState<AdminCase | null>(null);
  const refresh = useCallback(async () => {
    try { setCases(await listAdminCases()); setError(null); } catch (e) { setError(m.casesLoadFailed({ why: (e as Error).message })); }
  }, [m]);
  useEffect(() => { refresh(); }, [refresh]);
  const due = (cases ?? []).filter((c) => isDue(c));
  return (
    <>
      <p className="view-intro">{m.adminCasesIntro}</p>
      <CaseSettingsEditor onSaved={refresh} />
      {due.length > 0 && (
        <InlineNotice icon={<CircleAlert size={14} />}>
          {m.casesDue({ n: due.length })}: {due.map((c) => c.reference).join(", ")}
        </InlineNotice>
      )}
      <h2 className="label">{m.adminCases}</h2>
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      {cases && cases.length === 0 && <p className="caption">{m.noCasesYet}</p>}
      {cases && cases.length > 0 && (
        <div className="table-wrap cases-table-wrap">
          <table className="usage-table cases-table">
            <thead><tr>
              <th scope="col">{m.colReference}</th><th scope="col">{m.colName}</th><th scope="col">{m.colState}</th>
              <th scope="col">{m.colManager}</th><th scope="col" className="cases-num">{m.colMembers}</th><th scope="col">{m.colFate}</th><th scope="col"></th>
            </tr></thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} data-due={isDue(c) || undefined}>
                  <th scope="row">{c.state === "closed" ? <Lock size={12} aria-hidden /> : <Folder size={12} aria-hidden />} {c.reference}</th>
                  <td className="cases-name" title={c.name}>{c.name || (c.confidential ? <span className="overview-dim">{m.strictlyConfidential}</span> : "")}</td>
                  <td><span className="overview-status-cell">{c.state === "closed" ? `${m.caseClosed} ${dayLabel(c.closed_at!)}` : m.stateOpen}
                    {/* §11: the violet outline label, as in Dossiers (board B05) */}
                    {c.confidential && <span className="overview-label"><FolderKey size={12} aria-hidden /> {m.strictlyConfidential}</span>}</span></td>
                  <td title={c.manager_username}>{c.manager_name || c.manager_username || c.manager}</td>
                  <td className="cases-num">{c.members}</td>
                  <td className="cases-fate">{c.state !== "closed" ? "" : isDue(c) ? <b>{fateShort(c, m)}</b> : fateShort(c, m)}</td>
                  <td><TextButton link onPress={() => setHanding(c)}><ArrowRightLeft size={12} aria-hidden /> {m.handOver}</TextButton></td>
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

/** Under "Deleted" (board B05), short: "on 1 Nov 2026" when it is due, "kept until 1 Mar 2027" before that,
 *  "kept" for a case marked to keep, nothing when the office keeps cases until they are deleted by hand. */
function fateShort(c: AdminCase, m: ReturnType<typeof useT>): string {
  if (c.keep) return m.keptMarked;
  if (c.keep_until === null) return "";
  return isDue(c) ? m.deletedOnShort({ day: onDay(c.keep_until) }) : m.keptUntilShort({ day: onDay(c.keep_until) });
}

/** The office's three settings for cases, changed here as on Administration › Settings (board B05: one setting
 *  shown in two places), with the same confirmation when a change touches cases or conversations that exist. */
function CaseSettingsEditor({ onSaved }: { onSaved: () => void }) {
  const m = useT();
  const [settings, setSettings] = useState<CaseSettings | null>(null);
  const [access, setAccess] = useState<"office" | "members">("members");
  const [applyTo, setApplyTo] = useState<"new" | "all">("new");
  const [keep, setKeep] = useState<KeepPeriod>("manual");
  const [conversations, setConversations] = useState<KeepPeriod>("manual");
  const [confirming, setConfirming] = useState<SettingsPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const take = (s: CaseSettings) => { setSettings(s); setAccess(s.default_access); setKeep(s.keep); setConversations(s.conversations_keep); setApplyTo("new"); };
  useEffect(() => { getCaseSettings().then(take).catch(() => setSettings(null)); }, []);
  if (!settings) return null;

  const opens = access === "office" && settings.default_access === "members";
  const changed = access !== settings.default_access || keep !== settings.keep || conversations !== settings.conversations_keep;
  const edited = <T,>(set: (v: T) => void) => (v: T) => { set(v); setSaved(false); setError(null); };
  const body = { default_access: access, keep, conversations_keep: conversations, two_step: settings.two_step,
                 ...(opens ? { apply_to: applyTo } : {}) };
  const write = async () => {
    setBusy(true);
    setError(null);
    try { take(await setCaseSettings(body)); setConfirming(null); setSaved(true); onSaved(); }
    catch (e) { setConfirming(null); setError(m.settingsFailed({ why: (e as Error).message })); }
    finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try {
      const p = await previewCaseSettings({ default_access: access, apply_to: opens ? applyTo : undefined, conversations_keep: conversations });
      setBusy(false);
      if (p.cases_opened || p.cases_closed || p.conversations_deleted) setConfirming(p);
      else await write();
    } catch (e) { setBusy(false); setError(m.settingsFailed({ why: (e as Error).message })); }
  };
  const periods = keepPeriodOptions(m);
  return (
    <section aria-labelledby="case-settings" className="admin-case-settings">
      <h2 id="case-settings" className="ui-visually-hidden">{m.adminCases}</h2>
      <div className="admin-settings-row">
        <SelectField name="default_access" label={m.whoSeesACase} size="small" value={access}
                     onChange={edited((v: string) => setAccess(v as "office" | "members"))}
                     options={[{ id: "office", label: m.accessEveryone }, { id: "members", label: m.accessMembersOnly }]} />
        {opens && <SelectField name="apply_to" label={m.applyTo} size="small" value={applyTo}
                               onChange={edited((v: string) => setApplyTo(v as "new" | "all"))}
                               options={[{ id: "new", label: m.applyNewCases }, { id: "all", label: m.applyAllCases }]} />}
        <SelectField name="keep" label={m.keepClosedCase} size="small" value={keep} onChange={edited((v: string) => setKeep(v as KeepPeriod))} options={periods} />
        <SelectField name="conversations_keep" label={m.keepConversations} size="small" value={conversations}
                     onChange={edited((v: string) => setConversations(v as KeepPeriod))} options={periods} />
      </div>
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      <div className="admin-settings-save">
        <Button variant="primary" size="small" onPress={() => void save()} isDisabled={busy || !changed}>{busy ? m.saving : m.save}</Button>
        <p className="caption">
          {saved ? <span className="status-ok"><Check size={12} aria-hidden /> {m.settingsSaved}</span>
            : settings.updated_at ? m.settingsChangedBy({ who: settings.updated_by, day: dayLabel(settings.updated_at) }) : m.settingsAsProvisioned}
        </p>
      </div>
      <Dialog isOpen={confirming !== null} onClose={() => setConfirming(null)} busy={busy} kind="confirmation" title={m.saveSettingsTitle}
              cancel={{ label: m.cancel }} primary={{ label: m.save, onPress: () => void write(), busyLabel: m.saving }}>
        {confirming && <SettingsConsequences preview={confirming} />}
      </Dialog>
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
    try { await handOver(kase.id, chosen.sub); onDone(); } catch (e) { setError(m.handOverFailed({ why: (e as Error).message })); } finally { setBusy(false); }
  };
  return (
    <Dialog isOpen={open} onClose={onClose} busy={busy} kind="confirmation" title={m.handOverTo({ reference: kase?.reference ?? "" })} error={error}
            cancel={{ label: m.cancel }} primary={{ label: m.handOver, onPress: () => void confirm(), disabled: !chosen, busyLabel: m.handingOver }}>
      <p>{m.handOverHint}</p>
      <ComboBoxField name="colleague" label={m.newManager} value={query} onChange={setQuery}
                     options={candidates.map((p) => ({ id: p.sub, label: labelOf(p) }))} />
    </Dialog>
  );
}
