/**
 * Charts (suveryn-tracker#46): columns over time and bars per person or thing, each with up to two
 * stacked series (such as input and output tokens). Drawn in HTML with the brand's chart colours
 * from ui.css; heights and widths are style properties set through the DOM, which the CSP allows
 * (docs/content-security-policy.md). No chart library: d3-array gives the round axis steps
 * (chartScale.ts), and that is all a bar needs.
 *
 * For everyone: every chart can be shown as a table; the columns are one Tab stop, and the arrow
 * keys, Home and End move between them, each read out with its values; the bars print their totals.
 * Series differ in lightness as well as hue, and the legend names them in stacking order.
 */
import { Table2, ChartColumnBig } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "./Button";
import { marks, share, step, sum, valueAxis } from "./chartScale";

/** At most two: the brand has two chart colours that tell apart in greyscale (ui.css, --chart-*). */
export type Series = { id: string; label: string };
/** One column or bar: its label, and a value per series, in the order of `series`. */
export type Datum = { key: string; label: string; values: number[] };

export type ChartText = {
  showTable: string;
  showChart: string;
  /** The heading of the table's first column: what a row is ("Time", "User"). */
  category: string;
  total: string;
};

type Common = {
  /** What the chart shows, in words: its accessible name and caption. */
  label: string;
  series: Series[];
  data: Datum[];
  /** Exact values (the table, what a column reads out). */
  format: (n: number) => string;
  text: ChartText;
};

/** Columns over time. `tick` formats the value axis (short: "15k"). The time axis labels up to eight
 *  columns, every other one of them at phone width; `slots` and `every` put them on round times
 *  (see marks in chartScale.ts). */
export function ColumnChart({ label, series, data, format, tick, text, slots, every, markLabel }: Common & {
  tick: (n: number) => string; slots?: number[]; every?: number[];
  /** A label on the time axis shorter than the column's own, given the column of the label two
   *  before it (null for the first two): the label before it on a phone, which hides every other
   *  one. So "21:00" after "wo 15:00", and the weekday again where the day changes. */
  markLabel?: (index: number, previous: number | null) => string;
}) {
  const [table, setTable] = useState(false);
  const [active, setActive] = useState(0);
  // The column whose values float above it: the one under the mouse, else the one with focus.
  const [hovered, setHovered] = useState<number | null>(null);
  const [focused, setFocused] = useState<number | null>(null);
  const shown = hovered ?? focused;
  const refs = useRef<(HTMLLIElement | null)[]>([]);
  const captionId = useId();
  const axis = valueAxis(Math.max(0, ...data.map((d) => sum(d.values))));
  const onKey = (e: KeyboardEvent) => {
    const next = step(e.key, active, data.length, "horizontal");
    if (next === null) return;
    e.preventDefault();
    refs.current[next]?.focus();
  };
  return (
    <figure className="ui-chart">
      <ChartHead series={series} table={table} onToggle={() => setTable(!table)} text={text} />
      {table ? <DataTable label={label} series={series} data={data} format={format} text={text} /> : (
        <>
          <div className="ui-chart-plot">
            <div className="ui-chart-axis" aria-hidden>
              {axis.ticks.map((t) => <span key={t} className="ui-chart-tick" style={{ bottom: `${share(t, axis.top)}%` }}>{tick(t)}</span>)}
            </div>
            <div className="ui-chart-area" onMouseLeave={() => setHovered(null)}>
              {axis.ticks.map((t) => <span key={t} className="ui-chart-grid" aria-hidden style={{ bottom: `${share(t, axis.top)}%` }} />)}
              <ul className="ui-chart-columns" aria-labelledby={captionId} onKeyDown={onKey}>
                {data.map((d, i) => (
                  <li key={d.key} ref={(el) => { refs.current[i] = el; }} className="ui-chart-column"
                      tabIndex={i === active ? 0 : -1} data-active={shown === i || undefined}
                      onFocus={() => { setActive(i); setFocused(i); }} onBlur={() => setFocused(null)}
                      onMouseEnter={() => setHovered(i)}>
                    <span className="ui-chart-stack" style={{ height: `${share(sum(d.values), axis.top)}%` }} aria-hidden>
                      {d.values.map((v, s) => v > 0 && (
                        <span key={s} className="ui-chart-segment" data-series={s} style={{ flexGrow: v }} />
                      ))}
                    </span>
                    <span className="ui-visually-hidden">{readOut(d, series, format, text)}</span>
                  </li>
                ))}
              </ul>
              {shown !== null && data[shown] && (
                <Tip datum={data[shown]} series={series} format={format} text={text}
                     at={(shown + 0.5) / data.length} />
              )}
            </div>
          </div>
          <div className="ui-chart-x" aria-hidden>
            {marks(data.length, 8, slots, every).map((i, n, all) => {
              const at = (i + 0.5) / data.length;
              return (
                <span key={data[i].key} className="ui-chart-x-mark" data-minor={n % 2 === 1 || undefined}
                      data-edge={at < 0.08 ? "start" : at > 0.92 ? "end" : undefined} style={{ left: `${at * 100}%` }}>
                  {markLabel ? markLabel(i, n > 1 ? all[n - 2] : null) : data[i].label}
                </span>
              );
            })}
          </div>
        </>
      )}
      <figcaption id={captionId} className="ui-chart-caption">{label}</figcaption>
    </figure>
  );
}

/** Bars side by side for comparison (per user, per model), longest first, each with its total
 *  printed after it. `withTable={false}` when the screen shows the same numbers in a table of its own. */
export function BarChart({ label, series, data, format, text, withTable = true }: Common & { withTable?: boolean }) {
  const [table, setTable] = useState(false);
  const captionId = useId();
  const rows = [...data].sort((a, b) => sum(b.values) - sum(a.values));
  const top = Math.max(0, ...rows.map((d) => sum(d.values)));
  return (
    <figure className="ui-chart">
      <ChartHead series={series} table={table} onToggle={withTable ? () => setTable(!table) : undefined} text={text} />
      {table ? <DataTable label={label} series={series} data={rows} format={format} text={text} /> : (
        <ul className="ui-chart-bars" aria-labelledby={captionId}>
          {rows.map((d) => (
            <li key={d.key} className="ui-chart-bar-row">
              <span className="ui-chart-bar-label">{d.label}</span>
              <span className="ui-chart-bar-track" aria-hidden>
                <span className="ui-chart-stack" style={{ width: `${share(sum(d.values), top)}%` }}>
                  {d.values.map((v, s) => v > 0 && (
                    <span key={s} className="ui-chart-segment" data-series={s} style={{ flexGrow: v }} />
                  ))}
                </span>
              </span>
              <span className="ui-chart-bar-value" aria-hidden>{format(sum(d.values))}</span>
              <span className="ui-visually-hidden">{readOut(d, series, format, text, false)}</span>
            </li>
          ))}
        </ul>
      )}
      <figcaption id={captionId} className="ui-chart-caption">{label}</figcaption>
    </figure>
  );
}

/** "Tue 14:00: Input tokens 1,200, Output tokens 300, Total 1,500" (the label is left out where it
 *  is already visible). */
function readOut(d: Datum, series: Series[], format: (n: number) => string, text: ChartText, withLabel = true) {
  const parts = series.map((s, i) => `${s.label} ${format(d.values[i] ?? 0)}`);
  if (series.length > 1) parts.push(`${text.total} ${format(sum(d.values))}`);
  return `${withLabel ? `${d.label}: ` : ""}${parts.join(", ")}`;
}

function ChartHead({ series, table, onToggle, text }: { series: Series[]; table: boolean; onToggle?: () => void; text: ChartText }) {
  return (
    <div className="ui-chart-head">
      {series.length > 1 && !table ? (
        <ul className="ui-chart-legend" aria-hidden>
          {/* Top of the stack first, as it is drawn. */}
          {series.map((s, i) => ({ s, i })).reverse().map(({ s, i }) => (
            <li key={s.id}><span className="ui-chart-swatch" data-series={i} />{s.label}</li>
          ))}
        </ul>
      ) : <span />}
      {onToggle && (
        <Button variant="quiet" size="small" onPress={onToggle}>
          {table ? <ChartColumnBig size={14} aria-hidden /> : <Table2 size={14} aria-hidden />}
          {table ? text.showChart : text.showTable}
        </Button>
      )}
    </div>
  );
}

function Tip({ datum, series, format, text, at }: { datum: Datum; series: Series[]; format: (n: number) => string;
                                                    text: ChartText; at: number }) {
  // Kept inside the plot near the edges: anchored left in the first fifth, right in the last.
  const edge = at < 0.2 ? "start" : at > 0.8 ? "end" : undefined;
  return (
    <div className="ui-chart-tip" aria-hidden data-edge={edge} style={{ left: `${at * 100}%` }}>
      <b>{datum.label}</b>
      {series.map((s, i) => (
        <span key={s.id} className="ui-chart-tip-row">
          {series.length > 1 && <span className="ui-chart-swatch" data-series={i} />}{s.label}<span>{format(datum.values[i] ?? 0)}</span>
        </span>
      ))}
      {series.length > 1 && <span className="ui-chart-tip-row ui-chart-tip-total">{text.total}<span>{format(sum(datum.values))}</span></span>}
    </div>
  );
}

function DataTable({ label, series, data, format, text }: Omit<Common, "text"> & { text: ChartText }) {
  return (
    <div className="ui-chart-table-wrap">
      <table className="ui-chart-table">
        <caption className="ui-visually-hidden">{label}</caption>
        <thead>
          <tr>
            <th scope="col">{text.category}</th>
            {series.map((s) => <th key={s.id} scope="col">{s.label}</th>)}
            {series.length > 1 && <th scope="col">{text.total}</th>}
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.key}>
              <th scope="row">{d.label}</th>
              {series.map((s, i) => <td key={s.id}>{format(d.values[i] ?? 0)}</td>)}
              {series.length > 1 && <td>{format(sum(d.values))}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
