/**
 * The conversation turns. Only the user's turn has a bubble; the assistant's reply has none and is
 * marked by the teal brand-mark outline. Model output is rendered as React text only (lib/answer.ts),
 * never as HTML. Under an answer: the cited sources, copy and download, calculation notes and the
 * "not sourced" notices that tell a reader what to check.
 */
import { AlertCircle, AlertTriangle, Calculator, Check, Copy, Download, FileSpreadsheet, FileText } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { Button, InlineNotice, MenuButton } from "../ui";
import type { Calculation, Citation, CitationIssue } from "../api";
import { lang, locale, useT } from "../i18n";
import { exportRef } from "../lib/marks";
import { citedNumbers, claimTerms, claimTexts, markerClaims, markPassage, termsOf, toBlocks, type Segment, type Table } from "../lib/answer";
import { checkLines, type AnswerExport } from "../lib/export";
import { statusText } from "../lib/status";
import {
  copyText, downloadText, formatSource, formatSourceMarkdown, formatSources, safeFileName, sourceFileName,
  sourcesDocument, sourcesMarkdown, type Format,
} from "../lib/copy";
import type { AssistantTurn, UserTurn } from "../types";
import { AssistantMark } from "./Brand";
import { AttachmentChip, CitationChip } from "./Chips";

/** The user's turn: attachment chips above a bubble (the only bubble in the conversation). */
export function UserMessage({ turn }: { turn: UserTurn }) {
  return (
    <div className="turn-user">
      {turn.attachments.length > 0 && (
        <div className="attachments">{turn.attachments.map((a) => <AttachmentChip key={a.key} a={a} />)}</div>
      )}
      {turn.text && <div className="bubble">{turn.text}</div>}
    </div>
  );
}

/** A small ghost button that copies text and confirms it ("Copied") for two seconds. */
function CopyButton({ text, label, what }: { text: string; label: string; what: string }) {
  const m = useT();
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(t);
  }, [state]);
  return (
    <Button variant="plain" className="copy-button" aria-label={m.copyWhat(what)}
            onPress={async () => setState((await copyText(text)) ? "copied" : "failed")}>
      {state === "copied" ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
      <span aria-live="polite">{state === "copied" ? m.copied : state === "failed" ? m.copyFailed : label}</span>
    </Button>
  );
}

/** A small ghost button with a menu: save as plain text (.txt) or Markdown (.md). */
function DownloadButton({ filename, text, what }: {
  filename: (format: Format) => string; text: (format: Format) => string; what: string;
}) {
  const m = useT();
  return (
    <MenuButton className="copy-button" aria-label={m.downloadWhat(what)} menuLabel={m.download}
                items={[{ id: "txt", label: m.textFile }, { id: "md", label: m.markdownFile }]} placement="bottom end"
                onAction={(f) => downloadText(filename(f as Format), text(f as Format))}>
      <Download size={13} aria-hidden />
      <span>{m.download}</span>
    </MenuButton>
  );
}

export function SourceCard({ n, citation, filename, terms = [], claims = [] }: { n: number; citation: Citation; filename: string; terms?: string[]; claims?: string[] }) {
  const m = useT();
  const quote = useRef<HTMLQuoteElement>(null);
  // Scroll the passage (not the page) to the first marked fact: a long passage shows only its start.
  useEffect(() => {
    const box = quote.current, first = box?.querySelector("mark");
    // .source-text is position: relative, so a mark's offsetTop is measured from the passage itself.
    if (box && first instanceof HTMLElement) box.scrollTop = Math.max(0, first.offsetTop - box.clientHeight / 3);
  }, [n, citation.text]);
  if (citation.removed) {
    return (
      <div className="source-card" role="region" aria-label={m.source(n)}>
        <div className="source-head">
          <span className="label">{m.source(n)}</span>
          <span className="source-file">{m.sourceRemoved}</span>
        </div>
        <p className="caption">{m.sourceRemovedCaption}</p>
      </div>
    );
  }
  return (
    <div className="source-card" role="region" aria-label={m.source(n)}>
      <div className="source-head">
        <span className="label">{m.source(n)}</span>
        <span className="source-file">{filename}</span>
        <span className="source-where">{citation.source?.location ?? (citation.source?.page ? `p. ${citation.source.page}` : "")}</span>
        <span className="source-actions">
          <CopyButton text={formatSource(n, citation, filename)} label={m.copy} what={m.sourceWithReference(n)} />
          <DownloadButton filename={(f) => sourceFileName(n, filename, citation.source?.page, f)} what={m.sourceN(n)}
                          text={(f) => (f === "md" ? formatSourceMarkdown(n, citation, filename) : formatSource(n, citation, filename)) + "\n"} />
        </span>
      </div>
      <blockquote className="source-text" ref={quote}>
        {markPassage(citation.text, claims, terms).map((part, i) => (part.mark
          ? <mark key={i} className={part.mark === "term" ? "source-match" : "source-span"}>{part.text}</mark>
          : <Fragment key={i}>{part.text}</Fragment>))}
      </blockquote>
      <p className="caption">{m.sourceCaption}</p>
    </div>
  );
}

/**
 * The assistant's turn: no bubble, marked by the teal brand-mark outline. Citation markers [n]
 * become buttons that open the source (citations[n-1]); only cited sources are listed below.
 */
export function AssistantMessage({ turn, question, filenames, caseRef = null }: {
  turn: AssistantTurn; question: string; filenames: Map<string, string>;
  /** The case the conversation is in (null: personal), named in the export mark. */
  caseRef?: string | null;
}) {
  const m = useT();
  const [open, setOpen] = useState<number | null>(null);
  const available = turn.citations.length;
  const cited = citedNumbers(turn.text, available);
  const nameOf = (c: Citation) => (c.removed ? m.sourceRemoved : (c.source && filenames.get(c.source.document_id)) || m.unnamedDocument);
  // The marker clicked (its ``occ``), so the card shows what that claim rests on; null from the source list: every claim.
  const [openOcc, setOpenOcc] = useState<number | null>(null);
  const toggle = (n: number, occ: number | null = null) => {
    const closing = open === n && openOcc === occ;
    setOpen(closing ? null : n);
    setOpenOcc(closing ? null : occ);
  };
  // Copy and download only what is still there: a deleted document's passage was taken out.
  const citedItems = cited.filter((n) => !turn.citations[n - 1].removed)
    .map((n) => ({ n, citation: turn.citations[n - 1], filename: nameOf(turn.citations[n - 1]) }));
  const allSources = formatSources(citedItems);
  const flagged = turn.unverifiedFigures ?? [];
  const issues = turn.status === "done" ? turn.citationIssues ?? [] : [];
  const flaggedMarkers = new Set(issues.map((i) => i.marker));
  const blocks = toBlocks(turn.text, turn.status === "done" ? available : 0, turn.status === "done" ? flagged : []);
  // Word and Excel downloads carry the same warnings and sources as the chat (lib/export.ts).
  const exported = (): AnswerExport => ({
    question, answeredOn: new Date(), model: turn.model, blocks,
    checks: [...checkLines(turn.calculations ?? [], flagged, issues, m),
             ...(turn.instructionLikeSources?.length ? [m.instructionLike(turn.instructionLikeSources)] : [])],
    sources: cited.map((n) => ({ n, citation: turn.citations[n - 1], filename: nameOf(turn.citations[n - 1]) })),
    // sūveryn's mark (lib/marks.ts): so that this file, uploaded again, is recognised and asks first.
    mark: m.exportMark("answer", caseRef, new Date().toLocaleDateString(locale()), exportRef("A", turn.id)),
  });
  const render = (segments: Segment[]) => segments.map((s, j) =>
    s.kind === "text" ? <Fragment key={j}>{s.text}</Fragment> :
    s.kind === "bold" ? <strong key={j}>{s.text}</strong> :
    s.kind === "flag" ? <mark key={j} className="unverified" title={m.unverifiedTitle}>
                          {s.bold ? <strong>{s.text}</strong> : s.text}</mark> :
    <Button key={j} variant="plain" className={`cite-marker${open === s.n && (openOcc === null || openOcc === s.occ) ? " active" : ""}${flaggedMarkers.has(s.occ) ? " flagged" : ""}`}
            onPress={() => toggle(s.n, s.occ)} aria-expanded={open === s.n && (openOcc === null || openOcc === s.occ)}
            title={flaggedMarkers.has(s.occ) ? m.citationIssueTitle : undefined}
            aria-label={m.sourceLabel(s.n, nameOf(turn.citations[s.n - 1]), null)
                        + (flaggedMarkers.has(s.occ) ? `. ${m.citationIssueTitle}` : "")}>{s.n}</Button>);

  if (turn.status === "error") {
    return (
      <div className="turn-assistant">
        <AssistantMark />
        <div className="answer">
          <InlineNotice icon={<AlertCircle size={14} />} tone="error">{m.answerFailed(turn.error ?? "")}</InlineNotice>
        </div>
      </div>
    );
  }

  return (
    <div className="turn-assistant">
      <AssistantMark />
      <div className="answer" aria-live={turn.status === "streaming" ? "polite" : undefined}>
        {blocks.map((b, i) => (b.kind === "table"
          ? <AnswerTable key={i} table={b} render={render} done={turn.status === "done"} exported={exported} />
          : b.kind === "li" ? <li key={i}>{render(b.segments)}</li> : <p key={i}>{render(b.segments)}</p>))}
        {turn.status === "streaming" && (turn.text
          ? <WaitingDots />                                              /* answer is arriving */
          : <p className="waiting" role="status"><WaitingDots /><span>{statusText(turn.step) ?? m.sending}</span></p>)}

        {turn.status === "done" && turn.calculations?.map((c, i) => <CalculationNote key={i} calc={c} />)}
        {turn.status === "done" && flagged.length > 0 && <UnverifiedNote figures={flagged} />}
        {issues.length > 0 && <CitationIssuesNote issues={issues} />}
        {turn.status === "done" && (turn.instructionLikeSources?.length ?? 0) > 0 && (
          <InlineNotice icon={<AlertTriangle size={14} />} tone="error">{m.instructionLike(turn.instructionLikeSources!)}</InlineNotice>
        )}

        {turn.status === "done" && open !== null && turn.citations[open - 1] && (
          <SourceCard n={open} citation={turn.citations[open - 1]} filename={nameOf(turn.citations[open - 1])}
                      {...(() => {
                        const one = openOcc === null ? undefined : markerClaims(turn.text, available)[openOcc];
                        return one?.n === open ? { terms: termsOf(one.claim), claims: [one.claim] }
                          : { terms: claimTerms(turn.text, available).get(open) ?? [], claims: claimTexts(turn.text, available).get(open) ?? [] };
                      })()} />
        )}

        {turn.status === "done" && turn.text && (
          <div className="answer-actions">
            <OfficeButton kind="word" label={m.downloadWord} what={m.downloadWordWhat}
                          make={async () => {
                            const { answerToWord } = await import("../lib/office");
                            return [`${safeFileName(question)}.docx`, await answerToWord(exported(), officeText(m), lang())];
                          }} />
          </div>
        )}

        {turn.status === "done" && cited.length > 0 && (
          <div className="sources">
            <span className="label">{m.sources}</span>
            {cited.map((n) => (
              <CitationChip key={n} n={n} citation={turn.citations[n - 1]} filename={nameOf(turn.citations[n - 1])}
                            active={open === n} onClick={() => toggle(n)} />
            ))}
            {citedItems.length > 0 && <CopyButton label={m.copySources} what={m.allCitedSources} text={allSources} />}
            {citedItems.length > 0 && <DownloadButton filename={(f) => `sources_${safeFileName(question)}.${f}`} what={m.allCitedSources}
                            text={(f) => (f === "md" ? sourcesMarkdown(question, citedItems, new Date())
                                                     : sourcesDocument(question, allSources, new Date()))} />}
          </div>
        )}

        {turn.status === "done" && cited.length === 0 && (
          <InlineNotice icon={<AlertCircle size={14} />}>{turn.grounded ? m.noSourceCited : m.notGrounded}</InlineNotice>
        )}
      </div>
    </div>
  );
}

/**
 * Flags figures in the answer that are in no source and weren't calculated by the server: the
 * model worked them out or made them up (it is told never to do arithmetic itself).
 */
function UnverifiedNote({ figures }: { figures: string[] }) {
  const m = useT();
  return (
    <InlineNotice icon={<AlertTriangle size={14} />} tone="error">{m.unverified(figures)}</InlineNotice>
  );
}

/** A Markdown table in an answer, as a real table (so copy and paste into Excel or Word keeps the
 *  columns), with an Excel download under it once the answer is complete. */
function AnswerTable({ table, render, done, exported }: {
  table: Table; render: (s: Segment[]) => React.ReactNode; done: boolean; exported: () => AnswerExport;
}) {
  const m = useT();
  const align = (i: number) => table.align[i] ?? undefined;
  return (
    <div className="answer-table">
      <div className="answer-table-scroll">
        <table>
          <thead><tr>{table.header.map((c, i) => <th key={i} style={{ textAlign: align(i) }}>{render(c)}</th>)}</tr></thead>
          <tbody>{table.rows.map((r, j) => (
            <tr key={j}>{r.map((c, i) => <td key={i} style={{ textAlign: align(i) }}>{render(c)}</td>)}</tr>))}
          </tbody>
        </table>
      </div>
      {done && (
        <OfficeButton kind="excel" label={m.downloadExcel} what={m.downloadExcelWhat}
                      make={async () => {
                        const a = exported();
                        const { tableToExcel } = await import("../lib/office");
                        return [`${safeFileName(a.question)}.xlsx`, await tableToExcel(table, a, officeText(m))];
                      }} />
      )}
    </div>
  );
}

/** A download made in the browser (Word or Excel); says so if it fails. */
function OfficeButton({ kind, label, what, make }: {
  kind: "word" | "excel"; label: string; what: string; make: () => Promise<[string, Blob]>;
}) {
  const m = useT();
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const run = async () => {
    setState("busy");
    try {
      const [name, blob] = await make();
      const { saveBlob } = await import("../lib/office");
      saveBlob(name, blob);
      setState("idle");
    } catch {
      setState("failed");
    }
  };
  return (
    <Button variant="plain" className="copy-button" aria-label={what} title={what} onPress={run} isDisabled={state === "busy"}>
      {kind === "word" ? <FileText size={13} aria-hidden /> : <FileSpreadsheet size={13} aria-hidden />}
      <span aria-live="polite">{state === "busy" ? m.preparingDownload : state === "failed" ? m.downloadFailed : label}</span>
    </Button>
  );
}

function officeText(m: ReturnType<typeof useT>) {
  return {
    answeredOn: m.answeredOn, checkHeading: m.toCheck, sourcesHeading: m.sources, sourceRemoved: m.sourceRemoved,
    sourceColumn: m.sourceColumn, sheetTable: m.sheetTable, sheetSources: m.sources, sheetChecks: m.toCheck,
    columns: { n: m.columnNumber, document: m.columnDocument, where: m.columnWhere, passage: m.columnPassage },
    disclaimer: m.exportDisclaimer,
  };
}

/**
 * Facts in a cited sentence that the cited source doesn't contain (suveryn-tracker#11): a figure or date
 * from another source, or a name the source spells differently. One line per fact, once each.
 */
function CitationIssuesNote({ issues }: { issues: CitationIssue[] }) {
  const m = useT();
  const lines = [...new Set(issues.map((i) => m.citationIssue(i.n, i.item, i.found_in, i.written_as)))];
  return (
    <InlineNotice icon={<AlertTriangle size={14} />} tone="error">{lines.join(" ")}</InlineNotice>
  );
}

/**
 * Says how a calculated figure was made: by the server, exactly, from figures the model copied
 * from the sources (never the model's own arithmetic). Flags figures that aren't in the sources.
 */
function CalculationNote({ calc }: { calc: Calculation }) {
  const m = useT();
  if (calc.result === null) {
    return (
      <InlineNotice icon={<AlertCircle size={14} />} tone="error">{m.calcFailed(calc.expression, calc.error ?? "")}</InlineNotice>
    );
  }
  const missing = calc.figures_not_in_sources;
  return (
    <InlineNotice icon={missing.length ? <AlertCircle size={14} /> : <Calculator size={14} />} tone={missing.length ? "error" : "note"}>
      {m.calculatedBy} {calc.expression} = <strong>{calc.result}</strong>.
      {missing.length > 0 ? m.calcMissing(missing) : m.calcAllSourced}
    </InlineNotice>
  );
}

/**
 * The working indicator (suveryn-tracker#6): three small outlined rounded squares, like the brand mark,
 * bouncing in turn. Neutral colour; still for people who prefer reduced motion.
 */
function WaitingDots() {
  return <span className="waiting-dots" aria-hidden><i /><i /><i /></span>;
}
