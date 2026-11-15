/**
 * Reading notes (suveryn-tracker#26): what reading a document noticed, shown to everyone who can see the
 * document. Two kinds put it on "To check": text addressed to an AI (``instruction_like_text``, "ignore
 * the instructions": possibly put there to steer an AI) and body text the layout reading missed, taken
 * from the PDF without its layout (``text_layer_recovered``, ``text_recovered``: the garbled sources
 * reported earlier). A recovered header or footer (``furniture_restored``) is common and harmless: only
 * a note, never "To check". The server's own review warnings (``reviewPages``) are unchanged.
 */
import { pagesWith, reviewPages, type Warning } from "../api";
import type { Messages } from "../i18n";
import { pagesOf as pagesValue } from "./lists";
import { messageText } from "./messages";

type ReadingNotes = { ai: boolean; aiPages: number[]; recovered: number[]; headers: number[] };

const AI = "document.instruction_like_text", RECOVERED = ["document.text_layer_recovered", "document.text_recovered"];
const HEADERS = "document.furniture_restored", REVIEW = ["document.page_coverage_low", "document.layout_failed"];

export function readingNotes(warnings: Warning[] | undefined): ReadingNotes {
  const ws = warnings ?? [];
  return { ai: ws.some((w) => w.code === AI), aiPages: pagesWith(ws, [AI]), recovered: pagesWith(ws, RECOVERED), headers: pagesWith(ws, [HEADERS]) };
}

/** Whether the notes put the document on "To check". */
export const toCheck = (n: ReadingNotes) => n.ai || n.recovered.length > 0;

/** Whether there is anything to show under "Reading notes". */
export const hasNotes = (warnings: Warning[] | undefined) => {
  const n = readingNotes(warnings);
  return toCheck(n) || n.headers.length > 0 || reviewPages(warnings).length > 0 || newer(warnings).length > 0;
};

/** Why the pages need checking, for the upload card (board G13): the first warning that put them there, by the
 *  word after its area ("page_coverage_low"), which the card's message chooses by. */
export const reviewKind = (warnings: Warning[] | undefined): string | undefined =>
  (warnings ?? []).find((w) => REVIEW.includes(w.code ?? ""))?.code?.split(".")[1];

/** The pages to name beside "To check": the server's review pages and the notes', together. */
export const checkPages = (warnings: Warning[] | undefined) => {
  const n = readingNotes(warnings);
  return [...new Set([...reviewPages(warnings), ...n.aiPages, ...n.recovered])].sort((a, b) => a - b);
};

/** Warnings this page has no words of its own for: a code newer than the page. Each is still said, by its area's or
 *  its kind's words (the decision of 12 November, rule 4). What has no code isn't a message: a document stored before
 *  the warnings were codes shows no note. */
const newer = (warnings: Warning[] | undefined) =>
  (warnings ?? []).filter((w) => typeof w.code === "string" && ![AI, HEADERS, ...RECOVERED, ...REVIEW].includes(w.code));

/** What the document's row says to a screen reader beside its name and status. */
export function rowNotes(m: Messages, warnings: Warning[] | undefined): string[] {
  const n = readingNotes(warnings);
  return [...(n.ai ? [n.aiPages.length ? m.noteAiRowPages(pagesValue(n.aiPages, m)) : m.noteAiRow] : []), ...(n.recovered.length ? [m.noteRecoveredRow(pagesValue(n.recovered, m))] : [])];
}

/** The reading notes in full, most serious first: each kind of warning in its own sentence (the code's words, in
 *  `messages`), for all its pages at once. */
export function noteDetails(m: Messages, warnings: Warning[] | undefined): string[] {
  const n = readingNotes(warnings);
  const review = reviewPages(warnings);
  const said = m.messages, bare = m.messagesBare;
  return [...(n.ai ? [n.aiPages.length ? said[AI](pagesValue(n.aiPages, m)) : bare[AI]] : []),
          ...(review.length ? [said["document.page_coverage_low"](pagesValue(review, m))] : []),
          ...(n.recovered.length ? [said["document.text_recovered"](pagesValue(n.recovered, m))] : []),
          ...(n.headers.length ? [said[HEADERS](pagesValue(n.headers, m))] : []),
          ...new Set(newer(warnings).map((w) => messageText(w, m)))];
}

/** The line on the upload card once it is read: the most serious note, or null. */
export function cardNote(m: Messages, warnings: Warning[] | undefined): string | null {
  const n = readingNotes(warnings);
  return n.ai ? m.cardNoteAi : n.recovered.length ? m.cardNoteRecovered : null;
}
