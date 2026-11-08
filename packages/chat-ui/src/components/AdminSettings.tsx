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
import { Check, CircleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  getCaseSettings, ME_CHANGED, getRates, previewCaseSettings, setCaseSettings, setRates,
  type CaseSettings, type KeepPeriod, type Rates, type SettingsPreview,
} from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { Button, Dialog, InlineNotice, NumberField, RadioList, Segmented, SelectField, Switch, TextField } from "../ui";
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
  const [twoStep, setTwoStep] = useState(false);
  const [officeName, setOfficeName] = useState("");
  const [input, setInput] = useState(0);
  const [output, setOutput] = useState(0);
  const [currency, setCurrency] = useState("USD");
  const [confirming, setConfirming] = useState<SettingsPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const take = useCallback((s: CaseSettings | null, r: Rates | null) => {
    if (s) { setSettings(s); setAccess(s.default_access); setKeep(s.keep); setConversations(s.conversations_keep); setTwoStep(s.two_step); setApplyTo("new");
             setOfficeName(s.office_name ?? ""); }
    if (r) { setSavedRates(r); setInput(Number(r.input_per_million)); setOutput(Number(r.output_per_million)); setCurrency(r.currency);
             setTypedInput(null); setTypedOutput(null); }
  }, []);
  useEffect(() => {
    getCaseSettings().then((s) => take(s, null)).catch(() => setLoadFailed(true));
    getRates().then((r) => take(null, r)).catch(() => setSavedRates(null));
  }, [take]);

  const opens = settings !== null && access === "office" && settings.default_access === "members";
  const casesChanged = settings !== null
    && (access !== settings.default_access || keep !== settings.keep || conversations !== settings.conversations_keep
        || twoStep !== settings.two_step || officeName.trim() !== (settings.office_name ?? ""));
  const twoStepChanged = settings !== null && twoStep !== settings.two_step;
  // A price as typed counts at once, before its field commits it on blur (board B08: Save stayed grey after typing
  // a price and clicking Save, because a click on a disabled button doesn't take the focus from the field).
  const [typedInput, setTypedInput] = useState<number | null>(null);
  const [typedOutput, setTypedOutput] = useState<number | null>(null);
  const inputNow = typedInput ?? input;
  const outputNow = typedOutput ?? output;
  const ratesChanged = rates !== null
    && (inputNow !== Number(rates.input_per_million) || outputNow !== Number(rates.output_per_million) || currency !== rates.currency);
  const ratesValid = validRate(inputNow) && validRate(outputNow);
  const changed = casesChanged || ratesChanged;
  const edited = <T,>(set: (v: T) => void) => (v: T) => { set(v); setSaved(false); setError(null); };
  // null is the field committing (or text that isn't a number): it doesn't undo "Saved."
  const typing = (set: (v: number | null) => void) => (v: number | null) => { set(v); if (v !== null) { setSaved(false); setError(null); } };

  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = casesChanged
        ? await setCaseSettings({ default_access: access, keep, conversations_keep: conversations, two_step: twoStep, office_name: officeName.trim(),
                                  ...(opens ? { apply_to: applyTo } : {}) })
        : null;
      if (s && s.office_name !== (settings?.office_name ?? "")) window.dispatchEvent(new Event(ME_CHANGED));
      const r = ratesChanged ? await setRates({ input_per_million: String(inputNow), output_per_million: String(outputNow), currency }) : null;
      take(s, r);
      setConfirming(null);
      setSaved(true);
    } catch (e) {
      setConfirming(null);
      setError(m.settingsFailed((e as Error).message));
      // two-step is the office's whole sign-in: refused, the switch shows the setting as it stands (finding 13)
      if (settings) setTwoStep(settings.two_step);
    } finally { setBusy(false); }
  };
  const save = async () => {
    if (!casesChanged) return write();
    setBusy(true);
    try {
      const p = await previewCaseSettings({ default_access: access, apply_to: opens ? applyTo : undefined, conversations_keep: conversations });
      setBusy(false);
      if (p.cases_opened || p.cases_closed || p.conversations_deleted || twoStepChanged) setConfirming(p);
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
    return <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{m.settingsLoadFailed}</InlineNotice>;
  }
  return (
    <div className="admin-settings">
      {settings && (
        <>
          {/* Sections as on board B08: a heading in small capitals per section, the fields under it with their
              own labels in bold. The office's name is new since the board (G01, G04: shown after each person's
              name in the column and in the account menu), in a section of its own at the top. */}
          <section aria-labelledby="office" className="admin-settings-section">
            <h2 id="office" className="label">{m.adminOffice}</h2>
            <div className="office-name-field">
              <TextField label={m.officeName} name="office_name" value={officeName} onChange={edited(setOfficeName)} maxLength={120}
                         description={m.officeNameHint} />
            </div>
          </section>
          <section aria-labelledby="cases-settings" className="admin-settings-section">
            <h2 id="cases-settings" className="label">{m.cases}</h2>
            <div className="admin-settings-item">
              <h3 className="ui-label" aria-hidden>{m.whoSeesACase}</h3>
              <RadioList label={m.whoSeesACase} name="default_access" value={access} onChange={edited((v: string) => setAccess(v as Access))}
                         choices={[{ value: "members", title: m.accessMembersOnly }, { value: "office", title: m.accessEveryone }]} />
              {opens && (
                <div className="admin-settings-apply">
                  <Segmented label={m.applyTo} value={applyTo} onChange={edited((v: string) => setApplyTo(v as "new" | "all"))}
                             options={[{ value: "new", label: m.applyNewCases }, { value: "all", label: m.applyAllCases }]} />
                </div>
              )}
              <p className="caption">{m.changeablePerCase} {m.strictlyStays}</p>
            </div>
            {/* the keep periods as segmented buttons, each under its own label (board B08) */}
            <div className="admin-settings-item">
              <h3 className="ui-label" aria-hidden>{m.keepClosedCase}</h3>
              <Segmented label={m.keepClosedCase} description={m.keepClosedHint} value={keep}
                         onChange={edited((v: string) => setKeep(v as KeepPeriod))} options={periods.map((p) => ({ value: p.id, label: p.label }))} />
            </div>
            <div className="admin-settings-item">
              <h3 className="ui-label" aria-hidden>{m.keepConversations}</h3>
              <Segmented label={m.keepConversations} description={m.keepConversationsHint} value={conversations}
                         onChange={edited((v: string) => setConversations(v as KeepPeriod))} options={periods.map((p) => ({ value: p.id, label: p.label }))} />
            </div>
          </section>
          <section aria-labelledby="two-step" className="admin-settings-section">
            <h2 id="two-step" className="label">{m.twoStepHeading}</h2>
            <Switch label={m.twoStepEveryone} checked={twoStep} onChange={edited(setTwoStep)} />
            <p className="caption">{m.twoStepHint}</p>
          </section>
        </>
      )}
      {rates && (
        <section aria-labelledby="indicative-cost" className="admin-settings-section">
          <h2 id="indicative-cost" className="label">{m.indicativeCost}</h2>
          <div className="admin-settings-row">
            <NumberField name="input" label={m.rateInput} value={input} onChange={edited(setInput)} onTyped={typing(setTypedInput)} minValue={0} maxValue={10_000}
                         maxDecimals={4} size="small" className="rates-field" />
            <NumberField name="output" label={m.rateOutput} value={output} onChange={edited(setOutput)} onTyped={typing(setTypedOutput)} minValue={0} maxValue={10_000}
                         maxDecimals={4} size="small" className="rates-field" />
            <SelectField name="currency" label={m.currency} value={currency} onChange={edited(setCurrency)} size="small"
                         options={["USD", "EUR", "GBP"].map((c) => ({ id: c, label: c }))} />
          </div>
          <p className="caption">{ratesValid ? m.indicativeCostHint : m.ratesInvalid}</p>
        </section>
      )}
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      <div className="admin-settings-save">
        <Button variant="primary" onPress={save} isDisabled={busy || !changed || !ratesValid}>{busy ? m.saving : m.save}</Button>
        {/* Cancel: back to what is saved (board B08) */}
        {changed && !busy && <Button variant="quiet" onPress={() => { take(settings, rates); setError(null); }}>{m.cancel}</Button>}
        <p className="caption">
          {saved ? <span className="status-ok"><Check size={12} aria-hidden /> {m.settingsSaved}</span>
            : settings?.updated_at ? m.settingsChangedBy(settings.updated_by, dayLabel(settings.updated_at)) : m.settingsAsProvisioned}
        </p>
      </div>
      <Dialog isOpen={confirming !== null} onClose={() => setConfirming(null)} busy={busy} kind="confirmation" title={m.saveSettingsTitle}
              cancel={{ label: m.cancel }} primary={{ label: m.save, onPress: () => void write(), busyLabel: m.saving }}>
        {confirming && <SettingsConsequences preview={confirming} />}
        {twoStepChanged ? <p>{twoStep ? m.twoStepTurnsOn : m.twoStepTurnsOff}</p> : null}
      </Dialog>
    </div>
  );
}

/** What saving the office's case settings does to cases and conversations that exist, as the gateway previewed it:
 *  the confirmation's text, here and under Administration › Cases (board B05: one setting, two places). */
export function SettingsConsequences({ preview }: { preview: SettingsPreview }) {
  const m = useT();
  return <>
    {preview.cases_opened ? <p>{m.casesOpened(preview.cases_opened)}</p> : null}
    {preview.cases_closed ? <p>{m.casesClosed(preview.cases_closed)}</p> : null}
    {preview.conversations_deleted ? <p>{m.conversationsDeleted(preview.conversations_deleted)}</p> : null}
    {preview.cases_opened || preview.cases_closed ? <p className="caption">{m.strictlyStays}</p> : null}
  </>;
}

/** The keep periods in their order, labelled as everywhere: "6 months", …, "Until deleted by hand". */
export function keepPeriodOptions(m: ReturnType<typeof useT>) {
  return PERIODS.map((p) => {
    const l = keepPeriodLabel(p, m);
    return { id: p, label: l ? l.charAt(0).toUpperCase() + l.slice(1) : m.keepUntilDeleted };
  });
}
