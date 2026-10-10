/**
 * Token usage views (suveryn-tracker#7, development context §5.3):
 * - UsageView: the signed-in user's own usage (never a colleague's);
 * - AdminView: administrators only (realm role suveryn-admin, enforced by the gateway): the
 *   office's usage in total and per user, with a notional cloud cost and its editable rates.
 * Both pick a period (last hour, day, week, month, or whole local days) and show the totals and a
 * bar chart. Counts only: the server never stores or returns text. Informational: nothing limits anyone.
 */
import { ArrowLeft, BarChart3, Check, Shield } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getMyUsage, getOfficeUsage, setRates, type OfficeUsageReport, type UsageReport, type UsageTotals } from "../api";
import { locale, useT } from "../i18n";
import { bucketLabel, compact, money, PRESETS, rangeFor, whole, type Preset } from "../lib/usage";

function useReport<R>(load: (start: Date, end?: Date) => Promise<R>) {
  const [preset, setPreset] = useState<Preset>("day");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [report, setReport] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    const r = rangeFor(preset, new Date(), from, to);
    if (!r) return;
    try { setReport(await load(r.start, r.end)); setError(null); } catch (e) { setError((e as Error).message); }
  }, [preset, from, to, load]);
  useEffect(() => { refresh(); }, [refresh]);
  return { preset, setPreset, from, setFrom, to, setTo, report, error, refresh };
}

function RangePicker({ preset, setPreset, from, setFrom, to, setTo }: {
  preset: Preset; setPreset: (p: Preset) => void; from: string; setFrom: (v: string) => void; to: string; setTo: (v: string) => void;
}) {
  const m = useT();
  const name: Record<Preset, string> = { hour: m.presetHour, day: m.presetDay, week: m.presetWeek, month: m.presetMonth, custom: m.presetCustom };
  return (
    <div className="range">
      <div className="segmented" role="radiogroup" aria-label={m.rangeLabel}>
        {PRESETS.map((p) => (
          <button key={p} type="button" role="radio" aria-checked={preset === p} className={preset === p ? "on" : ""}
                  onClick={() => setPreset(p)}>{name[p]}</button>
        ))}
      </div>
      {preset === "custom" && (
        <span className="range-dates">
          <label>{m.from} <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label>{m.to} <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></label>
        </span>
      )}
    </div>
  );
}

function Totals({ totals, extra }: { totals: UsageTotals; extra?: { label: string; value: string } }) {
  const m = useT();
  const cells = [[m.requests, whole(totals.requests)], [m.inputTokens, whole(totals.prompt_tokens)],
                 [m.outputTokens, whole(totals.completion_tokens)], [m.totalTokens, whole(totals.total_tokens)],
                 ...(extra ? [[extra.label, extra.value]] : [])];
  return (
    <dl className="totals">
      {cells.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
  );
}

function Chart({ report }: { report: UsageReport }) {
  const m = useT();
  const max = Math.max(1, ...report.series.map((b) => b.total_tokens));
  return (
    <figure className="chart" aria-label={m.chartLabel(whole(report.totals.total_tokens), m.stepName(report.step))}>
      <div className="bars">
        {report.series.map((b) => (
          <span key={b.start} className="bar" title={`${bucketLabel(b.start, report.step)}: ${whole(b.total_tokens)}`}>
            <i style={{ height: `${(b.total_tokens / max) * 100}%` }} />
          </span>
        ))}
      </div>
      {report.series.length > 0 && (
        <figcaption className="caption">
          <span>{bucketLabel(report.series[0].start, report.step)}</span>
          <span>{m.stepName(report.step)}</span>
          <span>{bucketLabel(report.series[report.series.length - 1].start, report.step)}</span>
        </figcaption>
      )}
    </figure>
  );
}

function ByKind({ report }: { report: UsageReport }) {
  const m = useT();
  const kinds = Object.entries(report.by_kind);
  if (kinds.length < 2) return null;
  return <p className="caption">{kinds.map(([k, v]) => `${m.kind(k)}: ${compact(v.total_tokens)}`).join(" · ")}</p>;
}

function Header({ icon, title, onBack }: { icon: React.ReactNode; title: string; onBack: () => void }) {
  const m = useT();
  return (
    <header className="view-head">
      <button type="button" className="link" onClick={onBack}><ArrowLeft size={14} aria-hidden /> {m.backToChat}</button>
      <h1>{icon} {title}</h1>
    </header>
  );
}

/** The signed-in user's own usage. */
export function UsageView({ onBack }: { onBack: () => void }) {
  const m = useT();
  const r = useReport(getMyUsage);
  return (
    <section className="view">
      <Header icon={<BarChart3 size={18} aria-hidden />} title={m.yourUsage} onBack={onBack} />
      <p className="view-intro">{m.usageIntro}</p>
      <RangePicker {...r} />
      {r.error && <p className="notice notice-error" role="alert">{m.usageUnavailable(r.error)}</p>}
      {r.report && (r.report.totals.requests === 0 ? <p className="caption">{m.noUsage}</p> : (
        <>
          <Totals totals={r.report.totals} />
          <Chart report={r.report} />
          <ByKind report={r.report} />
        </>
      ))}
    </section>
  );
}

/** Administrators: the office's usage, per user, with the notional cloud cost and its rates. */
export function AdminView({ onBack }: { onBack: () => void }) {
  const m = useT();
  const r = useReport(getOfficeUsage);
  const report = r.report as OfficeUsageReport | null;
  return (
    <section className="view">
      <Header icon={<Shield size={18} aria-hidden />} title={m.administration} onBack={onBack} />
      <nav className="tabs" aria-label={m.administration}><span className="tab on" aria-current="page">{m.adminUsage}</span></nav>
      <p className="view-intro">{m.adminIntro}</p>
      <RangePicker {...r} />
      {r.error && <p className="notice notice-error" role="alert">{m.usageUnavailable(r.error)}</p>}
      {report && (
        <>
          <h2 className="label">{m.officeUsage}</h2>
          <Totals totals={report.totals} extra={{ label: m.notionalCost, value: money(report.cost, report.rates.currency) }} />
          <p className="caption">{m.costExplain(money(report.cost, report.rates.currency),
            money(report.rates.input_per_million, report.rates.currency), money(report.rates.output_per_million, report.rates.currency))}</p>
          {report.totals.requests === 0 ? <p className="caption">{m.noUsage}</p> : (
            <>
              <Chart report={report} />
              <ByKind report={report} />
              <h2 className="label">{m.perUser}</h2>
              <div className="table-wrap">
                <table className="usage-table">
                  <thead><tr><th scope="col">{m.user}</th><th scope="col">{m.requests}</th><th scope="col">{m.inputTokens}</th>
                    <th scope="col">{m.outputTokens}</th><th scope="col">{m.totalTokens}</th><th scope="col">{m.notionalCost}</th></tr></thead>
                  <tbody>
                    {report.per_user.map((u) => (
                      <tr key={u.user_id}>
                        <th scope="row" title={u.username ?? u.user_id}>{u.name ?? u.username ?? m.unknownUser}</th>
                        <td>{whole(u.totals.requests)}</td><td>{whole(u.totals.prompt_tokens)}</td>
                        <td>{whole(u.totals.completion_tokens)}</td><td>{whole(u.totals.total_tokens)}</td>
                        <td>{u.cost !== null ? money(u.cost, report.rates.currency) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <RatesForm report={report} onSaved={r.refresh} />
        </>
      )}
    </section>
  );
}

function RatesForm({ report, onSaved }: { report: OfficeUsageReport; onSaved: () => void }) {
  const m = useT();
  const plain = (v: string) => String(Number(v)); // "3.0000" from the server shows as "3"
  const [input, setInput] = useState(plain(report.rates.input_per_million));
  const [output, setOutput] = useState(plain(report.rates.output_per_million));
  const [currency, setCurrency] = useState(report.rates.currency);
  const [state, setState] = useState<"idle" | "saved" | string>("idle");
  const valid = [input, output].every((v) => v !== "" && Number(v) >= 0);
  const save = async () => {
    if (!valid) { setState(m.ratesInvalid); return; }
    try { await setRates({ input_per_million: input, output_per_million: output, currency }); setState("saved"); onSaved(); }
    catch (e) { setState((e as Error).message); }
  };
  const changed = report.rates.updated_by && report.rates.updated_at;
  return (
    <form className="rates" onSubmit={(e) => { e.preventDefault(); save(); }}>
      <h2 className="label">{m.rates}</h2>
      <label>{m.rateInput}<input type="number" min="0" step="0.01" value={input} onChange={(e) => { setInput(e.target.value); setState("idle"); }} /></label>
      <label>{m.rateOutput}<input type="number" min="0" step="0.01" value={output} onChange={(e) => { setOutput(e.target.value); setState("idle"); }} /></label>
      <label>{m.currency}
        <select value={currency} onChange={(e) => { setCurrency(e.target.value); setState("idle"); }}>
          {["USD", "EUR", "GBP"].map((c) => <option key={c}>{c}</option>)}
        </select>
      </label>
      <button type="submit" className="button-secondary">
        {state === "saved" ? <><Check size={14} aria-hidden /> {m.saved}</> : m.save}
      </button>
      {state !== "idle" && state !== "saved" && <p className="notice notice-error" role="alert">{state}</p>}
      <p className="caption">{changed ? m.ratesChanged(report.rates.updated_by!, new Date(report.rates.updated_at!).toLocaleDateString(locale(), { dateStyle: "long" })) : m.ratesDefault}</p>
    </form>
  );
}
