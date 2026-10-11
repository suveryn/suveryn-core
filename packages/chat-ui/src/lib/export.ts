/**
 * An answer as a Word document or a table as an Excel sheet: what goes in, as plain data. The files
 * themselves are made in lib/office.ts, in the browser: nothing is sent anywhere.
 *
 * What travels with the content, so a file read later says as much as the chat did: the question,
 * the date, every warning (figures to check, calculations, citations to check) and every cited
 * source with its passage. A deleted document's source says so.
 */
import type { Calculation, Citation, CitationIssue } from "../api";
import type { Block, Segment, Table } from "./answer";

export type SourceItem = { n: number; citation: Citation; filename: string };

/** Text of segments; markers as [n] (or left out). */
export function segmentText(segments: Segment[], markers = true): string {
  return segments.map((s) => (s.kind === "cite" ? (markers ? `[${s.n}]` : "") : s.text)).join("").replace(/[ \t]+$/g, "").replace(/\s+([.,;:])/g, "$1").trim();
}

/** The source numbers cited in segments, in order, once each. */
export function segmentSources(segments: Segment[]): number[] {
  const out: number[] = [];
  for (const s of segments) if (s.kind === "cite" && !out.includes(s.n)) out.push(s.n);
  return out;
}

export type CellValue = { value: string | number; format?: string };

const COMMA_DECIMAL = [/^\d{1,3}(?:\.\d{3})+(?:,\d+)?$/, /^\d+,\d+$/];  // 1.275.000,00 · 12,5
const DOT_DECIMAL = [/^\d{1,3}(?:,\d{3})+(?:\.\d+)?$/, /^\d+\.\d+$/];   // 1,275,000.00 · 12.5

/**
 * A spreadsheet cell: a number when the text is clearly one amount or number, otherwise the text.
 * "EUR 1.275.000,00" and "€ 48.200" become amounts (in euros three digits after a separator are
 * thousands: cents have two), "25 %" a percentage, "4182" a whole number.
 * Anything ambiguous stays text: "1.275" (a thousand or one and a bit?), "0123" (a leading zero),
 * dates, references. Excel shows numbers in the reader's own style.
 */
export function cellValue(text: string): CellValue {
  const t = text.replace(/[  ]/g, " ").trim();
  let core = t, currency = false, percent = false, m: RegExpMatchArray | null;
  if ((m = core.match(/^(?:EUR|€)\s*(.+)$/i) ?? core.match(/^(.+?)\s*(?:EUR|€)$/i))) { core = m[1]; currency = true; }
  else if ((m = core.match(/^(.+?)\s*%$/))) { core = m[1]; percent = true; }
  const negative = core.startsWith("-");
  const digits = negative ? core.slice(1) : core;
  const comma = COMMA_DECIMAL.some((r) => r.test(digits)), dot = DOT_DECIMAL.some((r) => r.test(digits));
  let value: number, decimals: number;
  if (/^\d+$/.test(digits)) {
    if (digits.length > 1 && digits.startsWith("0")) return { value: t };
    value = Number(digits); decimals = 0;
  } else if (currency && /^\d{1,3}[.,]\d{3}$/.test(digits)) {
    value = Number(digits.replace(/[.,]/, "")); decimals = 0;  // € 48.200: cents have two digits, so these are thousands
  } else if (comma !== dot) {
    const [whole, frac = ""] = comma ? digits.replaceAll(".", "").split(",") : digits.replaceAll(",", "").split(".");
    value = Number(`${whole}.${frac || "0"}`); decimals = frac.length;
  } else {
    return { value: t };
  }
  if (negative) value = -value;
  const grouped = (d: number) => `#,##0${d ? "." + "0".repeat(d) : ""}`;
  if (currency) return { value, format: `"€" ${grouped(Math.max(decimals, 2))}` };
  if (percent) return { value: value / 100, format: `0${decimals ? "." + "0".repeat(decimals) : ""}%` };
  return /[.,]/.test(digits) ? { value, format: grouped(decimals) } : { value, format: "0" };
}

/**
 * A table as rows of plain text, with a last column naming each row's sources. A column the model
 * filled with markers only (its own "Source" column) is left out: its numbers are in that last column.
 */
export function tableRows(table: Table, sourceColumn: string): { header: string[]; rows: { cells: string[]; sources: number[] }[] } {
  const markersOnly = (i: number) => table.rows.length > 0 && table.rows.every((r) =>
    segmentText(r[i] ?? [], false) === "" && (r[i] ?? []).some((s) => s.kind === "cite"));
  const keep = table.header.map((_, i) => !markersOnly(i));
  return {
    header: [...table.header.filter((_, i) => keep[i]).map((c) => segmentText(c, false)), sourceColumn],
    rows: table.rows.map((r) => ({ cells: r.filter((_, i) => keep[i]).map((c) => segmentText(c, false)), sources: segmentSources(r.flat()) })),
  };
}

/** Everything an exported answer says besides its text: what to check, and how figures were made. */
export function checkLines(calculations: Calculation[], unverified: string[], issues: CitationIssue[], text: {
  calcFailed: (e: string, why: string) => string; calculatedBy: string; calcMissing: (f: string[]) => string;
  unverified: (f: string[]) => string; citationIssue: (n: number, item: string, foundIn: number[], writtenAs: string | null) => string;
}): string[] {
  const lines: string[] = [];
  for (const c of calculations) {
    lines.push(c.result === null ? text.calcFailed(c.expression, c.error ?? "")
      : `${text.calculatedBy} ${c.expression} = ${c.result}.${c.figures_not_in_sources.length ? text.calcMissing(c.figures_not_in_sources) : ""}`);
  }
  if (unverified.length) lines.push(text.unverified(unverified));
  for (const i of issues) {
    const line = text.citationIssue(i.n, i.item, i.found_in, i.written_as);
    if (!lines.includes(line)) lines.push(line);
  }
  return lines;
}

/** The answer's blocks with the parts an exported file needs. */
export type AnswerExport = {
  question: string;
  answeredOn: Date;
  model?: string;
  blocks: Block[];
  checks: string[];
  sources: SourceItem[];
};
