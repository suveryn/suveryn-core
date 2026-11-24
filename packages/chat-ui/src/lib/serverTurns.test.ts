/** A conversation the server keeps (suveryn-tracker#251): its turns read back as the screen shows them. The server
 *  keeps it as a tree, as Claude and ChatGPT do (each turn names the turn it follows); the screen shows one branch. */
import { describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { Turn } from "../types";
import { answerStored, answerTo, fromSaved, readTurns, shownBranch } from "./conversations";
import { saveState } from "./documentActions";
import { askedAgain, toFollow, withStored } from "./ask";
import type { StoredDocument } from "../api";

const CID = "00000000-0000-4000-8000-0000000000a1";
const DEED = "11111111-1111-4111-8111-111111111111";
const question = (seq: number, text: string, parent: number | null, more: object = {}) =>
  ({ seq, role: "user", text, kind: "question", parent, document_ids: [], about: [], attached: [], model: null, thinking: false, ...more });
const answer = (seq: number, text: string, parent: number, more: object = {}) =>
  ({ seq, role: "assistant", text, kind: "answer", parent, outcome: "done", model: "Qwen3.8-27B", citations: [], calculations: [],
     unverified_figures: [], citation_issues: [], support_spans: [], instruction_like_sources: [], reasoning: "", thought_seconds: null,
     thinking_cut: false, narrowed_to: null, complete: null, asked_again: false, finish_reason: "stop", failure: null, ...more });
const stored = (...turns: object[]) => turns as unknown as Turn[];

describe("a conversation the server keeps as a tree", () => {
  it("shows the newest answer of each question, and what followed that one", () => {
    // q1 answered twice (Regenerate); q2 followed the first answer, q3 the second
    const turns = [question(1, "q1", null), answer(2, "a1", 1), answer(3, "a1b", 1), question(4, "q2", 2), answer(5, "a2", 4),
                   question(6, "q3", 3), answer(7, "a3", 6)];
    expect(shownBranch(turns).map((t) => t.seq)).toEqual([1, 3, 6, 7]);
    expect(shownBranch([question(1, "q1", null), answer(2, "a1", 1), question(3, "q2", 2), answer(4, "a2", 3), answer(5, "a2b", 3)])
      .map((t) => t.text)).toEqual(["q1", "a1", "q2", "a2b"]);
  });

  it("goes on after turns the chat UI saved itself, which follow the one before", () => {
    const turns = [{ seq: 1, role: "user", text: "q1" }, { seq: 2, role: "assistant", text: "a1", status: "done" },
                   question(3, "q2", 2), answer(4, "a2", 3)];
    expect(shownBranch(turns).map((t) => t.seq)).toEqual([1, 2, 3, 4]);
  });
});

describe("a turn the server stored, as the screen shows it", () => {
  it("a question with the documents it showed, named as they are now, a deleted one taken out", () => {
    const [q] = fromSaved(stored(question(1, "Wat is de prijs?", null, { attached: [DEED], about: ["gone"] })), CID,
                          (id) => (id === DEED ? "akte.pdf" : undefined));
    expect(q).toEqual({ id: `${CID}/1`, seq: 1, byServer: true, parent: null, role: "user", text: "Wat is de prijs?",
                        attachments: [{ key: DEED, status: "ready", documentId: DEED, filename: "akte.pdf" }],
                        about: [{ documentId: "gone", filename: "", removed: true }] });
  });

  it("an answer written out, with its checks, Thorough, and the document it was narrowed to by name", () => {
    const [, a] = fromSaved(stored(question(1, "q", null, { document_ids: [DEED], thinking: true }),
                                   answer(2, "€ 1 [1]", 1, { unverified_figures: ["€ 9"], narrowed_to: DEED, finish_reason: "length" })),
                            CID, () => "akte.pdf");
    expect(a).toMatchObject({ id: `${CID}/2`, seq: 2, role: "assistant", text: "€ 1 [1]", status: "done", grounded: true, thinking: true,
                              unverifiedFigures: ["€ 9"], narrowedTo: "akte.pdf", truncated: true, model: "Qwen3.8-27B" });
  });

  it("an answer stopped keeps its words, unchecked; a failed one says why, in the reader's language", () => {
    setLang("en", false);
    const [, stopped, , failed] = fromSaved(stored(question(1, "q", null), answer(2, "De prijs is", 1, { outcome: "stopped" }),
                                                   question(3, "q2", 2), answer(4, "", 3, { outcome: "failed",
                                                     failure: { kind: "unavailable", code: "model.unavailable", params: {} } })), CID);
    expect(stopped).toMatchObject({ text: "De prijs is", status: "stopped" });
    expect(failed).toMatchObject({ text: "", status: "error", failure: { code: "model.unavailable" } });
    expect((failed as { error: string }).error.length).toBeGreaterThan(10);
  });
});

describe("an answer saved to its case before, found again", () => {
  it("by the document the server copied from it, which names it", () => {
    const [, a] = fromSaved(stored(question(1, "q", null), answer(2, "€ 1", 1)), CID);
    const document = { id: "doc-1", filename: "q.docx", origin: "answer", provenance: { conversation: CID, message: `${CID}/2` } } as unknown as StoredDocument;
    const state = (documents: StoredDocument[]) => saveState(a as never, { inCase: true, contributes: true, closed: false, readOnly: false,
                                                                          savedHere: new Set(), documents });
    expect(state([document])).toEqual({ saved: { documentId: "doc-1", filename: "q.docx" }, undoable: false });
    expect(state([])).toEqual({ saved: null, undoable: false });
  });
});

describe("the answer to a question, by the question it answers (never by its place)", () => {
  it("the newest answer that follows it, or, saved whole, the turn after it", () => {
    const turns = [question(1, "q1", null), answer(2, "a1", 1), question(3, "q2", 2), answer(4, "a2", 3), answer(5, "a2b", 3)];
    expect([answerTo(turns, 1), answerTo(turns, 3), answerTo(turns, 9)]).toEqual([2, 5, undefined]);
    expect(answerTo([question(1, "q1", null)], 1)).toBeUndefined();  // not stored yet
    expect(answerTo(turns, 3, new Set([5]))).toBe(4);  // a version this page knew isn't the one asked for just now
    expect(answerTo(turns, 3, new Set([4, 5]))).toBeUndefined();
    expect(answerTo([{ seq: 1, role: "user", text: "q" }, { seq: 2, role: "assistant", text: "a" }], 1)).toBe(2);
  });

  it("stopped before the stream said its number, it is read again until stored, or given up on", async () => {
    const stored = [question(1, "q1", null), answer(2, "a1", 1)];
    const reads = [() => Promise.reject(new Error("down")), () => Promise.resolve([question(1, "q1", null)]), () => Promise.resolve(stored)];
    let n = 0;
    const read = () => reads[Math.min(n++, reads.length - 1)]();
    expect(await answerStored(read, 1, new Set(), 5, 0)).toEqual({ answer: 2, turns: stored });
    expect(n).toBe(3);  // unreadable, not stored yet, there
    expect(await answerStored(() => Promise.resolve(stored), 1, new Set([2]), 3, 0)).toBeUndefined();  // only known ones
  });
});

describe("turns read back", () => {
  it("follow the turn the server says, and turns saved whole follow none (no versions)", () => {
    expect(readTurns([question(1, "q1", null), answer(2, "a1", 1)] as never).map((t) => t.parent)).toEqual([null, 1]);
    expect(readTurns([{ seq: 1, role: "user", text: "q" }, { seq: 2, role: "assistant", text: "a" }] as never)
      .map((t) => t.parent)).toEqual([undefined, undefined]);
  });
});

describe("the numbers the server says as it answers", () => {
  const asked: Turn[] = [{ id: "u1", role: "user", text: "q", attachments: [] },
                         { id: "a1", role: "assistant", text: "", citations: [], status: "streaming", grounded: false }];

  it("go on the question first, then on its answer once stored; a refused question never gets one", () => {
    const first = withStored(asked, "u1", "a1", { question: 7, answer: null });
    expect(first.map((t) => [t.seq, t.byServer])).toEqual([[7, true], [undefined, undefined]]);
    const both = withStored(first, "u1", "a1", { question: 7, answer: 8 });
    expect(both.map((t) => [t.id, t.seq, t.byServer])).toEqual([["u1", 7, true], ["a1", 8, true]]);
    expect(asked.map((t) => t.seq)).toEqual([undefined, undefined]);  // nothing said: nothing numbered
  });

  it("Regenerate asks the stored question again by its number, a question saved whole as a new one", () => {
    const stored = { id: "u1", role: "user" as const, text: "q", attachments: [], seq: 7, byServer: true };
    expect([askedAgain(stored, true), askedAgain(stored, false), askedAgain({ ...stored, byServer: undefined }, true)])
      .toEqual([7, undefined, undefined]);
  });
});

describe("what a new question follows", () => {
  const turn = (id: string, role: "user" | "assistant", seq?: number) => (role === "user"
    ? { id, role, text: id, attachments: [], ...(seq !== undefined ? { seq, byServer: true } : {}) }
    : { id, role, text: id, citations: [], status: "done", grounded: false, ...(seq !== undefined ? { seq, byServer: true } : {}) }) as Turn;

  it("the newest numbered answer, past a question the server refused (review of step 3a, N1)", () => {
    // answered; then refused before anything was stored (another tab answering, a model gone): never numbered
    const turns = [turn("q1", "user", 1), turn("a1", "assistant", 2), turn("q2", "user"), turn("a2", "assistant")];
    expect(toFollow(turns)).toEqual({ after: 2 });
    // and Regenerate on the refused question asks it as a new one, after that same answer
    expect(askedAgain(turns[2] as never, true)).toBeUndefined();
    expect(toFollow([...turns, turn("q3", "user"), turn("a3", "assistant")])).toEqual({ after: 2 });
  });

  it("a stopped answer, not numbered yet, is looked up by its question; before it, what was numbered", () => {
    const turns = [turn("q1", "user", 1), turn("a1", "assistant", 2), turn("q2", "user", 3), turn("a2", "assistant")];
    const next = toFollow(turns);
    expect(next).toMatchObject({ lookUp: 3 });
    expect(toFollow((next as { otherwise: Turn[] }).otherwise)).toEqual({ after: 2 });
    expect(toFollow([turn("q1", "user"), turn("a1", "assistant")])).toBeNull();  // the first question
  });
});

