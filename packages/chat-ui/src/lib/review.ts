/** Wording for documents in needs_review: usable, but text on some pages may be missing. */
import { t, type Messages } from "../i18n";

/** "p. 1" or "pp. 1, 3" (in the current language) */
export const pageList = (pages: number[]) => t().pageList(pages);

export const reviewHint = (pages: number[] | undefined): string => t().reviewHint(pages);

/** Why an upload failed, as the server says it ("ValueError: the file is not a valid Word file"): the
 *  reason as a sentence, without the exception's name. Only when there is no code (``failureText``). */
export function failureReason(error: string | undefined): string {
  const reason = (error ?? "").replace(/^[A-Za-z]+(?:Error|Exception):\s*/, "").trim();
  return reason && reason[0].toUpperCase() + reason.slice(1) + (/[.!?]$/.test(reason) ? "" : ".");
}

/** Why an upload couldn't be read, in the interface's language: from the reader's code
 *  (suveryn_rag.reading.CODES) and its numbers; without a code (an older server, or the upload itself
 *  was refused, already said in words by api.ts), the server's own reason (``failureReason``). */
export function failureText(m: Messages, code: string | undefined, detail: Record<string, number> = {}, error?: string): string {
  switch (code) {
    case "password": return m.failPassword;
    case "damaged": return m.failDamaged;
    case "too_many_pages": return detail.pages && detail.max ? m.failTooManyPages(detail.pages, detail.max) : m.failTooLarge;
    case "too_large": return m.failTooLarge;
    case "no_text": return m.failNoText;
    case "unsupported": return m.failUnsupported;
    case "timeout": return m.failTimeout(detail.minutes || 30);
    case "unreadable": return m.failUnreadable;
    default: return failureReason(error);
  }
}
