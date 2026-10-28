/**
 * An answer as a Word file, and saved to its case (docs/design/chat-ui.md §5).
 *
 * The Word file is built in the browser (lib/office.ts). Saving to a case stores what builds it (the
 * question, the answer as written, its sources with their file names, its checks), and the file is
 * built again from that on download: the same file, mark included. The server takes a deleted
 * document's passages out of a saved answer as it does from conversations (``without`` in the store).
 */
import type { Watermark } from "./watermark";
import type { Citation } from "../api";
import { locale, type Messages } from "../i18n";
import type { AssistantTurn } from "../types";
import { citedNumbers, stripMarkers, toBlocks } from "./answer";
import { checkLines, type AnswerExport } from "./export";
import { exportRef } from "./marks";

/** What a saved answer keeps: everything its Word file is made of. */
export type SavedAnswer = {
  question: string;
  answer: string;
  answeredOn: string;            // ISO date: when it was saved
  model?: string;
  citations: Citation[];
  calculations: AssistantTurn["calculations"];
  unverifiedFigures: string[];
  citationIssues: AssistantTurn["citationIssues"];
  supportSpans?: AssistantTurn["supportSpans"];  // absent in answers saved before suveryn-tracker#25
  instructionLikeSources: number[];
  filenames: Record<string, string>;  // the sources' file names, as they were
  turnId: string;                      // the answer's id: the mark's reference stays the same
  caseRef: string | null;
};

/** The texts the Word and Excel files use, in the interface's language. */
export function officeText(m: Messages) {
  return {
    answeredOn: m.answeredOn, checkHeading: m.toCheck, sourcesHeading: m.sources, sourceRemoved: m.sourceRemoved,
    sourceColumn: m.sourceColumn, sheetTable: m.sheetTable, sheetSources: m.sources, sheetChecks: m.toCheck,
    columns: { n: m.columnNumber, document: m.columnDocument, where: m.columnWhere, passage: m.columnPassage },
    disclaimer: m.exportDisclaimer,
  };
}

/** A finished answer as its Word and Excel files show it: the same warnings and sources as the chat. */
export function answerExport(turn: AssistantTurn, question: string, nameOf: (c: Citation) => string, m: Messages,
                             caseRef: string | null, answeredOn: Date = new Date(), watermark?: Watermark): AnswerExport {
  const available = turn.citations.length;
  const flagged = turn.unverifiedFigures ?? [];
  return {
    question, answeredOn, model: turn.model, blocks: toBlocks(turn.text, available, flagged),
    checks: [...checkLines(turn.calculations ?? [], flagged, turn.citationIssues ?? [], m),
             ...(turn.instructionLikeSources?.length ? [m.instructionLike(turn.instructionLikeSources)] : [])],
    sources: citedNumbers(turn.text, available).map((n) => ({ n, citation: turn.citations[n - 1], filename: nameOf(turn.citations[n - 1]) })),
    // sūveryn's mark (lib/marks.ts): so that this file, uploaded again, is recognised and asks first.
    mark: m.exportMark("answer", caseRef, answeredOn.toLocaleDateString(locale()), exportRef("A", turn.id))
      + (watermark ? ` · ${m.strictlyConfidential}` : ""),
    watermark,
  };
}

/** The Word file's name: the question, on one line, without characters a file name can't hold. */
export function answerFileName(question: string): string {
  const name = question.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().replace(/[. ]+$/, "");
  return `${(name.length > 80 ? name.slice(0, 80).trimEnd() : name) || "answer"}.docx`;
}

/** What is stored when an answer is saved to its case. */
export function savedAnswer(turn: AssistantTurn, question: string, filenames: Map<string, string>,
                            caseRef: string | null, now: Date = new Date()): SavedAnswer {
  const names: Record<string, string> = {};
  for (const c of turn.citations) {
    const id = c.source?.document_id;
    if (id && filenames.has(id)) names[id] = filenames.get(id)!;
  }
  return {
    question, answer: turn.text, answeredOn: now.toISOString(), model: turn.model, citations: turn.citations,
    calculations: turn.calculations ?? [], unverifiedFigures: turn.unverifiedFigures ?? [],
    citationIssues: turn.citationIssues ?? [], instructionLikeSources: turn.instructionLikeSources ?? [],
    ...(turn.supportSpans ? { supportSpans: turn.supportSpans } : {}),
    filenames: names, turnId: turn.id, caseRef,
  };
}

/** What search finds of a saved answer: the question and the answer, without citation markers. */
export function searchText(s: SavedAnswer): string {
  return `${s.question}\n\n${stripMarkers(s.answer)}`.trim();
}

/** A saved answer as the turn it came from, to build its file again. */
export function savedTurn(s: SavedAnswer): AssistantTurn {
  return {
    id: s.turnId, role: "assistant", text: s.answer, citations: s.citations ?? [], calculations: s.calculations ?? [],
    unverifiedFigures: s.unverifiedFigures ?? [], citationIssues: s.citationIssues ?? [],
    ...(s.supportSpans ? { supportSpans: s.supportSpans } : {}),
    instructionLikeSources: s.instructionLikeSources ?? [], status: "done", grounded: true, model: s.model,
  };
}

/** A saved answer's Word file, built again: the same as when it was downloaded from the chat. */
export async function savedWord(s: SavedAnswer, m: Messages, language: string, watermark?: Watermark): Promise<Blob> {
  const { answerToWord } = await import("./office");
  const nameOf = (c: Citation) => (c.removed ? m.sourceRemoved : (c.source && s.filenames?.[c.source.document_id]) || m.unnamedDocument);
  return answerToWord(answerExport(savedTurn(s), s.question, nameOf, m, s.caseRef, new Date(s.answeredOn), watermark), officeText(m), language);
}
