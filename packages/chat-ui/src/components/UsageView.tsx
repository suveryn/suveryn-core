/**
 * Token usage views (suveryn-tracker#7, development context §5.3):
 * - UsageView: the signed-in user's own usage (never a colleague's);
 * - AdminView: administrators only (realm role suveryn-admin, enforced by the gateway): the
 *   office's usage in total and per user, with a notional cloud cost and its editable rates.
 * Both pick a period (last hour, day, week, month, or whole local days) and show the totals and a
 * chart of input and output tokens (src/ui/charts.tsx, suveryn-tracker#46). Counts only: the server
 * never stores or returns text. Informational: nothing limits anyone.
 */
import { AlertCircle, ArrowLeft, BarChart3, Check, Shield } from "lucide-react";
import { AdminCases } from "./AdminCases";
import { AdminPlaybooks } from "./AdminPlaybooks";
import { useCallback, useEffect, useState } from "react";
import { getMyUsage, getOfficeUsage, setRates, type OfficeUsageReport, type UsageReport, type UsageTotals } from "../api";
import { locale, useT } from "../i18n";
import { bucketLabel, compact, money, PRESETS, rangeFor, timeLabel, whole, type Preset } from "../lib/usage";
import {
  BarChart, Button, ColumnChart, DateField, Form, FormError, InlineNotice, NumberField, Segmented, SelectField, TextButton,
  type ChartText, type Datum, type FieldErrors, type Series,
} from "../ui";

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
      <Segmented label={m.rangeLabel} value={preset} onChange={(p) => setPreset(p as Preset)}
                 options={PRESETS.map((p) => ({ value: p, label: name[p] }))} />
      {preset === "custom" && (
        <span className="range-dates">
          <DateField label={m.from} value={from} onChange={setFrom} size="small" className="range-date" />
          <DateField label={m.to} value={to} onChange={setTo} minValue={from || undefined} size="small" className="range-date" />
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

function useChartText(category: string): ChartText {
  const m = useT();
  return { showTable: m.chartShowTable, showChart: m.chartShowChart, category, total: m.chartTotal };
}

function useTokenSeries(): Series[] {
  const m = useT();
  return [{ id: "input", label: m.inputTokens }, { id: "output", label: m.outputTokens }];
}

/** Input and output tokens per step of the period. */
function Chart({ report }: { report: UsageReport }) {
  const m = useT();
  const text = useChartText(m.chartTime);
  const series = useTokenSeries();
  const data: Datum[] = report.series.map((b) => ({
    key: b.start, label: bucketLabel(b.start, report.step), values: [b.prompt_tokens, b.completion_tokens],
  }));
  const { slots, every } = clock(report);
  // Within a day only the time, with the weekday on the first labels and where the day changes.
  const markLabel = report.step === "5 minutes" || report.step === "1 hour" ? (i: number, previous: number | null) => {
    const d = new Date(report.series[i].start);
    const sameDay = previous !== null && new Date(report.series[previous].start).toDateString() === d.toDateString();
    return sameDay ? timeLabel(d) : bucketLabel(report.series[i].start, report.step);
  } : undefined;
  return <ColumnChart label={m.chartLabel(whole(report.totals.total_tokens), m.stepName(report.step))} series={series}
                      data={data} format={whole} tick={compact} text={text} slots={slots} every={every} markLabel={markLabel} />;
}

/** Where each column sits on the clock, and the label intervals that read well for its step: every
 *  15 or 30 minutes, every 3 or 6 hours, on Mondays, … (the gateway's buckets start on whole steps). */
function clock(report: UsageReport): { slots: number[]; every: number[] } {
  const MONDAY = new Date(2000, 0, 3).getTime(); // as the gateway's buckets (usage.py ORIGIN)
  const DAY = 86_400_000;
  const at = (iso: string) => new Date(iso);
  const days = (d: Date) => Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - MONDAY) / DAY);
  const per: Record<UsageReport["step"], [(d: Date) => number, number[]]> = {
    "5 minutes": [(d) => d.getHours() * 12 + d.getMinutes() / 5, [1, 3, 6, 12, 24]],
    "1 hour": [(d) => d.getHours(), [1, 2, 3, 6, 12]],
    "1 day": [days, [1, 2, 7, 14]],
    "7 days": [(d) => days(d) / 7, [1, 2, 4, 13, 26]],
    "30 days": [(d) => d.getFullYear() * 12 + d.getMonth(), [1, 3, 6, 12]],
  };
  const [slot, every] = per[report.step];
  return { slots: report.series.map((b) => slot(at(b.start))), every };
}

/** The office's users compared; the table after it has the exact numbers, so no table of its own. */
function PerUserChart({ report }: { report: OfficeUsageReport }) {
  const m = useT();
  const text = useChartText(m.user);
  const series = useTokenSeries();
  const data: Datum[] = report.per_user.map((u) => ({
    key: u.user_id, label: u.name ?? u.username ?? m.unknownUser, values: [u.totals.prompt_tokens, u.totals.completion_tokens],
  }));
  return <BarChart label={m.perUserChartLabel(whole(report.totals.total_tokens))} series={series} data={data}
                   format={compact} text={text} withTable={false} />;
}

function ByKind({ report }: { report: UsageReport }) {
  const m = useT();
  const kinds = Object.entries(report.by_kind);
  if (kinds.length < 2) return null;
  return <p className="caption">{kinds.map(([k, v]) => `${m.kind(k)}: ${compact(v.total_tokens)}`).join(" · ")}</p>;
}

export function ViewHeader({ icon, title, onBack }: { icon: React.ReactNode; title: string; onBack: () => void }) {
  const m = useT();
  return (
    <header className="view-head">
      <TextButton onPress={onBack}><ArrowLeft size={14} aria-hidden /> {m.backToChat}</TextButton>
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
      <ViewHeader icon={<BarChart3 size={18} aria-hidden />} title={m.yourUsage} onBack={onBack} />
      <p className="view-intro">{m.usageIntro}</p>
      <RangePicker {...r} />
      {r.error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{m.usageUnavailable(r.error)}</InlineNotice>}
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
export type AdminTab = "usage" | "cases" | "playbooks";

export function AdminView({ onBack, initialTab = "usage" }: { onBack: () => void; initialTab?: AdminTab }) {
  const m = useT();
  const [tab, setTab] = useState<AdminTab>(initialTab);
  useEffect(() => { setTab(initialTab); }, [initialTab]);
  return (
    <section className="view">
      <ViewHeader icon={<Shield size={18} aria-hidden />} title={m.administration} onBack={onBack} />
      <nav className="tabs" aria-label={m.administration}>
        <Button variant="plain" className={`tab${tab === "usage" ? " on" : ""}`} aria-current={tab === "usage" ? "page" : undefined}
                onPress={() => setTab("usage")}>{m.adminUsage}</Button>
        <Button variant="plain" className={`tab${tab === "cases" ? " on" : ""}`} aria-current={tab === "cases" ? "page" : undefined}
                onPress={() => setTab("cases")}>{m.adminCases}</Button>
        <Button variant="plain" className={`tab${tab === "playbooks" ? " on" : ""}`} aria-current={tab === "playbooks" ? "page" : undefined}
                onPress={() => setTab("playbooks")}>{m.adminPlaybooks}</Button>
      </nav>
      {tab === "cases" ? <AdminCases /> : tab === "playbooks" ? <AdminPlaybooks /> : <AdminUsage />}
    </section>
  );
}

function AdminUsage() {
  const m = useT();
  const r = useReport(getOfficeUsage);
  const report = r.report as OfficeUsageReport | null;
  return (
    <>
      <p className="view-intro">{m.adminIntro}</p>
      <RangePicker {...r} />
      {r.error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{m.usageUnavailable(r.error)}</InlineNotice>}
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
              {report.per_user.length > 1 && <PerUserChart report={report} />}
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
    </>
  );
}

function RatesForm({ report, onSaved }: { report: OfficeUsageReport; onSaved: () => void }) {
  const m = useT();
  const [input, setInput] = useState(Number(report.rates.input_per_million));
  const [output, setOutput] = useState(Number(report.rates.output_per_million));
  const [currency, setCurrency] = useState(report.rates.currency);
  const [saved, setSaved] = useState(false);
  const edited = <T,>(set: (v: T) => void) => (v: T) => { set(v); setSaved(false); };
  // As the server checks them (usage.py Rates): 0 to 10,000, at most 4 decimals.
  const valid = (v: number) => Number.isFinite(v) && v >= 0 && v <= 10_000 && Number(v.toFixed(4)) === v;
  const check = async (): Promise<FieldErrors> => {
    const errors: FieldErrors = {};
    if (!valid(input)) errors.input = m.ratesInvalid;
    if (!valid(output)) errors.output = m.ratesInvalid;
    if (Object.keys(errors).length > 0) return errors;
    try {
      await setRates({ input_per_million: String(input), output_per_million: String(output), currency });
      return {};
    } catch (e) {
      return { _: (e as Error).message };
    }
  };
  const changed = report.rates.updated_by && report.rates.updated_at;
  return (
    <Form className="rates" check={check} onValid={() => { setSaved(true); onSaved(); }} aria-labelledby="rates-title">
      <h2 id="rates-title" className="label">{m.rates}</h2>
      <FormError />
      <NumberField name="input" label={m.rateInput} value={input} onChange={edited(setInput)} minValue={0} maxValue={10_000}
                   maxDecimals={4} size="small" className="rates-field" />
      <NumberField name="output" label={m.rateOutput} value={output} onChange={edited(setOutput)} minValue={0} maxValue={10_000}
                   maxDecimals={4} size="small" className="rates-field" />
      <SelectField name="currency" label={m.currency} value={currency} onChange={edited(setCurrency)} size="small"
                   options={["USD", "EUR", "GBP"].map((c) => ({ id: c, label: c }))} />
      <Button type="submit" size="small">
        {saved ? <><Check size={14} aria-hidden /> {m.saved}</> : m.save}
      </Button>
      <p className="caption">{changed ? m.ratesChanged(report.rates.updated_by!, new Date(report.rates.updated_at!).toLocaleDateString(locale(), { dateStyle: "long" })) : m.ratesDefault}</p>
    </Form>
  );
}
