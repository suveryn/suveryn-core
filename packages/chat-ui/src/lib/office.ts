/**
 * Word (.docx) and Excel (.xlsx) files from an answer, made in the browser with docx and
 * write-excel-file (both MIT). The libraries are loaded on the first download only, so the chat
 * doesn't get slower; nothing is fetched from elsewhere, they are part of the build.
 */
import type { Segment, Table } from "./answer";
import { cellValue, segmentText, tableRows, type AnswerExport, type SourceItem } from "./export";

export type OfficeText = {
  answeredOn: (date: string) => string;      // "Answered by sūveryn on 11 October 2026"
  checkHeading: string;                      // "To check"
  sourcesHeading: string;                    // "Sources"
  sourceRemoved: string;
  sourceColumn: string;                      // "Source"
  sheetTable: string; sheetSources: string; sheetChecks: string;
  columns: { n: string; document: string; where: string; passage: string };
  disclaimer: string;                        // check every figure against the source
};

const DATE = (d: Date, lang: string) => d.toLocaleDateString(lang, { day: "numeric", month: "long", year: "numeric" });
const where = (s: SourceItem) => s.citation.source?.location ?? (s.citation.source?.page ? `p. ${s.citation.source.page}` : "");

/** The answer as a Word document: question, answer (paragraphs, lists, tables), checks, sources. */
export async function answerToWord(a: AnswerExport, text: OfficeText, lang: string): Promise<Blob> {
  const d = await import("docx");
  const runs = (segments: Segment[]) => segments.map((s) =>
    s.kind === "cite" ? new d.TextRun({ text: `[${s.n}]`, superScript: true })
    // a figure to check: a wavy accent-ink underline, as on screen (no separate yellow)
    : new d.TextRun({ text: s.text, bold: s.kind === "bold" || (s.kind === "flag" && s.bold),
                      underline: s.kind === "flag" ? { type: d.UnderlineType.WAVE, color: "C42F00" } : undefined }));
  const table = (t: Table) => new d.Table({
    width: { size: 100, type: d.WidthType.PERCENTAGE },
    rows: [t.header, ...t.rows].map((row, r) => new d.TableRow({
      tableHeader: r === 0,
      children: row.map((cell) => new d.TableCell({
        children: [new d.Paragraph({ children: r === 0 ? [new d.TextRun({ text: segmentText(cell), bold: true })] : runs(cell) })],
      })),
    })),
  });
  const body: (InstanceType<typeof d.Paragraph> | InstanceType<typeof d.Table>)[] = [
    new d.Paragraph({ text: a.question, heading: d.HeadingLevel.HEADING_1 }),
    new d.Paragraph({ children: [new d.TextRun({ text: text.answeredOn(DATE(a.answeredOn, lang)) + (a.model ? ` (${a.model})` : ""), italics: true, size: 18 })] }),
  ];
  for (const b of a.blocks) {
    if (b.kind === "table") body.push(table(b), new d.Paragraph({}));
    else body.push(new d.Paragraph({ children: runs(b.segments), bullet: b.kind === "li" ? { level: 0 } : undefined }));
  }
  if (a.checks.length) {
    body.push(new d.Paragraph({ text: text.checkHeading, heading: d.HeadingLevel.HEADING_2 }));
    a.checks.forEach((c) => body.push(new d.Paragraph({ text: c, bullet: { level: 0 } })));
  }
  if (a.sources.length) {
    body.push(new d.Paragraph({ text: text.sourcesHeading, heading: d.HeadingLevel.HEADING_2 }));
    for (const s of a.sources) {
      body.push(new d.Paragraph({ children: [new d.TextRun({ text: `[${s.n}] `, bold: true }),
        new d.TextRun({ text: s.citation.removed ? text.sourceRemoved : [s.filename, where(s)].filter(Boolean).join(", ") })] }));
      if (!s.citation.removed) {
        body.push(new d.Paragraph({ children: [new d.TextRun({ text: s.citation.text.trim(), italics: true })], indent: { left: 360 } }));
      }
    }
  }
  body.push(new d.Paragraph({ children: [new d.TextRun({ text: text.disclaimer, italics: true, size: 16 })] }));
  return d.Packer.toBlob(new d.Document({ creator: "sūveryn", title: a.question, sections: [{ children: body }] }));
}

/** One table as an Excel workbook: the table (with each row's sources), the sources, what to check. */
export async function tableToExcel(t: Table, a: AnswerExport, text: OfficeText): Promise<Blob> {
  const { default: writeExcelFile } = await import("write-excel-file/browser");
  const { header, rows } = tableRows(t, text.sourceColumn);
  const width = (texts: string[]) => Math.min(60, Math.max(8, ...texts.map((x) => x.length + 2)));
  const tableData = [
    header.map((h) => ({ value: h, fontWeight: "bold" as const })),
    ...rows.map((r) => [...r.cells.map((c) => {
      const v = cellValue(c);
      return v.format ? { value: v.value as number, format: v.format } : { value: String(v.value), wrap: true };
    }), { value: r.sources.join(", ") }]),
  ];
  const cited = a.sources.filter((s) => rows.some((r) => r.sources.includes(s.n)));
  const sheets = [{
    data: tableData, sheet: text.sheetTable, stickyRowsCount: 1,
    columns: header.map((h, i) => ({ width: width([h, ...rows.map((r) => (i < r.cells.length ? r.cells[i] : r.sources.join(", ")))]) })),
  }, {
    sheet: text.sheetSources, stickyRowsCount: 1,
    data: [[text.columns.n, text.columns.document, text.columns.where, text.columns.passage].map((h) => ({ value: h, fontWeight: "bold" as const })),
           ...cited.map((s) => [{ value: s.n }, { value: s.citation.removed ? text.sourceRemoved : s.filename },
                                { value: where(s) }, { value: s.citation.removed ? "" : s.citation.text.trim(), wrap: true }])],
    columns: [{ width: 8 }, { width: 30 }, { width: 24 }, { width: 80 }],
  }];
  if (a.checks.length) {
    sheets.push({ sheet: text.sheetChecks, stickyRowsCount: 0, data: a.checks.map((c) => [{ value: c, wrap: true }]) as never, columns: [{ width: 100 }] });
  }
  return writeExcelFile(sheets as never).toBlob();
}

export type IntakeExport = {
  title: string; caseName: string; version: string; confirmedOn: string;
  facts: { label: string; value: string; sources: string[] }[];
  sourcesHeading: string; emptyValue: string; disclaimer: string;
};

/** A playbook run's confirmed facts as a Word document (suveryn-tracker#51): a heading, a table of
 *  facts with where each was read from, and the disclaimer. The case's record; sūveryn's own layout
 *  until the office's templates exist (suveryn-tracker#22). */
export async function intakeToWord(x: IntakeExport): Promise<Blob> {
  const d = await import("docx");
  const cell = (text: string, bold = false) => new d.TableCell({ children: [new d.Paragraph({ children: [new d.TextRun({ text, bold })] })] });
  const table = new d.Table({
    width: { size: 100, type: d.WidthType.PERCENTAGE },
    rows: [
      new d.TableRow({ tableHeader: true, children: [cell("", true), cell("", true), cell(x.sourcesHeading, true)] }),
      ...x.facts.map((f) => new d.TableRow({ children: [cell(f.label, true), cell(f.value || x.emptyValue), cell(f.sources.join(", "))] })),
    ],
  });
  const doc = new d.Document({ sections: [{ children: [
    new d.Paragraph({ text: x.title, heading: d.HeadingLevel.HEADING_1 }),
    new d.Paragraph({ children: [new d.TextRun({ text: x.caseName })] }),
    new d.Paragraph({ children: [new d.TextRun({ text: `${x.confirmedOn} · ${x.version}`, italics: true, size: 18 })] }),
    new d.Paragraph({}),
    table,
    new d.Paragraph({}),
    new d.Paragraph({ children: [new d.TextRun({ text: x.disclaimer, italics: true, size: 18 })] }),
  ] }] });
  return d.Packer.toBlob(doc);
}

/** Save a made file under a name (a click on a temporary link; nothing leaves the browser). */
export function saveBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
