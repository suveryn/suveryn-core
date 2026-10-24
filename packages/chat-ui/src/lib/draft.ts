/**
 * The question being typed, kept for this browser tab (sessionStorage) so that it survives signing in
 * again after the session ended, for example when the server restarted (Pod check of 5e9a539). Kept
 * until it is sent, emptied or the person signs out; gone when the tab closes. Without storage the
 * composer works as before, for this page only.
 */
const KEY = "suveryn.draft";

export function readDraft(): string {
  try { return sessionStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

export function keepDraft(text: string): void {
  try {
    if (text.trim()) sessionStorage.setItem(KEY, text);
    else sessionStorage.removeItem(KEY);
  } catch { /* this page only */ }
}

export function clearDraft(): void {
  keepDraft("");
}
