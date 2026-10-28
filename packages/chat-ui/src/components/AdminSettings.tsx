/**
 * Administration › Settings (docs/design/admin.md, artboard 35): what the office decides, in one place. Who
 * sees a case, how long closed cases and conversations are kept, and the rates of the indicative cost. *Cases*
 * and *Usage* only show these now, with "Change in Settings".
 *
 * *Save* is active after a change. Before it saves, the gateway counts what the change would do
 * (``GET /v1/admin/cases/settings/preview``); when cases change who sees them, or saved conversations would go,
 * a confirmation says how many. Opening the office's access asks whether it applies to new cases (the existing
 * ones stay with their members) or to all of them; strictly confidential cases never change with it.
 */
import { AlertCircle, Check } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  getCaseSettings, getRates, previewCaseSettings, setCaseSettings, setRates,
  type CaseSettings, type KeepPeriod, type Rates, type SettingsPreview,
} from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { Button, Dialog, InlineNotice, NumberField, RadioList, SelectField, TextButton } from "../ui";
import { keepPeriodLabel } from "./CaseDialogs";

type Access = "office" | "members";
const PERIODS: KeepPeriod[] = ["6m", "1y", "5y", "manual"];
// As the server checks them (usage.py Rates): 0 to 10,000, at most 4 decimals.
const validRate = (v: number) => Number.isFinite(v) && v >= 0 && v <= 10_000 && Number(v.toFixed(4)) === v;

export function AdminSettings() {
  const m = useT();
  const [settings, setSettings] = useState<CaseSettings | null>(null);
  const [rates, setSavedRates] = useState<Rates | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [access, setAccess] = useState<Access>("members");
  const [applyTo, setApplyTo] = useState<"new" | "all">("new");
  const [keep, setKeep] = useState<KeepPeriod>("manual");
  const [conversations, setConversations] = useState<KeepPeriod>("manual");
  const [input, setInput] = useState(0);
  const [output, setOutput] = useState(0);
  const [currency, setCurrency] = useState("USD");
  const [confirming, setConfirming] = useState<SettingsPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const take = useCallback((s: CaseSettings | null, r: Rates | null) => {
    if (s) { setSettings(s); setAccess(s.default_access); setKeep(s.keep); setConversations(s.conversations_keep); setApplyTo("new"); }
    if (r) { setSavedRates(r); setInput(Number(r.input_per_million)); setOutput(Number(r.output_per_million)); setCurrency(r.currency); }
  }, []);
  useEffect(() => {
    getCaseSettings().then((s) => take(s, null)).catch(() => setLoadFailed(true));
    getRates().then((r) => take(null, r)).catch(() => setSavedRates(null));
  }, [take]);

  const opens = settings !== null && access === "office" && settings.default_access === "members";
  const casesChanged = settings !== null
    && (access !== settings.default_access || keep !== settings.keep || conversations !== settings.conversations_keep);
  const ratesChanged = rates !== null
    && (input !== Number(rates.input_per_million) || output !== Number(rates.output_per_million) || currency !== rates.currency);
  const ratesValid = validRate(input) && validRate(output);
  const changed = casesChanged || ratesChanged;
  const edited = <T,>(set: (v: T) => void) => (v: T) => { set(v); setSaved(false); setError(null); };

  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = casesChanged
        ? await setCaseSettings({ default_access: access, keep, conversations_keep: conversations, ...(opens ? { apply_to: applyTo } : {}) })
        : null;
      const r = ratesChanged ? await setRates({ input_per_million: String(input), output_per_million: String(output), currency }) : null;
      take(s, r);
      setConfirming(null);
      setSaved(true);
    } catch (e) {
      setConfirming(null);
      setError(m.settingsFailed((e as Error).message));
    } finally { setBusy(false); }
  };
  const save = async () => {
    if (!casesChanged) return write();
    setBusy(true);
    try {
      const p = await previewCaseSettings({ default_access: access, apply_to: opens ? applyTo : undefined, conversations_keep: conversations });
      setBusy(false);
      if (p.cases_opened || p.cases_closed || p.conversations_deleted) setConfirming(p);
      else await write();
    } catch (e) {
      setBusy(false);
      setError(m.settingsFailed((e as Error).message));
    }
  };

  const periodLabel = (p: KeepPeriod) => {
    const l = keepPeriodLabel(p, m);
    return l ? l.charAt(0).toUpperCase() + l.slice(1) : m.keepUntilDeleted;
  };
  const periods = PERIODS.map((p) => ({ id: p, label: periodLabel(p) }));

  if (loadFailed && !settings) {
    return <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{m.settingsLoadFailed}</InlineNotice>;
  }
  return (
    <div className="admin-settings">
      {settings && (
        <>
          <section aria-labelledby="who-sees">
            <h2 id="who-sees" className="label">{m.whoSeesACase}</h2>
            <RadioList label={m.whoSeesACase} name="default_access" value={access} onChange={edited((v: string) => setAccess(v as Access))}
                       choices={[{ value: "members", title: m.accessMembersOnly }, { value: "office", title: m.accessEveryone }]} />
            {opens && (
              <div className="admin-settings-apply">
                <h3 className="label">{m.applyTo}</h3>
                <RadioList label={m.applyTo} name="apply_to" value={applyTo} onChange={edited((v: string) => setApplyTo(v as "new" | "all"))}
                           choices={[{ value: "new", title: m.applyNewCases }, { value: "all", title: m.applyAllCases }]} />
              </div>
            )}
            <p className="caption">{m.changeablePerCase} {m.strictlyStays}</p>
          </section>
          <section aria-labelledby="keep-periods" className="admin-settings-row">
            <h2 id="keep-periods" className="ui-visually-hidden">{m.keepClosedCase}</h2>
            <SelectField name="keep" label={m.keepClosedCase} description={m.keepClosedHint} value={keep}
                         onChange={edited((v: string) => setKeep(v as KeepPeriod))} options={periods} />
            <SelectField name="conversations_keep" label={m.keepConversations} description={m.keepConversationsHint} value={conversations}
                         onChange={edited((v: string) => setConversations(v as KeepPeriod))} options={periods} />
          </section>
        </>
      )}
      {rates && (
        <section aria-labelledby="indicative-cost">
          <h2 id="indicative-cost" className="label">{m.indicativeCost}</h2>
          <div className="admin-settings-row">
            <NumberField name="input" label={m.rateInput} value={input} onChange={edited(setInput)} minValue={0} maxValue={10_000}
                         maxDecimals={4} size="small" className="rates-field" />
            <NumberField name="output" label={m.rateOutput} value={output} onChange={edited(setOutput)} minValue={0} maxValue={10_000}
                         maxDecimals={4} size="small" className="rates-field" />
            <SelectField name="currency" label={m.currency} value={currency} onChange={edited(setCurrency)} size="small"
                         options={["USD", "EUR", "GBP"].map((c) => ({ id: c, label: c }))} />
          </div>
          <p className="caption">{ratesValid ? m.indicativeCostHint : m.ratesInvalid}</p>
        </section>
      )}
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      <div className="admin-settings-save">
        <Button variant="primary" onPress={save} isDisabled={busy || !changed || !ratesValid}>{busy ? m.saving : m.save}</Button>
        <p className="caption">
          {saved ? <span className="status-ok"><Check size={12} aria-hidden /> {m.settingsSaved}</span>
            : settings?.updated_at ? m.settingsChangedBy(settings.updated_by, dayLabel(settings.updated_at)) : m.settingsAsProvisioned}
        </p>
      </div>
      <Dialog isOpen={confirming !== null} onClose={() => setConfirming(null)} busy={busy} title={m.saveSettingsTitle} actions={<>
        <TextButton onPress={() => setConfirming(null)} isDisabled={busy}>{m.cancel}</TextButton>
        <Button variant="primary" onPress={write} isDisabled={busy}>{busy ? m.saving : m.save}</Button>
      </>}>
        {confirming?.cases_opened ? <p>{m.casesOpened(confirming.cases_opened)}</p> : null}
        {confirming?.cases_closed ? <p>{m.casesClosed(confirming.cases_closed)}</p> : null}
        {confirming?.conversations_deleted ? <p>{m.conversationsDeleted(confirming.conversations_deleted)}</p> : null}
        {confirming?.cases_opened || confirming?.cases_closed ? <p className="caption">{m.strictlyStays}</p> : null}
      </Dialog>
    </div>
  );
}
