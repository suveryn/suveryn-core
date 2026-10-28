/**
 * Ask about (docs/design/chat-ui.md §10): which of a case's documents a conversation's questions are
 * about. The choice belongs to the conversation: it stays for every following question until changed,
 * is saved with each question (``UserTurn.about``), and is never carried to another conversation.
 */
import type { StoredDocument } from "../api";
import type { Chosen, Turn } from "../types";
import { formatName } from "./formats";
import { originKind } from "./origin";

/** The choice when a conversation is opened again: the last question's. A conversation saved before
 *  *Ask about* chose by attaching, so its attached documents are its choice. */
export function restoreAbout(turns: Turn[]): Chosen[] {
  const asked = turns.filter((t) => t.role === "user");
  const last = asked[asked.length - 1];
  if (last?.about) return last.about.filter((c) => !c.removed);
  const seen = new Map<string, Chosen>();
  for (const t of asked) for (const a of t.attachments)
    if (a.documentId && !a.removed && (a.status === "ready" || a.status === "needs_review")) seen.set(a.documentId, { documentId: a.documentId, filename: a.filename });
  return [...seen.values()];
}

/** The case's documents that may be chosen: its sources, newest first. */
export function choosable(docs: StoredDocument[]): StoredDocument[] {
  return docs.filter((d) => originKind(d) === "source").sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** The choice without the documents that left the case (deleted, or no longer a source); ``gone`` when
 *  something was chosen and nothing remains, so the line under the question box can say so. */
export function stillThere(about: Chosen[], docs: StoredDocument[]): { about: Chosen[]; gone: boolean } {
  const here = new Map(choosable(docs).map((d) => [d.id, d]));
  const kept = about.filter((c) => here.has(c.documentId)).map((c) => ({ ...c, filename: here.get(c.documentId)!.filename }));
  return { about: kept, gone: about.length > 0 && kept.length === 0 };
}

/** One row's details: "PDF · 14 p. · Mieke Delarivière, 12 Oct". */
export function pickMeta(d: StoredDocument, who: string, locale: string): string {
  const kind = formatName(d.filename) || "PDF";
  const when = new Date(d.created_at).toLocaleDateString(locale, { day: "numeric", month: "short" });
  return [kind, d.pages ? `${d.pages} p.` : null, [who, when].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
}
