/**
 * Reading notes (suveryn-tracker#26): what reading a document noticed, shown to everyone who can see the
 * document. Two kinds put it on "To check": text addressed to an AI (``instruction_like_text``, "ignore
 * the instructions": possibly put there to steer an AI) and body text the layout reading missed, taken
 * from the PDF without its layout (``text_layer_recovered``, ``text_recovered``: the garbled sources
 * reported earlier). A recovered header or footer (``furniture_restored``) is common and harmless: only
 * a note, never "To check". The server's own review warnings (``reviewPages``) are unchanged.
 */
import { reviewPages, type Warning } from "../api";
import type { Messages } from "../i18n";
import { pagesOf as pagesValue } from "./lists";

type ReadingNotes = { ai: boolean; aiPages: number[]; recovered: number[]; headers: number[] };

const pagesOf = (ws: Warning[], kinds: string[]) =>
  [...new Set(ws.filter((w) => kinds.includes(w.kind) && w.page !== null).map((w) => w.page!))].sort((a, b) => a - b);

export function readingNotes(warnings: Warning[] | undefined): ReadingNotes {
  const ws = warnings ?? [];
  return { ai: ws.some((w) => w.kind === "instruction_like_text"), aiPages: pagesOf(ws, ["instruction_like_text"]),
           recovered: pagesOf(ws, ["text_layer_recovered", "text_recovered"]), headers: pagesOf(ws, ["furniture_restored"]) };
}

/** Whether the notes put the document on "To check". */
export const toCheck = (n: ReadingNotes) => n.ai || n.recovered.length > 0;

/** Whether there is anything to show under "Reading notes". */
export const hasNotes = (warnings: Warning[] | undefined) => {
  const n = readingNotes(warnings);
  return toCheck(n) || n.headers.length > 0 || reviewPages(warnings).length > 0;
};

/** Why the pages need checking, for the upload card (board G13): the kind of the first warning that put them there. */
export const reviewKind = (warnings: Warning[] | undefined): string | undefined =>
  (warnings ?? []).find((w) => w.kind === "page_coverage_low" || w.kind === "layout_failed")?.kind;

/** The pages to name beside "To check": the server's review pages and the notes', together. */
export const checkPages = (warnings: Warning[] | undefined) => {
  const n = readingNotes(warnings);
  return [...new Set([...reviewPages(warnings), ...n.aiPages, ...n.recovered])].sort((a, b) => a - b);
};

/** What the document's row says to a screen reader beside its name and status. */
export function rowNotes(m: Messages, warnings: Warning[] | undefined): string[] {
  const n = readingNotes(warnings);
  return [...(n.ai ? [n.aiPages.length ? m.noteAiRowPages(pagesValue(n.aiPages, m)) : m.noteAiRow] : []), ...(n.recovered.length ? [m.noteRecoveredRow(pagesValue(n.recovered, m))] : [])];
}

/** The reading notes in full, most serious first. */
export function noteDetails(m: Messages, warnings: Warning[] | undefined): string[] {
  const n = readingNotes(warnings);
  const review = reviewPages(warnings);
  return [...(n.ai ? [n.aiPages.length ? m.noteAiPages(pagesValue(n.aiPages, m)) : m.noteAi] : []), ...(review.length ? [m.reviewHintPages(pagesValue(review, m))] : []),
          ...(n.recovered.length ? [m.noteRecovered(pagesValue(n.recovered, m))] : []), ...(n.headers.length ? [m.noteHeaders(pagesValue(n.headers, m))] : [])];
}

/** The line on the upload card once it is read: the most serious note, or null. */
export function cardNote(m: Messages, warnings: Warning[] | undefined): string | null {
  const n = readingNotes(warnings);
  return n.ai ? m.cardNoteAi : n.recovered.length ? m.cardNoteRecovered : null;
}
