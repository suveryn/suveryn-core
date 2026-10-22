/**
 * The documents a question reads (docs/harness.md: "the person chooses the documents, or the case's
 * documents are used"): what the conversation attached so far and with this question. In a case where
 * nothing is attached, the case's sources, newest first, as the case's empty state and the line under the
 * question box promise (Pod check of 13469bf: such a question read nothing). Attaching is choosing: an
 * attached document keeps the answer to it, rather than mixing in passages from similar documents in the
 * case. sūveryn's own output and uploads waiting for a choice are never read (originKind). At most
 * MAX_DOCUMENTS, the server's limit.
 */
import type { StoredDocument } from "../api";
import { originKind } from "./origin";

export const MAX_DOCUMENTS = 50;  // ChatRequest.document_ids (suveryn_harness.schemas)

export function questionDocuments(chosen: Iterable<string>, caseDocuments: StoredDocument[] | null): string[] {
  const ids = [...new Set(chosen)];
  if (ids.length === 0 && caseDocuments) {
    ids.push(...caseDocuments.filter((d) => originKind(d) === "source")
      .sort((a, b) => b.created_at.localeCompare(a.created_at)).map((d) => d.id));
  }
  return ids.slice(0, MAX_DOCUMENTS);
}

/**
 * A question refused as "unknown document" (404), with the case's documents read again (Pod check of
 * 547f48e: a colleague had deleted one since this page last read the list). ``retry``: it was about the
 * whole case, so it is asked again at once with the sources there are now. ``chosenGone``: it was about
 * chosen documents and one of them is gone, which the person is told rather than answered from fewer.
 * ``null``: nothing was deleted, so the refusal stands as it is.
 */
export function afterDeletion(sent: Iterable<string>, chosen: number, now: StoredDocument[]): "retry" | "chosenGone" | null {
  const here = new Set(now.filter((d) => originKind(d) === "source").map((d) => d.id));
  if (![...sent].some((id) => !here.has(id))) return null;
  if (chosen > 0) return "chosenGone";
  return here.size > 0 ? "retry" : null;
}
