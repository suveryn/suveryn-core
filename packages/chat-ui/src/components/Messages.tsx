import { AlertCircle } from "lucide-react";
import { Fragment, useState } from "react";
import type { Citation } from "../api";
import { citedNumbers, toBlocks } from "../lib/answer";
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

function SourceCard({ n, citation, filename }: { n: number; citation: Citation; filename: string }) {
  return (
    <div className="source-card" role="region" aria-label={`Source ${n}`}>
      <div className="source-head">
        <span className="label">Source {n}</span>
        <span className="source-file">{filename}</span>
        <span className="source-where">{citation.source?.location ?? (citation.source?.page ? `p. ${citation.source.page}` : "")}</span>
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
export function AssistantMessage({ turn, filenames }: { turn: AssistantTurn; filenames: Map<string, string> }) {
  const [open, setOpen] = useState<number | null>(null);
  const available = turn.citations.length;
  const cited = citedNumbers(turn.text, available);
  const nameOf = (c: Citation) => (c.source && filenames.get(c.source.document_id)) || "document";
  const toggle = (n: number) => setOpen((cur) => (cur === n ? null : n));

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
