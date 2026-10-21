/**
 * The documents a question reads (docs/harness.md: "the person chooses the documents, or the case's
 * documents are used"): what the conversation attached so far and with this question. In a case where
 * nothing is attached, the case's sources, newest first, as the case's empty state and the line under the
 * question box promise (Pod check of 13469bf: such a question read nothing). Attaching is choosing: an
 * attached document keeps the answer to it, rather than mixing in passages from similar documents in the
 * case. sūveryn's own output and uploads waiting for a choice are never read (originKind). At most
 * MAX_DOCUMENTS, the server's limit. ``focus``: the documents are the case's, not chosen, so the server
 * first narrows them to the ones the question is about (suveryn_rag.focus).
 */
import type { StoredDocument } from "../api";
import { originKind } from "./origin";

export const MAX_DOCUMENTS = 50;  // ChatRequest.document_ids (suveryn_harness.schemas)

export function questionDocuments(chosen: Iterable<string>, caseDocuments: StoredDocument[] | null): { ids: string[]; focus: boolean } {
  const ids = [...new Set(chosen)];
  if (ids.length > 0 || !caseDocuments) return { ids: ids.slice(0, MAX_DOCUMENTS), focus: false };
  const sources = caseDocuments.filter((d) => originKind(d) === "source")
    .sort((a, b) => b.created_at.localeCompare(a.created_at)).map((d) => d.id);
  return { ids: sources.slice(0, MAX_DOCUMENTS), focus: sources.length > 1 };
}
