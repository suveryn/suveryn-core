/**
 * Which format a download button makes by default (docs/design/chat-ui.md §6, "Other formats"): the
 * last one the person chose, for answers (Word or Markdown) and for tables (Excel or CSV) separately.
 * Kept in this browser (localStorage); without it, for this page only. Every button on the page follows
 * a change at once.
 */
import { useSyncExternalStore } from "react";

export const FORMATS = { answer: ["docx", "md"], table: ["xlsx", "csv"] } as const;
export type FormatKind = keyof typeof FORMATS;
export type AnswerFormat = (typeof FORMATS)["answer"][number];
export type TableFormat = (typeof FORMATS)["table"][number];
type FormatOf<K extends FormatKind> = (typeof FORMATS)[K][number];

const KEY = (kind: FormatKind) => `suveryn.format.${kind}`;
const chosen: Partial<Record<FormatKind, string>> = {};
const listeners = new Set<() => void>();

export function readFormat<K extends FormatKind>(kind: K): FormatOf<K> {
  const known = FORMATS[kind] as readonly string[];
  let value = chosen[kind];
  if (value === undefined) {
    try { value = localStorage.getItem(KEY(kind)) ?? undefined; } catch { /* no storage: the first format */ }
  }
  return (value && known.includes(value) ? value : known[0]) as FormatOf<K>;
}

export function rememberFormat<K extends FormatKind>(kind: K, format: FormatOf<K>): void {
  chosen[kind] = format;
  try { localStorage.setItem(KEY(kind), format); } catch { /* this page only */ }
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** The default format, following changes made by any button on the page. */
export function useFormat<K extends FormatKind>(kind: K): FormatOf<K> {
  return useSyncExternalStore(subscribe, () => readFormat(kind));
}
