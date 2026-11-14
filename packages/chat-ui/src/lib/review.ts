/** Wording for documents in needs_review: usable, but text on some pages may be missing. */
import { t, type Messages } from "../i18n";
import { pagesOf } from "./lists";
import { messageText, type Message } from "./messages";

/** "p. 1" or "pp. 1 and 3" (in the current language) */
export const pageList = (pages: number[]) => t().pageList(pagesOf(pages));

export const reviewHint = (pages: number[] | undefined): string => (pages?.length ? t().reviewHintPages(pagesOf(pages)) : t().reviewHint);

/** Why an upload failed, as the server says it ("ValueError: the file is not a valid Word file"): the
 *  reason as a sentence, without the exception's name. Only when there is no code (``failureText``). */
export function failureReason(error: string | undefined): string {
  const reason = (error ?? "").replace(/^[A-Za-z]+(?:Error|Exception):\s*/, "").trim();
  return reason && reason[0].toUpperCase() + reason.slice(1) + (/[.!?]$/.test(reason) ? "" : ".");
}

/** Why an upload couldn't be read, in the interface's language: the reader's reason, a code of the registry's
 *  document area with its numbers (docs/design/messages.md); a code newer than this page gets the area's words.
 *  Without a code (the upload itself was refused, already said in words by api.ts), the reason as it came. */
export function failureText(m: Messages, failure: Message | undefined, error?: string): string {
  if (!failure?.code) return failureReason(error);
  return failure.code in m.messages ? messageText(failure, m) : m.messageAreas.document;
}
