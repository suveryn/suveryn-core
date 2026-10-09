import { AlertCircle, Check, ChevronDown, Copy, Download } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import type { Citation } from "../api";
import { citedNumbers, toBlocks } from "../lib/answer";
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
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(t);
  }, [state]);
  return (
    <button type="button" className="copy-button" aria-label={`Copy ${what}`}
            onClick={async () => setState((await copyText(text)) ? "copied" : "failed")}>
      {state === "copied" ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
      <span aria-live="polite">{state === "copied" ? "Copied" : state === "failed" ? "Couldn't copy" : label}</span>
    </button>
  );
}

/** A small ghost button with a menu: save as plain text (.txt) or Markdown (.md). */
function DownloadButton({ filename, text, what }: {
  filename: (format: Format) => string; text: (format: Format) => string; what: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  const save = (format: Format) => { downloadText(filename(format), text(format)); setOpen(false); };
  return (
    <span className="download" ref={root}>
      <button type="button" className="copy-button" aria-haspopup="menu" aria-expanded={open}
              aria-label={`Download ${what}`} onClick={() => setOpen((o) => !o)}>
        <Download size={13} aria-hidden />
        <span>Download</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <span className="download-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => save("txt")}>Text (.txt)</button>
          <button type="button" role="menuitem" onClick={() => save("md")}>Markdown (.md)</button>
        </span>
      )}
    </span>
  );
}

function SourceCard({ n, citation, filename }: { n: number; citation: Citation; filename: string }) {
  return (
    <div className="source-card" role="region" aria-label={`Source ${n}`}>
      <div className="source-head">
        <span className="label">Source {n}</span>
        <span className="source-file">{filename}</span>
        <span className="source-where">{citation.source?.location ?? (citation.source?.page ? `p. ${citation.source.page}` : "")}</span>
        <span className="source-actions">
          <CopyButton text={formatSource(n, citation, filename)} label="Copy" what={`source ${n} with its reference`} />
          <DownloadButton filename={(f) => sourceFileName(n, filename, citation.source?.page, f)} what={`source ${n}`}
                          text={(f) => (f === "md" ? formatSourceMarkdown(n, citation, filename) : formatSource(n, citation, filename)) + "\n"} />
        </span>
      </div>
      <blockquote className="source-text">{citation.text}</blockquote>
      <p className="caption">The passage as it was read from the document. Check the original page before relying on it.</p>
    </div>
  );
}

/**
 * The assistant's turn: no bubble, marked by the teal brand-mark outline. Citation markers [n]
 * become buttons that open the source (citations[n-1]); only cited sources are listed below.
 */
export function AssistantMessage({ turn, question, filenames }: {
  turn: AssistantTurn; question: string; filenames: Map<string, string>;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const available = turn.citations.length;
  const cited = citedNumbers(turn.text, available);
  const nameOf = (c: Citation) => (c.source && filenames.get(c.source.document_id)) || "document";
  const toggle = (n: number) => setOpen((cur) => (cur === n ? null : n));
  const citedItems = cited.map((n) => ({ n, citation: turn.citations[n - 1], filename: nameOf(turn.citations[n - 1]) }));
  const allSources = formatSources(citedItems);

  if (turn.status === "error") {
    return (
      <div className="turn-assistant">
        <AssistantMark />
        <div className="answer">
          <p className="notice notice-error"><AlertCircle size={14} aria-hidden />
            The answer couldn't be completed: {turn.error}. Nothing from this attempt is shown, so ask again.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="turn-assistant">
      <AssistantMark />
      <div className="answer" aria-live={turn.status === "streaming" ? "polite" : undefined}>
        {toBlocks(turn.text, turn.status === "done" ? available : 0).map((b, i) => {
          const body = b.segments.map((s, j) =>
            s.kind === "text" ? <Fragment key={j}>{s.text}</Fragment> :
            s.kind === "bold" ? <strong key={j}>{s.text}</strong> :
            <button key={j} type="button" className={`cite-marker${open === s.n ? " active" : ""}`}
                    onClick={() => toggle(s.n)} aria-expanded={open === s.n}
                    aria-label={`Source ${s.n}: ${nameOf(turn.citations[s.n - 1])}`}>{s.n}</button>);
          return b.kind === "li" ? <li key={i}>{body}</li> : <p key={i}>{body}</p>;
        })}
        {turn.status === "streaming" && <span className="caret" aria-hidden />}

        {turn.status === "done" && open !== null && turn.citations[open - 1] && (
          <SourceCard n={open} citation={turn.citations[open - 1]} filename={nameOf(turn.citations[open - 1])} />
        )}

        {turn.status === "done" && cited.length > 0 && (
          <div className="sources">
            <span className="label">Sources</span>
            {cited.map((n) => (
              <CitationChip key={n} n={n} citation={turn.citations[n - 1]} filename={nameOf(turn.citations[n - 1])}
                            active={open === n} onClick={() => toggle(n)} />
            ))}
            <CopyButton label="Copy sources" what="all cited sources" text={allSources} />
            <DownloadButton filename={(f) => `sources_${safeFileName(question)}.${f}`} what="all cited sources"
                            text={(f) => (f === "md" ? sourcesMarkdown(question, citedItems, new Date())
                                                     : sourcesDocument(question, allSources, new Date()))} />
          </div>
        )}

        {turn.status === "done" && cited.length === 0 && (
          <p className="notice"><AlertCircle size={14} aria-hidden />
            {turn.grounded
              ? "No source is cited for this answer. Check it against the documents before relying on it."
              : "Not based on your documents. Attach a document to get answers that cite their source."}
          </p>
        )}
      </div>
    </div>
  );
}
