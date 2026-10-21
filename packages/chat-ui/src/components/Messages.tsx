/**
 * The conversation turns. Only the user's turn has a bubble; the assistant's reply has none and is
 * marked by the teal brand-mark outline. Model output is rendered as React text only (lib/answer.ts),
 * never as HTML. Under an answer: the cited sources, copy and download, calculation notes and the
 * "not sourced" notices that tell a reader what to check. A citation opens its passage in the source
 * panel beside the conversation (``SourcePanel``, docs/design/sidebar.md §5, artboard 11).
 */
import { AlertCircle, AlertTriangle, Brain, Calculator, Check, ChevronLeft, ChevronRight, Copy, Download, FileSpreadsheet, FileText, Files, FolderInput, Square, X } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState } from "react";
import { Button, IconButton, InlineNotice, MenuButton, SplitButton, TextButton, Toolbar } from "../ui";
import type { Calculation, Citation, CitationIssue } from "../api";
import { lang, useT } from "../i18n";
import { citedNumbers, claimTerms, claimTexts, markerClaims, markPassage, stripMarkers, termsOf, toBlocks, type Segment, type Table } from "../lib/answer";
import type { AnswerExport } from "../lib/export";
import { rememberFormat, useFormat, type FormatKind } from "../lib/downloadFormat";
import { answerExport, officeText } from "../lib/saved";
import { useWatermark, withWatermark } from "../lib/watermark";
import { verdictOf } from "../lib/sources";
import { statusText } from "../lib/status";
import { thoughtTime } from "../lib/thinking";
import {
  copyText, downloadText, formatSource, formatSourceMarkdown, formatSources, safeFileName, sourceFileName,
  sourcesDocument, sourcesMarkdown, type Format,
} from "../lib/copy";
import type { AssistantTurn, UserTurn } from "../types";
import { AssistantMark } from "./Brand";
import { AttachmentChip, CitationChip } from "./Chips";

/** The user's turn: attachment chips above a bubble (the only bubble in the conversation). */
export function UserMessage({ turn }: { turn: UserTurn }) {
  const m = useT();
  // What the question was asked about (§10), so whoever reads the conversation knows what each answer read.
  const about = (turn.about ?? []).map((c) => (c.removed ? m.sourceRemoved : c.filename));
  return (
    <div className="turn-user">
      {turn.attachments.length > 0 && (
        <div className="attachments">{turn.attachments.map((a) => <AttachmentChip key={a.key} a={a} />)}</div>
      )}
      {turn.text && <div className="bubble">{turn.text}</div>}
      {about.length > 0 && (
        <p className="asked-about"><Files size={12} aria-hidden /><span>{m.askAbout} <b>{about.join(", ")}</b></span></p>
      )}
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
  const mark = useWatermark();  // a strictly confidential case: the watermark is the first line (§11)
  return (
    <MenuButton className="copy-button" aria-label={m.downloadWhat(what)} menuLabel={m.download}
                items={[{ id: "txt", label: m.textFile }, { id: "md", label: m.markdownFile }]} placement="bottom end"
                onAction={(f) => downloadText(filename(f as Format), withWatermark(text(f as Format), mark()))}>
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

/** The id of the source panel: the open citation marker points at it (``aria-controls``). */
export const SOURCE_PANEL = "source-panel";

/** A citation's file name as shown: "Source removed" for a deleted document's, "Unnamed document" if unknown. */
export function sourceName(c: Citation, filenames: Map<string, string>, m: ReturnType<typeof useT>): string {
  return c.removed ? m.sourceRemoved : (c.source && filenames.get(c.source.document_id)) || m.unnamedDocument;
}

/** What the passage says for the claim(s) that cite it: the claim of the marker opened, or every claim citing ``n``. */
function passageMarks(turn: AssistantTurn, n: number, occ: number | null) {
  const available = turn.citations.length;
  const one = occ === null ? undefined : markerClaims(turn.text, available)[occ];
  return one?.n === n ? { terms: termsOf(one.claim), claims: [one.claim] }
    : { terms: claimTerms(turn.text, available).get(n) ?? [], claims: claimTexts(turn.text, available).get(n) ?? [] };
}

/**
 * The source panel (docs/design/sidebar.md §5, artboard 11): one source of an answer beside the
 * conversation. The file, the page and the case; previous and next between the answer's sources; the
 * passage, with the sentences the claim rests on in a teal wash and the rest dimmed; what the check
 * found, in words; *Copy passage* and the download. Esc closes it (from inside it, or anywhere when no
 * answer is being written: App), and the focus goes back to what opened it.
 *
 * Not here: *Open document at p. 3*. sūveryn keeps a document's text, not the file it was read from,
 * so there is no page to open (docs/design/sidebar.md, "Resolved while building").
 */
export function SourcePanel({ turn, open, filenames, caseRef, onSource, onClose }: {
  turn: AssistantTurn; open: OpenSource; filenames: Map<string, string>; caseRef: string | null;
  onSource: (s: OpenSource) => void; onClose: () => void;
}) {
  const m = useT();
  const here = useRef<HTMLElement>(null);
  const opener = useRef<Element | null>(null);
  const { n, occ } = open;
  // The focus moves into the panel when a citation outside it opens a source, and back to the last
  // such citation when the panel closes.
  useEffect(() => {
    const from = document.activeElement;
    if (here.current && !here.current.contains(from)) {
      opener.current = from;
      here.current.focus();
    }
  }, [n, occ]);
  useEffect(() => () => { if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus(); }, []);
  const quote = useRef<HTMLQuoteElement>(null);
  const available = turn.citations.length;
  const cited = citedNumbers(turn.text, available);
  const citation = turn.citations[n - 1];
  const at = cited.indexOf(n);
  const filename = sourceName(citation, filenames, m);
  const { terms, claims } = passageMarks(turn, n, occ);
  // Scroll the passage (not the page) to the first marked sentence: a long passage shows only its start.
  useEffect(() => {
    const box = quote.current, first = box?.querySelector("mark");
    if (box && first instanceof HTMLElement) box.scrollTop = Math.max(0, first.offsetTop - box.clientHeight / 3);
  }, [n, occ]);
  const found = verdictOf(turn, n, occ);
  const verdict = found === null ? null
    : found.kind === "unchecked" ? { ok: false, text: m.verdictUnchecked }
    : found.kind === "issues" ? { ok: false, text: [...new Set(found.issues.map((i) => m.citationIssue(i.n, i.item, i.found_in, i.written_as)))].join(" ") }
    : { ok: true, text: found.kind === "source" ? m.verdictSource : m.verdictSentence };
  const go = (to: number) => onSource({ n: cited[to], occ: null });

  return (
    <aside id={SOURCE_PANEL} className="source-panel" aria-label={m.source(n)} ref={here} tabIndex={-1}
           onKeyDown={(e) => { if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); onClose(); } }}>
      <header className="source-panel-head">
        <span className="cite-num source-panel-num" aria-hidden>{n}</span>
        <span className="source-panel-title">
          <span className="source-panel-file">{filename}</span>
          <span className="source-panel-where">{m.sourcePlace(citation.source?.page ?? null, caseRef)}</span>
        </span>
        {cited.length > 1 && at >= 0 && <>
          <IconButton size="small" label={m.previousSource} isDisabled={at === 0} onPress={() => go(at - 1)}><ChevronLeft size={16} aria-hidden /></IconButton>
          <span className="source-panel-count">{m.sourceOf(at + 1, cited.length)}</span>
          <IconButton size="small" label={m.nextSource} isDisabled={at === cited.length - 1} onPress={() => go(at + 1)}><ChevronRight size={16} aria-hidden /></IconButton>
        </>}
        <IconButton size="small" label={m.closeSource} onPress={onClose}><X size={16} aria-hidden /></IconButton>
      </header>
      <div className="source-panel-body">
        {citation.removed ? <p className="caption">{m.sourceRemovedCaption}</p> : <>
          <blockquote className="source-panel-text" ref={quote}>
            {markPassage(citation.text, claims, terms).map((part, i) => (part.mark
              ? <mark key={i} className={part.mark === "term" ? "source-match" : "source-span"}>{part.text}</mark>
              : <Fragment key={i}>{part.text}</Fragment>))}
          </blockquote>
          {verdict && (
            <p className="source-panel-verdict" data-ok={verdict.ok || undefined}>
              {verdict.ok ? <Check size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
              <span>{verdict.text}</span>
            </p>
          )}
          <p className="caption">{m.sourceCaption}</p>
        </>}
      </div>
      {!citation.removed && (
        <footer className="source-panel-actions">
          <CopyButton text={formatSource(n, citation, filename)} label={m.copyPassage} what={m.passageWhat(n)} />
          <DownloadButton filename={(f) => sourceFileName(n, filename, citation.source?.page, f)} what={m.sourceN(n)}
                          text={(f) => (f === "md" ? formatSourceMarkdown(n, citation, filename) : formatSource(n, citation, filename)) + "\n"} />
        </footer>
      )}
    </aside>
  );
}

/**
 * The assistant's turn: no bubble, marked by the teal brand-mark outline. Citation markers [n]
 * become buttons that open the source (citations[n-1]); only cited sources are listed below.
 */
/** Saving an answer to its case (docs/design/sidebar.md §5): only in a case, for a contributor. */
export type SaveToCase = {
  caseRef: string;
  saved: { documentId: string; filename: string } | null;  // saved, and still in the case
  undoable: boolean;                                       // saved during this visit: Undo is offered
  onSave: () => Promise<void>;
  onOpen: () => void;
  onUndo: () => Promise<void>;
};

/** The source open in the panel: its number and, opened from a marker, which marker (``occ``), so the
 *  panel shows what that claim rests on; null from the source list: every claim citing it. */
export type OpenSource = { n: number; occ: number | null };

/** "Thought for 14 s" above a *Thorough* answer (§5): a button that opens the reasoning, which is
 *  never checked the way the answer is, and says so. Not in Copy or the downloads. */
function ThoughtFor({ reasoning, seconds }: { reasoning: string; seconds?: number }) {
  const m = useT();
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <div className="answer-thought">
      <Button variant="plain" className="answer-thought-toggle" aria-expanded={open} aria-controls={panel} onPress={() => setOpen(!open)}>
        <Brain size={13} aria-hidden />
        <span>{seconds !== undefined ? m.thoughtFor(thoughtTime(seconds)) : m.reasoningLabel}</span>
        <ChevronRight size={13} aria-hidden className="answer-thought-chevron" />
      </Button>
      {open && (
        <div id={panel} className="answer-thought-body">
          <p className="caption">{m.reasoningNote}</p>
          {reasoning.split(/\n{2,}/).map((para, i) => <p key={i}>{para}</p>)}
        </div>
      )}
    </div>
  );
}

export function AssistantMessage({ turn, question, filenames, caseRef = null, save = null, source = null, onSource, onRegenerate = null }: {
  turn: AssistantTurn; question: string; filenames: Map<string, string>;
  /** The case the conversation is in (null: personal), named in the export mark. */
  caseRef?: string | null;
  save?: SaveToCase | null;
  /** This answer's source open in the panel, if any; ``onSource`` opens one (or closes it, pressed again). */
  source?: OpenSource | null;
  onSource: (s: OpenSource) => void;
  /** A failed or cut-off answer, the last one: ask the same question again. */
  onRegenerate?: (() => void) | null;
}) {
  const m = useT();
  const open = source?.n ?? null;
  const openOcc = source?.occ ?? null;
  const available = turn.citations.length;
  const cited = citedNumbers(turn.text, available);
  const nameOf = (c: Citation) => sourceName(c, filenames, m);
  const toggle = (n: number, occ: number | null = null) => onSource({ n, occ });
  // Copy and download only what is still there: a deleted document's passage was taken out.
  const citedItems = cited.filter((n) => !turn.citations[n - 1].removed)
    .map((n) => ({ n, citation: turn.citations[n - 1], filename: nameOf(turn.citations[n - 1]) }));
  const allSources = formatSources(citedItems);
  // The documents cited, each once, in the order the answer first cites them.
  const basis = [...new Map(citedItems.map((i) => [i.citation.source?.document_id ?? i.filename, i.filename])).values()];
  const flagged = turn.unverifiedFigures ?? [];
  // A stopped answer keeps its markers and the passages they point to, but was never checked.
  const settled = turn.status === "done" || turn.status === "stopped";
  const issues = turn.status === "done" ? turn.citationIssues ?? [] : [];
  const flaggedMarkers = new Set(issues.map((i) => i.marker));
  const blocks = toBlocks(turn.text, settled ? available : 0, turn.status === "done" ? flagged : []);
  // Word and Excel downloads carry the same warnings and sources as the chat (lib/saved.ts).
  const mark = useWatermark();
  const exported = (): AnswerExport => answerExport(turn, question, nameOf, m, caseRef, new Date(), mark());
  const render = (segments: Segment[]) => segments.map((s, j) =>
    s.kind === "text" ? <Fragment key={j}>{s.text}</Fragment> :
    s.kind === "bold" ? <strong key={j}>{s.text}</strong> :
    s.kind === "flag" ? <mark key={j} className="unverified" title={m.unverifiedTitle}>
                          {s.bold ? <strong>{s.text}</strong> : s.text}</mark> :
    <Button key={j} variant="plain" className={`cite-marker${open === s.n && (openOcc === null || openOcc === s.occ) ? " active" : ""}${flaggedMarkers.has(s.occ) ? " flagged" : ""}`}
            aria-controls={open === s.n ? SOURCE_PANEL : undefined}
            onPress={() => toggle(s.n, s.occ)} aria-expanded={open === s.n && (openOcc === null || openOcc === s.occ)}
            title={flaggedMarkers.has(s.occ) ? m.citationIssueTitle : undefined}
            aria-label={m.sourceLabel(s.n, nameOf(turn.citations[s.n - 1]), null)
                        + (flaggedMarkers.has(s.occ) ? `. ${m.citationIssueTitle}` : "")}>{s.n}</Button>);

  if (turn.status === "error") {
    // A cut-off answer keeps what arrived, unchecked, and says so under its last word (§5, artboard 09);
    // any other failure shows nothing of the attempt (the gateway's contract).
    return (
      <div className="turn-assistant">
        <AssistantMark />
        <div className="answer">
          {turn.cutOff && blocks.map((b, i) => (b.kind === "table"
            ? <AnswerTable key={i} table={b} render={render} done={false} exported={exported} />
            : b.kind === "li" ? <li key={i}>{render(b.segments)}</li> : <p key={i}>{render(b.segments)}</p>))}
          <p className="answer-failed">
            <AlertCircle size={14} aria-hidden />
            <span>{turn.cutOff ? m.answerCutOff : m.answerFailed(turn.error ?? "")}</span>
            {onRegenerate && <Button size="small" onPress={onRegenerate} title={m.regenerateWhat}>{m.regenerate}</Button>}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="turn-assistant">
      <AssistantMark />
      {/* still live when stopped, so the notice that it stopped is read out */}
      <div className="answer" aria-live={turn.status === "streaming" || turn.status === "stopped" ? "polite" : undefined}>
        {/* Thorough (§5): what the model thought, collapsed, once the answer has begun */}
        {turn.reasoning && (turn.text || settled) && <ThoughtFor reasoning={turn.reasoning} seconds={turn.thoughtSeconds} />}
        {/* Which documents the answer rests on, before it (docs/design/sidebar.md §5): in a case, a fact
            from the wrong deed shows at a glance (Pod check of 705b91d). */}
        {settled && basis.length > 0 && (
          <p className="answer-basis"><FileText size={13} aria-hidden /><span>{m.basedOn(basis.length, basis.join(", "))}</span></p>
        )}
        {settled && turn.partial && <InlineNotice icon={<AlertCircle size={14} />}>{m.partialRead}</InlineNotice>}
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

        {turn.status === "stopped" && (
          <InlineNotice icon={<Square size={12} fill="currentColor" strokeWidth={0} />}>{m.answerStopped}</InlineNotice>
        )}


        {settled && cited.length > 0 && (
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

        {turn.status === "done" && turn.text && (
          <Toolbar label={m.answerActions} className="answer-actions">
            <CopyButton label={m.copy} what={m.answerWithSources}
                        text={[stripMarkers(turn.text), allSources].filter(Boolean).join("\n\n")} />
            <DownloadFormats kind="answer"
                             formats={[{ id: "docx", label: m.downloadWord, what: mark() ? m.downloadWordWhatConfidential : m.downloadWordWhat },
                                       { id: "md", label: m.markdownFile, what: m.downloadMarkdownWhat }]}
                             make={async (format) => {
                               const name = `${safeFileName(question)}.${format}`;
                               if (format === "md") {
                                 const { answerToMarkdown } = await import("../lib/textfiles");
                                 return [name, new Blob([answerToMarkdown(exported(), officeText(m), lang())], { type: "text/markdown;charset=utf-8" })];
                               }
                               const { answerToWord } = await import("../lib/office");
                               return [name, await answerToWord(exported(), officeText(m), lang())];
                             }} />
            {save && <SaveToCaseActions save={save} />}
          </Toolbar>
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
        <DownloadFormats kind="table"
                         formats={[{ id: "xlsx", label: m.downloadExcel, what: m.downloadExcelWhat },
                                   { id: "csv", label: m.csvFile, what: m.downloadCsvWhat }]}
                         make={async (format) => {
                           const a = exported(), name = `${safeFileName(a.question)}.${format}`;
                           if (format === "csv") {
                             const { tableToCsv } = await import("../lib/textfiles");
                             return [name, new Blob([tableToCsv(table, officeText(m), a.watermark)], { type: "text/csv;charset=utf-8" })];
                           }
                           const { tableToExcel } = await import("../lib/office");
                           return [name, await tableToExcel(table, a, officeText(m))];
                         }} />
      )}
    </div>
  );
}

/**
 * A download made in the browser, as a split button (docs/design/sidebar.md §6, "Other formats"): the
 * word makes the person's default format; the chevron's menu offers both, and the one chosen becomes
 * the default (lib/downloadFormat.ts). Says so if the file can't be made.
 */
function DownloadFormats({ kind, formats, make }: {
  kind: FormatKind; formats: { id: string; label: string; what: string }[]; make: (format: string) => Promise<[string, Blob]>;
}) {
  const m = useT();
  const preferred = useFormat(kind);
  const current = formats.find((f) => f.id === preferred) ?? formats[0];
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  // Not disabled while busy: a disabled button loses the focus, which would drop to the page.
  const run = async (format: string) => {
    if (state === "busy") return;
    setState("busy");
    try {
      const [name, blob] = await make(format);
      const { saveBlob } = await import("../lib/office");
      saveBlob(name, blob);
      setState("idle");
    } catch {
      setState("failed");
    }
  };
  const Icon = kind === "table" ? FileSpreadsheet : FileText;
  return (
    <SplitButton className="copy-button" label={current.what} onPress={() => run(current.id)}
                 moreLabel={m.otherFormats} menuLabel={m.downloadFormat} selected={current.id}
                 items={formats.map(({ id, label }) => ({ id, label }))}
                 onAction={(id) => { rememberFormat(kind, id as never); void run(id); }}>
      <Icon size={13} aria-hidden />
      <span aria-live="polite">{state === "busy" ? m.preparingDownload : state === "failed" ? m.downloadFailed : current.label}</span>
    </SplitButton>
  );
}

/**
 * *Save to case*, then "✓ Saved to case 123 as <file>.docx" with *Open* and, during this visit, *Undo*
 * (docs/design/sidebar.md §5, artboard 16). The focus follows: to *Open* once saved, back to *Save to
 * case* after Undo, so a keyboard user isn't left on a button that disappeared.
 */
function SaveToCaseActions({ save }: { save: SaveToCase }) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const here = useRef<HTMLSpanElement>(null);
  const moved = useRef(false);
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    here.current?.querySelector("button")?.focus();
  }, [save.saved]);
  const act = async (what: () => Promise<void>) => {
    setBusy(true);
    try { await what(); moved.current = true; } finally { setBusy(false); }
  };
  return (
    <span className="save-to-case" ref={here}>
      {save.saved ? (<>
        <span role="status" className="saved-note">
          <Check size={13} aria-hidden /> {m.savedToCase(save.caseRef)} <strong>{save.saved.filename}</strong>
        </span>
        <TextButton link onPress={save.onOpen}>{m.openSaved}</TextButton>
        {save.undoable && <TextButton isDisabled={busy} onPress={() => act(save.onUndo)}>{m.undoSave}</TextButton>}
      </>) : (
        <Button variant="plain" className="copy-button" isDisabled={busy} onPress={() => act(save.onSave)}
                aria-label={m.saveToCaseWhat(save.caseRef)} title={m.saveToCaseWhat(save.caseRef)}>
          <FolderInput size={13} aria-hidden /><span aria-live="polite">{busy ? m.savingToCase : m.saveToCase}</span>
        </Button>
      )}
    </span>
  );
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
