/** Wording for documents in needs_review: usable, but text on some pages may be missing. */
import { t } from "../i18n";

/** "p. 1" or "pp. 1, 3" (in the current language) */
export const pageList = (pages: number[]) => t().pageList(pages);

export const reviewHint = (pages: number[] | undefined): string => t().reviewHint(pages);

/** Why an upload failed, as the server says it ("ValueError: the file is not a valid Word file"): the
 *  reason as a sentence, without the exception's name. In English: the reader reports reasons as text, not codes. */
export function failureReason(error: string | undefined): string {
  const reason = (error ?? "").replace(/^[A-Za-z]+(?:Error|Exception):\s*/, "").trim();
  return reason && reason[0].toUpperCase() + reason.slice(1) + (/[.!?]$/.test(reason) ? "" : ".");
}
