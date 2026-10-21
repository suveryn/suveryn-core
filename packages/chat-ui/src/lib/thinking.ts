/**
 * *Fast* or *Thorough* (docs/design/sidebar.md §5): whether the model thinks before it answers.
 *
 * - The choice belongs to the conversation: each answer records it (``AssistantTurn.thinking``), and a
 *   reopened conversation goes on as it was.
 * - A new conversation starts with the person's default, set under *Settings* and kept in this browser
 *   (localStorage); without storage, *Fast* for this page.
 * - Only a model that can think (``ModelInfo.thinks``) is asked to; with another, *Thorough* is
 *   disabled and the server ignores the flag anyway.
 */
import type { ModelInfo } from "../api";
import type { Turn } from "../types";

const KEY = "suveryn.thinking";
let fallback = false;

export function thinkingDefault(): boolean {
  try { return localStorage.getItem(KEY) === "thorough"; } catch { return fallback; }
}

export function setThinkingDefault(on: boolean): void {
  fallback = on;
  try { localStorage.setItem(KEY, on ? "thorough" : "fast"); } catch { /* this page only */ }
}

/** The mode a reopened conversation goes on with: its last answer's, else the default. */
export function restoreThinking(turns: Turn[], otherwise: boolean): boolean {
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i];
    if (t.role === "assistant" && t.thinking !== undefined) return t.thinking;
  }
  return otherwise;
}

/** Whether this model can think first (and so whether *Thorough* applies). */
export function canThink(model: ModelInfo | undefined): boolean {
  return !!model?.thinks;
}

/** "14 s", "1 min 5 s": how long the model thought, for "Thought for …". */
export function thoughtTime(seconds: number): string {
  const s = Math.max(1, Math.round(seconds));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
}
