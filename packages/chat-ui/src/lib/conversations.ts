/**
 * Saved conversations (suveryn-tracker#5): what is sent to the server and how it comes back.
 * The server stores the turns as given, under the signed-in user; see the gateway's conversations.py.
 */
import type { Turn } from "../types";

/** A random UUID (v4). Not crypto.randomUUID: that needs a secure context, and an appliance may be reached over plain http. */
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
  if (!first) return "Conversation";
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
  return turns.map((t) => (t.role === "assistant" && t.status === "streaming"
    ? { ...t, text: "", status: "error", error: "This answer was interrupted." } : t));
}

/** "Today", "Yesterday", "8 Oct" or "8 Oct 2025": when a conversation last changed. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short",
    ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
