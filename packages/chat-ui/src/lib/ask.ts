/**
 * A question and its answer, the decisions App.tsx's ``send`` makes, apart from React so they can be tested
 * (audit of 4 November 2026: App.tsx had no tests at all).
 *
 * - ``conversationDocuments``: the documents a conversation has attached so far, still there.
 * - ``questionFor``: which attachments go with a question, what it asks about in a case, and the
 *   documents it is answered from (docs/design/chat-ui.md §5).
 * - ``answerPatch``: the finished answer as its turn shows it.
 * - ``failureKind``: what an answer that didn't finish became.
 * - ``canRegenerate``: whether the last question can be asked again.
 */
import { HttpError, type ChatResponse, type StoredDocument } from "../api";
import { isReady, staysInComposer, type AssistantTurn, type Attachment, type Chosen, type Turn } from "../types";
import { questionDocuments } from "./questionDocuments";

/** The documents attached to the conversation's questions so far, read and (once the list is known) still there:
 *  a conversation restored from history may name documents that are gone, and asking about them would fail. */
export function conversationDocuments(turns: Turn[], documents: StoredDocument[], documentsReady: boolean): Set<string> {
  const exists = new Set(documents.map((d) => d.id));
  const ids = new Set<string>();
  for (const t of turns) if (t.role === "user") for (const a of t.attachments)
    if (isReady(a) && a.documentId && (!documentsReady || exists.has(a.documentId))) ids.add(a.documentId);
  return ids;
}

export interface Question {
  /** What goes with the question, as its turn shows it. */
  attachments: Attachment[];
  /** In a case: the Ask about choice, with this question's uploads once read; empty outside a case. */
  asked: Chosen[];
  /** The documents chosen for it (before the case's sources fill in when nothing is). */
  chosen: Set<string>;
  /** The documents it is answered from. */
  documentIds: string[];
}

/**
 * The question being sent. What is read goes with it; a document still being read, or one that failed, stays in
 * the composer and counts for the next question once ready. ``again`` and ``againAbout``: a question asked again
 * (Regenerate, or the retry after a colleague deleted a document) with what it had. ``documents``: the case's
 * documents as this page knows them (or as just read again for the retry); outside a case, null.
 */
export function questionFor(o: { pending: Attachment[]; again?: Attachment[]; againAbout?: Chosen[]; about: Chosen[];
                                 inCase: boolean; conversationDocs: Set<string>; documents: StoredDocument[] | null }): Question {
  const attachments = o.again ?? o.pending.filter((a) => !staysInComposer(a));
  const asked = o.inCase ? [...(o.againAbout ?? o.about)] : [];
  if (o.inCase) for (const a of attachments) if (isReady(a) && a.documentId && !asked.some((x) => x.documentId === a.documentId))
    asked.push({ documentId: a.documentId, filename: a.filename });
  const chosen = new Set(o.inCase ? asked.map((x) => x.documentId) : o.conversationDocs);
  for (const a of attachments) if (isReady(a) && a.documentId) chosen.add(a.documentId);
  // In a case with nothing chosen, the case's sources (lib/questionDocuments.ts).
  const documentIds = [...new Set(questionDocuments(chosen, o.inCase ? o.documents : null))];
  return { attachments, asked, chosen, documentIds };
}

/** The finished answer as its turn shows it. ``thought``/``thinkSeconds``: the reasoning as it streamed, for a server
 *  that didn't send it back; ``partial``: a case question whose documents weren't read in full (the last status). */
export function answerPatch(done: ChatResponse, o: { thought: string; thinkSeconds?: number; partial: boolean }): Partial<AssistantTurn> {
  const reasoning = done.reasoning || o.thought;
  return {
    text: done.answer, citations: done.citations, calculations: done.calculations ?? [],
    unverifiedFigures: done.unverified_figures ?? [], citationIssues: done.citation_issues ?? [],
    ...(done.support_spans ? { supportSpans: done.support_spans } : {}),
    instructionLikeSources: done.instruction_like_sources ?? [],
    ...(reasoning ? { reasoning, thoughtSeconds: done.thought_seconds ?? o.thinkSeconds } : {}),
    ...(done.thinking_cut ? { thinkingCut: true } : {}),
    ...(done.narrowed_to ? { narrowedTo: done.narrowed_to } : {}),
    ...(done.finish_reason === "length" ? { truncated: true } : {}),
    status: "done", model: done.model, ...(o.partial ? { partial: true } : {}),
  };
}

/**
 * What an answer that didn't finish became:
 * - ``stopped``: the person stopped it; what was written stays, unchecked.
 * - ``cutOff``: the connection dropped mid-answer; what arrived stays, with Regenerate, and the server is checked.
 * - ``maybeDeleted``: a 404 before any word, in a case, not already the retry: perhaps a colleague deleted a
 *   chosen document since this page read the list (the caller reads it again and decides, ``afterDeletion``).
 * - ``error``: anything else; any partial answer is discarded (the gateway's contract).
 */
export function failureKind(e: unknown, o: { stopped: boolean; streamed: string; inCase: boolean; retried: boolean;
                                              cutOffMessage: string }): "stopped" | "cutOff" | "maybeDeleted" | "error" {
  if (o.stopped) return "stopped";
  if (o.streamed && (e instanceof TypeError || (e as Error | null)?.message === o.cutOffMessage)) return "cutOff";
  if (e instanceof HttpError && e.status === 404 && o.inCase && !o.retried && !o.streamed) return "maybeDeleted";
  return "error";
}

/** Regenerate: offered when nothing is being written, asking is possible, and the last answer failed after its question. */
export function canRegenerate(turns: Turn[], busy: boolean, disabled: boolean): boolean {
  const last = turns[turns.length - 1];
  return !busy && !disabled && last?.role === "assistant" && last.status === "error" && turns[turns.length - 2]?.role === "user";
}
