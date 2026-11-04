/**
 * Deleting a document and saving an answer to a case: the decisions App.tsx makes, apart from React so they
 * can be tested (audit of 4 November 2026, App.tsx in slices; lib/ask.ts was the first).
 *
 * - ``citingCheck``: whether deleting may go ahead, and whether to ask which saved conversations cite it.
 * - ``deleteRefusal``: why a delete couldn't go ahead, in the reader's words.
 * - ``afterDelete``: what becomes of the open conversation once a document is gone.
 * - ``saveState``: whether an answer can be saved to the case, and whether it already was.
 */
import { HttpError, type StoredDocument } from "../api";
import type { Messages } from "../i18n";
import type { AssistantTurn, Turn } from "../types";
import { usesDocument } from "./conversations";

/**
 * Before a document is deleted, the saved conversations that cite it are asked whether they go too
 * (suveryn-tracker#12). ``ask``: history can be read, so find them. ``skip``: this server keeps no history,
 * nothing to ask. ``refuse``: history exists but can't be read now; nothing is deleted rather than skip the
 * question (Pod check of a318b65: it was sent at once).
 */
export function citingCheck(historyReady: boolean, historyStatus: string | undefined): "ask" | "skip" | "refuse" {
  if (historyReady) return "ask";
  return historyStatus && historyStatus !== "unavailable" ? "refuse" : "skip";
}

/** Why asking which conversations cite it failed: a 503 is the database gone before the health check noticed
 *  (Pod check of cbccd38), worded as such and worth checking at once; anything else as it came. */
export function deleteRefusal(e: unknown, m: Pick<Messages, "conversationsUnreachable">): { why: string; unreachable: boolean } {
  const unreachable = e instanceof HttpError && e.status === 503;
  return { why: unreachable ? m.conversationsUnreachable : (e as Error).message, unreachable };
}

/**
 * The open conversation once a document is deleted: ``new`` when it was among the conversations deleted with
 * it (a fresh one starts), ``clean`` when it shows the document (marked removed, as the server cleaned the
 * saved copy), else ``keep``.
 */
export function afterDelete(o: { documentId: string; turns: Turn[]; conversationId: string; conversations: "clean" | "delete";
                                 deleted: string[] }): "new" | "clean" | "keep" {
  if (o.conversations === "delete" && o.deleted.includes(o.conversationId)) return "new";
  return usesDocument(o.turns, o.documentId) ? "clean" : "keep";
}

/**
 * Save to case (docs/design/chat-ui.md §5): a finished answer, in an open case, for a contributor. ``saved``: the
 * document it was saved as, while it still exists (saved on this page, or still in the case's list); ``undoable``:
 * saved on this page, so *Undo* takes it out again. Null: the answer can't be saved here.
 */
export function saveState(t: AssistantTurn, o: { inCase: boolean; contributes: boolean; closed: boolean; readOnly: boolean;
                                                 savedHere: Set<string>; documents: StoredDocument[] }):
  { saved: NonNullable<AssistantTurn["saved"]> | null; undoable: boolean } | null {
  if (!o.inCase || !o.contributes || o.closed || o.readOnly || t.status !== "done") return null;
  const here = o.savedHere.has(t.id);
  const exists = !!t.saved && (here || o.documents.some((d) => d.id === t.saved!.documentId));
  return { saved: exists ? t.saved! : null, undoable: here && exists };
}
