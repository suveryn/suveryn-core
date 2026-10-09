import { AlertTriangle, Cpu, FileText, Loader2, X, XCircle } from "lucide-react";
import type { Citation } from "../api";
import { modelName } from "../lib/model";
import type { Attachment } from "../types";

const STATUS_LABEL: Record<Attachment["status"], string> = {
  uploading: "Uploading…",
  queued: "Waiting…",
  processing: "Reading…",
  ready: "",
  needs_review: "Check needed",
  failed: "Couldn't be read",
};

/**
 * Attachment chip: a file the user attached to their own message. Outlined (bg fill, line
 * border), deliberately unlike the citation chip.
 */
export function AttachmentChip({ a, onRemove }: { a: Attachment; onRemove?: () => void }) {
  const busy = a.status === "uploading" || a.status === "queued" || a.status === "processing";
  return (
    <span className="chip-attachment" title={a.error ?? a.filename}>
      {busy ? <Loader2 size={12} className="spin" aria-hidden /> :
        a.status === "failed" ? <XCircle size={12} aria-hidden /> :
        a.status === "needs_review" ? <AlertTriangle size={12} aria-hidden /> :
        <FileText size={12} aria-hidden />}
      <span className="chip-name">{a.filename}</span>
      {STATUS_LABEL[a.status] && (
        <span className="chip-status">
          {a.status === "uploading" && a.progress !== undefined ? `Uploading… ${Math.floor(a.progress * 100)}%` : STATUS_LABEL[a.status]}
        </span>
      )}
      {onRemove && (
        <button type="button" className="chip-remove" onClick={onRemove} aria-label={`Remove ${a.filename}`}>
          <X size={12} />
        </button>
      )}
    </span>
  );
}

/** Citation chip: marks a sourced passage. teal-ink text and icon on a translucent teal wash. */
export function CitationChip({ n, citation, filename, active, onClick }: {
  n: number; citation: Citation; filename: string; active: boolean; onClick: () => void;
}) {
  const page = citation.source?.page;
  return (
    <button type="button" className={`chip-citation${active ? " active" : ""}`} onClick={onClick}
            aria-expanded={active} aria-label={`Source ${n}: ${filename}${page ? `, page ${page}` : ""}`}>
      <span className="cite-num">{n}</span>
      <FileText size={12} aria-hidden />
      {filename}{page ? `, p.${page}` : ""}
    </button>
  );
}

/** Model tag in the composer: neutral on purpose (teal is reserved for citations). */
export function ModelTag({ file }: { file: string | null }) {
  const name = modelName(file);
  if (!name) return null;
  return (
    <span className="chip-model" title={`Answers come from ${name.full}, running on this server`}>
      <Cpu size={12} aria-hidden />
      <span className="model-full">{name.full}</span>
      <span className="model-family">{name.family}</span>
    </span>
  );
}
