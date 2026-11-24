/**
 * Saved conversations (suveryn-tracker#5): what is sent to the server and how it comes back.
 * The server stores the turns as given, under the signed-in user; see the gateway's conversations.py.
 */
import { lang, locale, t } from "../i18n";
import type { ChatResponse } from "../api";
import type { AssistantTurn, Turn } from "../types";
import { answerPatch } from "./ask";
import { messageText, type Message } from "./messages";
import { opened, shownOf } from "./versions";

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

/** A turn as the gateway gives it back: the chat UI's own (saved whole before suveryn-tracker#251), or one the server
 *  stored as it answered (``kind``: question or answer, ``parent``: the turn it follows; the gateway's ``AskedTurn``,
 *  ``AnsweredTurn``), with its number (``seq``). */
type Stored = Record<string, unknown> & { role: string; text?: string; seq?: number };

/** The newest stored answer to the question numbered ``question``: the one it follows (``parent``), or, for turns the
 *  chat UI saved whole, the turn after it. ``known``: answers this page already had, none of which is the one sought
 *  (a version asked for just now, not stored yet, is not an earlier one). */
export function answerTo(turns: unknown[], question: number, known: Set<number | undefined> = new Set()): number | undefined {
  const stored = turns as Stored[];
  const answers = stored.filter((t, i) => t.role === "assistant" && !known.has(t.seq)
    && ("parent" in t ? t.parent === question : stored[i - 1]?.seq === question));
  return answers.at(-1)?.seq;
}

/** The number the server gave the answer to the question numbered ``question``, stopped (or cut off) before the stream
 *  said it: it is stored as the connection closes, so the conversation is read again (``read``) a few times until it
 *  is there. With the turns read, to know it whether shown or not. ``known``: as for ``answerTo``. Undefined if it
 *  never comes, or the conversation can't be read. */
export async function answerStored(read: () => Promise<unknown[]>, question: number, known: Set<number | undefined> = new Set(),
                                   tries = 5, wait = 300): Promise<{ answer: number; turns: Turn[] } | undefined> {
  for (let i = 0; i < tries; i++) {
    if (i > 0) await new Promise((r) => setTimeout(r, wait));
    try {
      const turns = await read();
      const answer = answerTo(turns, question, known);
      if (answer !== undefined) return { answer, turns: turns as Turn[] };
    } catch { /* not readable now: try again */ }
  }
  return undefined;
}

/** A turn the server stored, as the screen shows it: a question with the documents it showed (by id: their names
 *  as the documents here know them, or taken out when deleted), an answer as it ended. ``conversationId``/``seq`` is
 *  its id: the mark of its Word file, and what a document saved from it names (its provenance's ``message``). */
function fromServer(turn: Stored, question: Stored | undefined, conversationId: string, nameOf: (id: string) => string | undefined): Turn {
  const id = `${conversationId}/${turn.seq}`;
  const ids = (key: string, of: Stored = turn) => (Array.isArray(of[key]) ? (of[key] as string[]) : []);
  const named = (documentId: string) => {
    const filename = nameOf(documentId);
    return filename === undefined ? { documentId, filename: "", removed: true } : { documentId, filename };
  };
  if (turn.role === "user") {
    const about = ids("about").map(named);
    return { id, seq: turn.seq, byServer: true, role: "user", text: turn.text ?? "",
             attachments: ids("attached").map((d) => ({ key: d, status: "ready" as const, ...named(d) })),
             ...(about.length ? { about } : {}) };
  }
  const done = { answer: turn.text ?? "", ...(turn as object) } as unknown as ChatResponse;
  const asked: Stored = question ?? { role: "user" };
  const answer: AssistantTurn = {
    id, seq: turn.seq, byServer: true, role: "assistant", citations: [], grounded: ids("document_ids", asked).length > 0,
    ...answerPatch(done, { thought: "", partial: ids("about", asked).length > 0 && turn.complete === false }),
    ...(asked.thinking ? { thinking: true } : {}),
  } as AssistantTurn;
  const narrowed = typeof turn.narrowed_to === "string" ? nameOf(turn.narrowed_to) : undefined;
  if (narrowed) answer.narrowedTo = narrowed;
  else delete answer.narrowedTo;
  if (turn.outcome === "stopped") return { ...answer, status: "stopped", supportSpans: undefined };
  if (turn.outcome === "failed") {
    const failure = turn.failure as Message | undefined;
    return { ...answer, text: "", status: "error", ...(failure ? { failure, error: messageText(failure, t()) } : {}) };
  }
  return answer;
}

/** Every turn of a conversation read back from the server, as the screen keeps it, each naming the turn it follows
 *  (``follows``). An answer saved mid-stream (it
 *  shouldn't be) shows as interrupted. The screen shows one branch of them (``fromSaved``), and switches between an
 *  answer's versions within them (lib/versions.ts). */
export function readTurns(stored: Turn[], conversationId = "", nameOf: (id: string) => string | undefined = () => undefined): Turn[] {
  const raw = stored as unknown as Stored[];
  const bySeq = new Map(raw.map((s) => [s.seq, s]));
  const read = raw.map((saved, i) => {
    const read = saved.kind === "question" || saved.kind === "answer"
      ? fromServer(saved, saved.kind === "answer" ? bySeq.get(saved.parent as number) : undefined, conversationId, nameOf)
      : saved as unknown as Turn;
    // A turn saved without the UI's own fields (through the API) opens all the same:
    // the lists default to empty, the id and status to something usable (VM regression of 29 October, finding 10).
    const turn = { ...read, id: read.id || `saved-${i}`, text: read.text ?? "" } as Turn;
    if (turn.role === "user") return { ...turn, attachments: Array.isArray(turn.attachments) ? turn.attachments : [] };
    const answer = { ...turn, citations: Array.isArray(turn.citations) ? turn.citations : [], status: turn.status ?? "done",
                     grounded: turn.grounded ?? false };
    return answer.status === "streaming" ? { ...answer, text: "", status: "error", error: t().answerInterrupted } : answer;
  });
  // what each follows, by id: the server's ``parent``; a turn the chat UI saved whole follows the one before it, so
  // has no versions (step 4 of #251 removes them)
  const idOf = new Map(raw.map((s, i) => [s.seq, read[i].id]));
  return read.map((turn, i) => ({ ...turn, follows: "parent" in raw[i] ? idOf.get(raw[i].parent as number) ?? null
    : i > 0 ? read[i - 1].id : null }) as Turn);
}

/** Turns read back from the server: the branch shown (the newest answer of each question, and what followed it), each
 *  as the screen keeps it (lib/versions.ts). */
export function fromSaved(stored: Turn[], conversationId = "", nameOf: (id: string) => string | undefined = () => undefined): Turn[] {
  return shownOf(opened(readTurns(stored, conversationId, nameOf)));
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
export function listedTitle(c: { title: string | null; shielded?: boolean; titles?: Record<string, string> | null }): string {
  // a playbook run's: its title in the reader's language, the pack's words (decision of 12 November 2026)
  return c.shielded || c.title === null ? t().shieldedConversation : c.titles?.[lang()] || c.title;
}
