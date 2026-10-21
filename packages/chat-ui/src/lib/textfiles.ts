/**
 * An answer as Markdown and a table as CSV (docs/design/sidebar.md §6, "Other formats"): the same content
 * as the Word and Excel files (lib/office.ts), as plain text, made in the browser.
 *
 * - Markdown: the question, the date and model, the answer with its [n] markers (tables as Markdown
 *   tables), what to check, every cited source with its passage as a quote, the disclaimer, and
 *   sūveryn's export mark as a comment, which the upload check reads (suveryn_rag.formats).
 * - CSV: the table with a last column naming each row's sources, as in the Excel sheet. UTF-8 with a
 *   byte order mark and semicolons, as Belgian Excel opens it. No mark, by decision: a CSV has no
 *   place for one that survives editing.
 */
import type { Segment, Table } from "./answer";
import { tableRows, type AnswerExport, type SourceItem } from "./export";
import type { OfficeText } from "./office";
import type { Watermark } from "./watermark";

const DATE = (d: Date, lang: string) => d.toLocaleDateString(lang, { day: "numeric", month: "long", year: "numeric" });
const where = (s: SourceItem) => s.citation.source?.location ?? (s.citation.source?.page ? `p. ${s.citation.source.page}` : "");

/** Text as Markdown would read it literally: the characters that start formatting, escaped. */
function escape(text: string): string {
  return text.replace(/([\\`*_[\]#|<>])/g, "\\$1");
}

/** Segments as Markdown: bold as bold, markers as [n], the rest as written. */
function inline(segments: Segment[]): string {
  return segments.map((s) => (s.kind === "cite" ? `[${s.n}]`
    : s.kind === "bold" || (s.kind === "flag" && s.bold) ? `**${escape(s.text)}**` : escape(s.text))).join("").trim();
}

/** A table as a Markdown table, markers kept in the cells. A line break in a cell becomes a space. */
function markdownTable(t: Table): string[] {
  const row = (cells: Segment[][]) => `| ${cells.map((c) => inline(c).replace(/\s*\n\s*/g, " ")).join(" | ")} |`;
  return [row(t.header), `|${t.header.map(() => " --- ").join("|")}|`, ...t.rows.map(row)];
}

export function answerToMarkdown(a: AnswerExport, text: OfficeText, lang: string): string {
  // A strictly confidential case's watermark (§11): the first line.
  const out: string[] = [...(a.watermark ? [`**${escape(a.watermark.line)}**`, ""] : []), `# ${escape(a.question)}`, "", `*${escape(text.answeredOn(DATE(a.answeredOn, lang)) + (a.model ? ` (${a.model})` : ""))}*`, ""];
  let inList = false;
  for (const b of a.blocks) {
    if (b.kind !== "li" && inList) { out.push(""); inList = false; }
    if (b.kind === "table") out.push(...markdownTable(b), "");
    else if (b.kind === "li") { out.push(`- ${inline(b.segments)}`); inList = true; }
    else out.push(inline(b.segments), "");
  }
  if (inList) out.push("");
  if (a.checks.length) out.push(`## ${escape(text.checkHeading)}`, "", ...a.checks.map((c) => `- ${escape(c)}`), "");
  if (a.sources.length) {
    out.push(`## ${escape(text.sourcesHeading)}`, "");
    for (const s of a.sources) {
      out.push(`**[${s.n}]** ${escape(s.citation.removed ? text.sourceRemoved : [s.filename, where(s)].filter(Boolean).join(", "))}`, "");
      if (!s.citation.removed) out.push(...s.citation.text.trim().split("\n").map((l) => `> ${escape(l)}`.trimEnd()), "");
    }
  }
  out.push(`*${escape(text.disclaimer)}*`, "");
  // sūveryn's export mark (lib/marks.ts): a comment, so it isn't shown but the upload check finds it.
  if (a.mark) out.push(`<!-- ${a.mark.replace(/--/g, "‐‐")} -->`, "");
  return out.join("\n");
}

/** One CSV field: quoted when it holds a separator, a quote or a line break; a formula's first
 *  character neutralised, so a cell can't run as a formula when the file is opened (CSV injection). */
function field(value: string): string {
  const safe = /^[=+\-@\t\r]/.test(value) && !/^[-+]?\d/.test(value) ? `'${value}` : value;
  return /[;"\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function tableToCsv(t: Table, text: Pick<OfficeText, "sourceColumn">, watermark?: Watermark): string {
  const { header, rows } = tableRows(t, text.sourceColumn);
  const lines = [...(watermark ? [[watermark.line]] : []), header, ...rows.map((r) => [...r.cells, r.sources.join(", ")])]
    .map((cells) => cells.map(field).join(";"));
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}
