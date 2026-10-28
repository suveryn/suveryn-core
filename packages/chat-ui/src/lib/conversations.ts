/**
 * Saved conversations (suveryn-tracker#5): what is sent to the server and how it comes back.
 * The server stores the turns as given, under the signed-in user; see the gateway's conversations.py.
 */
import { locale, t } from "../i18n";
import type { Turn } from "../types";

/** A random UUID (v4). Not crypto.randomUUID: that needs a secure context, and an appliance may be reached over plain http. */

/** The most turns the server saves in one conversation (``MAX_TURNS`` in the gateway's conversations.py). */
export const MAX_SAVED_TURNS = 500;

export function newConversationId(): string {
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** The first question, on one line and at most 80 characters: the conversation's name in the sidebar. */
export function conversationTitle(turns: Turn[]): string {
  const first = turns.find((t) => t.role === "user")?.text.replace(/\s+/g, " ").trim() ?? "";
  if (!first) return t().conversationFallbackTitle;
  return first.length > 80 ? `${first.slice(0, 79).trimEnd()}…` : first;
}

/** The turns as saved: without what only matters while an answer streams or a file uploads. */
export function toSaved(turns: Turn[]): Turn[] {
  return turns.map((t) => {
    if (t.role === "user") return { ...t, attachments: t.attachments.map(({ progress: _p, ...a }) => a) };
    const { step: _s, ...rest } = t;
    return rest;
  });
}

/** Turns read back from the server. An answer saved mid-stream (it shouldn't be) shows as interrupted. */
export function fromSaved(turns: Turn[]): Turn[] {
  return turns.map((turn) => (turn.role === "assistant" && turn.status === "streaming"
    ? { ...turn, text: "", status: "error", error: t().answerInterrupted } : turn));
}

/** "Today", "Yesterday", "8 Oct" or "8 Oct 2025" (in the current language): when a conversation last changed. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return t().today;
  if (days === 1) return t().yesterday;
  return d.toLocaleDateString(locale(), { day: "numeric", month: "short",
    ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/** True if a conversation cites or attaches this document. */
export function usesDocument(turns: Turn[], documentId: string): boolean {
  return turns.some((t) => (t.role === "user"
    ? t.attachments.some((a) => a.documentId === documentId) || (t.about ?? []).some((c) => c.documentId === documentId)
    : t.citations.some((c) => c.source?.document_id === documentId)));
}

/**
 * The conversation without a deleted document's passages and file names, exactly as the server cleans
 * the saved copy (conversations.py ``redact``, suveryn-tracker#12): text and location go, the page and
 * the answer stay, and the citation or attachment is marked ``removed``.
 */
export function withoutDocument(turns: Turn[], documentId: string): Turn[] {
  return turns.map((t) => {
    if (t.role === "user") {
      return { ...t, attachments: t.attachments.map((a) => (a.documentId === documentId && !a.removed
        ? { ...a, filename: "", removed: true } : a)),
        ...(t.about ? { about: t.about.map((c) => (c.documentId === documentId && !c.removed ? { ...c, filename: "", removed: true } : c)) } : {}) };
    }
    return { ...t, citations: t.citations.map((c) => (c.source?.document_id === documentId && !c.removed
      ? { text: "", source: { document_id: documentId, page: c.source.page, location: null }, removed: true } : c)) };
  });
}


/** A conversation's name in a list: its title, or "Shielded conversation" for one in a strictly
 *  confidential case, whose title the lists that span cases don't carry (docs/design/chat-ui.md §11). */
export function listedTitle(c: { title: string | null; shielded?: boolean }): string {
  return c.shielded || c.title === null ? t().shieldedConversation : c.title;
}
