/**
 * The two chip types, deliberately different components: attachment chips (outlined, on the
 * user's turn, show upload and review state) and citation chips (teal, under an answer, open a
 * source). The model badge is in ModelPicker.tsx.
 */
import { AlertTriangle, FileText, Loader2, X, XCircle } from "lucide-react";
import type { Citation } from "../api";
import { useT } from "../i18n";
import { Button, TextButton } from "../ui";
import { pageList, reviewHint } from "../lib/review";
import type { Attachment } from "../types";

/**
 * Attachment chip: a file the user attached to their own message. Outlined (bg fill, line
 * border), deliberately unlike the citation chip.
 */
export function AttachmentChip({ a, onRemove, onUseAsSource, onDelete }: {
  a: Attachment; onRemove?: () => void;
  /** For an upload that looks like sūveryn's own output (docs/design/sidebar.md §6): the person's two choices. */
  onUseAsSource?: () => void; onDelete?: () => void;
}) {
  const m = useT();
  const STATUS_LABEL: Record<Attachment["status"], string> = {
    uploading: m.uploading, queued: m.waiting, processing: m.reading, ready: "",
    needs_review: m.readyCheckNeeded, failed: m.couldntBeRead, noticed: m.originPending,
  };
  if (a.status === "noticed" && a.noticed) {
    // Read and stored, but not a source until the person says so; never blocked (cases.md decision 7).
    return (
      <span className="chip-attachment chip-noticed" role="group" aria-label={`${a.filename}: ${m.noticedTitle(a.noticed.kind)}`}>
        <span className="chip-noticed-head">
          <AlertTriangle size={13} aria-hidden />
          <span className="chip-name">{a.filename}</span>
          {onRemove && (
            <Button variant="plain" className="chip-remove" onPress={onRemove} aria-label={m.removeFile(a.filename)}>
              <X size={12} aria-hidden />
            </Button>
          )}
        </span>
        <span className="chip-noticed-title">{m.noticedTitle(a.noticed.kind)}</span>
        <span className="chip-noticed-line" title={a.noticed.line}>{m.noticedFound(a.noticed.line)}</span>
        <span className="chip-noticed-hint">{m.noticedHint}</span>
        {(onUseAsSource || onDelete) && (
          <span className="chip-noticed-actions">
            {onUseAsSource && <TextButton link onPress={onUseAsSource}>{m.useAsSource}</TextButton>}
            {onDelete && <TextButton onPress={onDelete}>{m.delete}</TextButton>}
          </span>
        )}
      </span>
    );
  }
  const busy = a.status === "uploading" || a.status === "queued" || a.status === "processing";
  const label = a.status === "needs_review" && a.reviewPages?.length ? m.readyCheckPages(pageList(a.reviewPages)) : STATUS_LABEL[a.status];
  const title = a.status === "needs_review" ? `${a.filename}: ${reviewHint(a.reviewPages)}` : (a.error ?? a.filename);
  if (a.removed) {  // the document was deleted and its name taken out (suveryn-tracker#12)
    return <span className="chip-attachment chip-removed"><XCircle size={12} aria-hidden /><span className="chip-name">{m.documentRemoved}</span></span>;
  }
  return (
    <span className="chip-attachment" title={title}>
      {busy ? <Loader2 size={12} className="spin" aria-hidden /> :
        a.status === "failed" ? <XCircle size={12} aria-hidden /> :
        a.status === "needs_review" || a.status === "noticed" ? <AlertTriangle size={12} aria-hidden /> :
        <FileText size={12} aria-hidden />}
      <span className="chip-name">{a.filename}</span>
      {label && (
        <span className="chip-status">
          {a.status === "uploading" && a.progress !== undefined ? m.uploadingPercent(Math.floor(a.progress * 100)) : label}
        </span>
      )}
      {onRemove && (
        <Button variant="plain" className="chip-remove" onPress={onRemove} aria-label={m.removeFile(a.filename)}>
          <X size={12} aria-hidden />
        </Button>
      )}
    </span>
  );
}

/** Citation chip: marks a sourced passage. teal-ink text and icon on a translucent teal wash. */
export function CitationChip({ n, citation, filename, active, onClick }: {
  n: number; citation: Citation; filename: string; active: boolean; onClick: () => void;
}) {
  const m = useT();
  const page = citation.source?.page;
  return (
    <Button variant="plain" className={`chip-citation${active ? " active" : ""}${citation.removed ? " chip-removed" : ""}`} onPress={onClick}
            aria-expanded={active} aria-label={m.sourceLabel(n, filename, page)}>
      <span className="cite-num">{n}</span>
      <FileText size={12} aria-hidden />
      {filename}{page ? `, ${m.pageShort(page)}` : ""}
    </Button>
  );
}

/** Model tag in the composer: neutral on purpose (teal is reserved for citations). */
