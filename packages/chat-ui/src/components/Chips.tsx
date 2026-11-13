/**
 * The two chip types, deliberately different components: attachment chips (outlined, on the
 * user's turn, show upload and review state) and citation chips (teal, under an answer, open a
 * source). The model badge is in ModelPicker.tsx.
 */
import { Check, CircleX, FileOutput, FileText, LoaderCircle, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { locale, useT } from "../i18n";
import { markOrigin } from "../lib/marks";
import { Button, Dialog, FileButton, IconButton, Progress, TextButton } from "../ui";
import { ACCEPTED_FILES } from "../lib/formats";
import { failureText, pageList, reviewHint } from "../lib/review";
import type { Attachment } from "../types";

/**
 * An attachment in the composer, as a card (docs/design/chat-ui.md §5, artboard 13): one shape for every
 * state, × at the top right. Reading: a bar (the upload's share, then indeterminate while the server
 * reads it). Ready: a check and the pages. Usable with a warning: the pages to check. Failed: why, and
 * *Another file*. sūveryn's own output: §6. A question can be sent while one is still read: it counts
 * for the next question once it is ready.
 */
export function AttachmentCard({ a, onRemove, onUseAsSource, onDelete, onReplace, inCase }: {
  a: Attachment; onRemove: () => void;
  onUseAsSource?: () => void; onDelete?: () => void;
  /** In a case, the delete link says where it deletes from ("Uit dossier verwijderen"). */
  inCase?: boolean;
  /** Failed: choose another file in its place. */
  onReplace?: (files: File[]) => void;
}) {
  const m = useT();
  const busy = a.status === "uploading" || a.status === "queued" || a.status === "processing";
  const icon = a.status === "failed" ? <CircleX size={14} aria-hidden />
    : a.status === "noticed" ? <FileOutput size={14} aria-hidden /> : <FileText size={14} aria-hidden />;
  // While the server reads it: page by page during text recognition, then the layout, then storing.
  const r = a.status === "processing" ? a.reading : null;
  const state = a.status === "uploading" ? m.cardUploading({ pct: Math.floor((a.progress ?? 0) * 100) })
    : a.status === "queued" ? m.cardWaiting
    // the pages done, not the one being worked on (board G13); none done yet: no count
    : r?.step === "ocr" && r.done !== null && r.total ? (r.done > 0 ? m.cardRecognising({ done: Math.min(r.done, r.total), total: r.total }) : m.cardRecognisingStart)
    : r?.step === "layout" ? (r.total ? m.cardLayoutPages({ n: r.total }) : m.cardLayout) : r?.step === "store" ? m.cardStoring
    : a.status === "processing" ? m.cardReading : null;
  const value = a.status === "uploading" && a.progress !== undefined ? a.progress * 100
    : r?.step === "ocr" && r.done !== null && r.total ? (r.done / r.total) * 100 : undefined;
  const why = failureText(m, a.errorCode, a.errorDetail, a.error);
  return (
    <li className="card-attachment" data-state={a.status} aria-busy={busy || undefined}>
      <span className="card-attachment-top">
        {icon}
        <span className="card-attachment-name" title={a.filename}>{a.filename}</span>
        <IconButton size="small" onPress={onRemove}
                    label={busy ? m.cancelUpload({ file: a.filename }) : a.status === "failed" ? m.removeFile({ file: a.filename }) : m.removeFromQuestion({ file: a.filename })}>
          <X size={14} aria-hidden />
        </IconButton>
      </span>
      {busy && state && (
        <>
          <Progress label={state} value={value} />
          <span className="card-attachment-state">{state}</span>
        </>
      )}
      {a.status === "ready" && (
        <span className="card-attachment-state" data-tone="ok"><Check size={14} aria-hidden />{[m.cardReady, a.pages ? m.pages({ n: a.pages }) : ""].filter(Boolean).join(" · ")}</span>
      )}
      {a.status === "needs_review" && (
        <span className="card-attachment-state" data-tone="warn" role="status" title={a.note ? undefined : reviewHint(a.reviewPages)}>
          <TriangleAlert size={14} aria-hidden />{a.note ?? (a.reviewPages?.length
            ? m.cardCheckWhy({ pages: pageList(a.reviewPages), why: a.reviewKind ?? "" })
            : m.cardCheckNeeded)}
        </span>
      )}
      {a.status === "failed" && <>
        <span className="card-attachment-state" data-tone="warn">{[a.notAdded ? m.cardNotAdded : m.cardFailed, why].filter(Boolean).join(" ")}</span>
        {(onReplace || onDelete) && (
          <span className="card-attachment-actions">
            {onReplace && (
              <FileButton accept={ACCEPTED_FILES} onSelect={onReplace}>
                <Button size="small" aria-label={m.chooseAnotherFile({ file: a.filename })}>{m.anotherFile}</Button>
              </FileButton>
            )}
            {onDelete && <DeleteUploadLink filename={a.filename} inCase={inCase} onDelete={onDelete} />}
          </span>
        )}
      </>}
      {a.status === "noticed" && a.noticed && <>
        {/* board G13: where it came from, and that it isn't a source; one button. The × only takes it out of the question
            (it never deletes, 9 November); deleting is the worded link, after a confirmation. */}
        <span className="card-attachment-state" data-tone="warn" title={a.noticed.line}>{m.noticedTitle({ kind: a.noticed.kind })}{noticedFrom(a.noticed.line, m)}. {m.cardNoticedNotSource}</span>
        {(onUseAsSource || onDelete) && (
          <span className="card-attachment-actions">
            {onUseAsSource && <Button size="small" onPress={onUseAsSource}>{m.useAsSource}</Button>}
            {onDelete && <DeleteUploadLink filename={a.filename} inCase={inCase} onDelete={onDelete} />}
          </span>
        )}
      </>}
    </li>
  );
}

/** Board G13: deleting an upload is a quiet worded link under the card's button, after a confirmation; the same
 *  on the card sūveryn recognised as its own and on the card that couldn't be read. The × never deletes. */
function DeleteUploadLink({ filename, inCase, onDelete }: { filename: string; inCase?: boolean; onDelete: () => void }) {
  const m = useT();
  const [deleting, setDeleting] = useState(false);
  return <>
    <TextButton link className="card-attachment-delete" onPress={() => setDeleting(true)}>{inCase ? m.deleteUploadFromCase : m.deleteUpload}</TextButton>
    <Dialog isOpen={deleting} onClose={() => setDeleting(false)} kind="confirmation" risky title={m.deleteUploadTitle({ file: filename })}
            cancel={{ label: m.cancel }} primary={{ label: m.deleteUpload, onPress: () => { setDeleting(false); onDelete(); } }}>
      <p>{m.deleteUploadBody}</p>
    </Dialog>
  </>;
}

/**
 * Attachment chip: a file the user attached to their own message. Outlined (bg fill, line
 * border), deliberately unlike the citation chip.
 */
export function AttachmentChip({ a, onRemove, onUseAsSource, onDelete }: {
  a: Attachment; onRemove?: () => void;
  /** For an upload that looks like sūveryn's own output (docs/design/chat-ui.md §6): the person's two choices. */
  onUseAsSource?: () => void; onDelete?: () => void;
}) {
  const m = useT();
  const STATUS_LABEL: Record<Attachment["status"], string> = {
    uploading: m.uploading, queued: m.waiting, processing: m.reading, ready: "",
    needs_review: m.readyCheckNeeded, failed: m.couldntBeRead, noticed: m.originPending, cancelled: "",
  };
  if (a.status === "noticed" && a.noticed) {
    // Read and stored, but not a source until the person says so; never blocked (cases.md decision 7).
    return (
      <span className="chip-attachment chip-noticed" role="group" aria-label={`${a.filename}: ${m.noticedTitle({ kind: a.noticed.kind })}`}>
        <span className="chip-noticed-head">
          <TriangleAlert size={13} aria-hidden />
          <span className="chip-name">{a.filename}</span>
          {onRemove && (
            <Button variant="plain" className="chip-remove" onPress={onRemove} aria-label={m.removeFile({ file: a.filename })}>
              <X size={12} aria-hidden />
            </Button>
          )}
        </span>
        <span className="chip-noticed-title">{m.noticedTitle({ kind: a.noticed.kind })}</span>
        <span className="chip-noticed-line" title={a.noticed.line}>{m.noticedFound({ line: a.noticed.line })}</span>
        <span className="chip-noticed-hint">{m.noticedHint}</span>
        {(onUseAsSource || onDelete) && (
          <span className="chip-noticed-actions">
            {onUseAsSource && <TextButton link onPress={onUseAsSource}>{m.useAsSource}</TextButton>}
            {onDelete && <TextButton link onPress={onDelete}>{m.delete}</TextButton>}
          </span>
        )}
      </span>
    );
  }
  const busy = a.status === "uploading" || a.status === "queued" || a.status === "processing";
  const label = a.status === "needs_review" && a.reviewPages?.length ? m.readyCheckPages({ pages: pageList(a.reviewPages) }) : STATUS_LABEL[a.status];
  const title = a.status === "needs_review" ? m.labelValue({ label: a.filename, value: reviewHint(a.reviewPages) })
    : a.status === "failed" ? m.labelValue({ label: a.filename, value: failureText(m, a.errorCode, a.errorDetail, a.error) }) : a.filename;
  if (a.removed) {  // the document was deleted and its name taken out (suveryn-tracker#12)
    return <span className="chip-attachment chip-removed"><CircleX size={12} aria-hidden /><span className="chip-name">{m.documentRemoved}</span></span>;
  }
  return (
    <span className="chip-attachment" title={title}>
      {busy ? <LoaderCircle size={12} className="spin" aria-hidden /> :
        a.status === "failed" ? <CircleX size={12} aria-hidden /> :
        a.status === "needs_review" || a.status === "noticed" ? <TriangleAlert size={12} aria-hidden /> :
        <FileText size={12} aria-hidden />}
      <span className="chip-name">{a.filename}</span>
      {label && (
        <span className="chip-status">
          {a.status === "uploading" && a.progress !== undefined ? m.uploadingPercent({ pct: Math.floor(a.progress * 100) }) : label}
        </span>
      )}
      {onRemove && (
        <Button variant="plain" className="chip-remove" onPress={onRemove} aria-label={m.removeFile({ file: a.filename })}>
          <X size={12} aria-hidden />
        </Button>
      )}
    </span>
  );
}

/** Model tag in the composer: neutral on purpose (teal is reserved for citations). */

/** " (dossier 124, 17 okt)": where an upload marked as sūveryn's own output came from, read from its mark (board G13). */
function noticedFrom(line: string, m: ReturnType<typeof useT>): string {
  const o = markOrigin(line);
  if (!o) return "";
  const day = o.date ? o.date.toLocaleDateString(locale(), { day: "numeric", month: "short" }).replace(/\.$/, "") : "";
  return ` (${day ? m.cardNoticedFrom({ caseRef: o.caseRef, day }) : o.caseRef})`;
}
