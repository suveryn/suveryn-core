/**
 * A document's origin (docs/design/chat-ui.md §6; cases.md decision 7): where it comes from, as one
 * word and a detail, for the Documents overview's origin column and its filter, and the icon
 * that follows the document wherever it appears. The server decides what is a source (``source``);
 * this only says it.
 */
import type { StoredDocument } from "../api";
import type { Messages } from "../i18n";

/** source: the model may cite it; made: sūveryn's own output, never a source; pending: an upload that
 *  carries sūveryn's own export mark, waiting for a person to decide. */
export type OriginKind = "source" | "made" | "pending";

export function originKind(d: Pick<StoredDocument, "origin" | "source" | "provenance">): OriginKind {
  if ((d.origin ?? "uploaded") !== "uploaded") return "made";
  const p = d.provenance;
  if (p?.noticed && !p.confirmed) return "pending";
  return d.source === false ? "pending" : "source";
}

/** "Source · uploaded", "Made · playbook v1.0", "Made · answer, saved", "Source · uploaded, was an answer", "Waiting for your choice". */
export function originText(d: Pick<StoredDocument, "origin" | "source" | "provenance">, m: Messages): { word: string; detail: string } {
  const kind = originKind(d);
  const p = d.provenance;
  if (kind === "pending") return { word: m.originPending, detail: m.noticedTitle(p?.noticed?.kind ?? "answer") };
  if (kind === "made") {
    return { word: m.originMade, detail: d.origin === "playbook" ? m.originPlaybook(p?.version ?? null)
                                   : d.origin === "answer" ? m.originAnswerSaved : m.originExport };
  }
  return { word: m.originSource, detail: p?.confirmed && p.noticed ? m.originWasOutput(p.noticed.kind) : m.originUploaded };
}
