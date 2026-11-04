import { describe, expect, it } from "vitest";
import { HttpError, type ChatResponse, type StoredDocument } from "../api";
import type { AssistantTurn, Attachment, Turn, UserTurn } from "../types";
import { answerPatch, canRegenerate, conversationDocuments, failureKind, questionFor } from "./ask";

const card = (id: string, status: Attachment["status"], documentId: string | undefined = status === "ready" || status === "needs_review" ? `doc-${id}` : undefined): Attachment =>
  ({ key: id, filename: `${id}.pdf`, status, documentId });
const doc = (id: string, created_at: string, extra: Partial<StoredDocument> = {}): StoredDocument =>
  ({ id, filename: `${id}.pdf`, created_at, origin: "uploaded", ...extra }) as StoredDocument;
const user = (attachments: Attachment[]): UserTurn => ({ id: `u${Math.random()}`, role: "user", text: "?", attachments });
const answer = (status: AssistantTurn["status"]): AssistantTurn => ({ id: `a${Math.random()}`, role: "assistant", text: "", citations: [], status, grounded: true });

describe("a question's documents (App.tsx send, now lib/ask.ts)", () => {
  it("takes what is read; what is still being read or failed stays in the composer", () => {
    const pending = [card("read", "ready"), card("check", "needs_review"), card("busy", "processing"), card("bad", "failed")];
    const q = questionFor({ pending, about: [], inCase: false, conversationDocs: new Set(["doc-earlier"]), documents: null });
    expect(q.attachments.map((a) => a.key)).toEqual(["read", "check"]);
    expect(q.asked).toEqual([]);                                   // no Ask about outside a case
    expect(q.documentIds).toEqual(["doc-earlier", "doc-read", "doc-check"]);  // the conversation's, then this question's
  });

  it("in a case: the Ask about choice plus this question's uploads, chosen once and only once", () => {
    const about = [{ documentId: "doc-read", filename: "read.pdf" }, { documentId: "doc-deed", filename: "deed.pdf" }];
    const q = questionFor({ pending: [card("read", "ready"), card("new", "ready")], about, inCase: true,
                            conversationDocs: new Set(["doc-earlier"]), documents: [doc("doc-other", "2026-11-01")] });
    expect(q.asked.map((x) => x.documentId)).toEqual(["doc-read", "doc-deed", "doc-new"]);
    expect(q.documentIds).toEqual(["doc-read", "doc-deed", "doc-new"]);   // not the conversation's earlier ones, not the case's
  });

  it("in a case with nothing chosen: the case's sources, newest first, never its own output", () => {
    const documents = [doc("old", "2026-10-01"), doc("summary", "2026-11-03", { origin: "playbook" } as Partial<StoredDocument>),
                       doc("new", "2026-11-02")];
    const q = questionFor({ pending: [], about: [], inCase: true, conversationDocs: new Set(), documents });
    expect(q.chosen.size).toBe(0);
    expect(q.documentIds).toEqual(["new", "old"]);
  });

  it("asked again: with the attachments and the choice it had, not what is in the composer now", () => {
    const again = [card("then", "ready")];
    const q = questionFor({ pending: [card("now", "ready")], again, againAbout: [], about: [{ documentId: "doc-now", filename: "now.pdf" }],
                            inCase: true, conversationDocs: new Set(), documents: [] });
    expect(q.attachments).toBe(again);
    expect(q.documentIds).toEqual(["doc-then"]);
  });

  it("a conversation's documents are those attached and read, and still there once the list is known", () => {
    const turns: Turn[] = [user([card("a", "ready"), card("b", "failed")]), answer("done"), user([card("c", "needs_review")])];
    expect(conversationDocuments(turns, [], false)).toEqual(new Set(["doc-a", "doc-c"]));                 // list not read yet
    expect(conversationDocuments(turns, [doc("doc-c", "2026-11-01")], true)).toEqual(new Set(["doc-c"]));  // a was deleted
  });
});

describe("an answer", () => {
  const done = { answer: "De prijs is EUR 1.275.000,00 [1].", citations: [{ n: 1 }], model: "qwen" } as unknown as ChatResponse;

  it("finished: its text, citations and model, and nothing it didn't have", () => {
    const p = answerPatch(done, { thought: "", partial: false });
    expect(p).toMatchObject({ text: done.answer, status: "done", model: "qwen", calculations: [], unverifiedFigures: [] });
    expect(p).not.toHaveProperty("reasoning");
    expect(p).not.toHaveProperty("partial");
    expect(p).not.toHaveProperty("truncated");
  });

  it("keeps the reasoning that streamed when the server sends none back, and says when it was cut or partial", () => {
    const p = answerPatch({ ...done, finish_reason: "length", narrowed_to: "akte.pdf" } as ChatResponse,
                          { thought: "Eerst de akte…", thinkSeconds: 4.2, partial: true });
    expect(p).toMatchObject({ reasoning: "Eerst de akte…", thoughtSeconds: 4.2, truncated: true, partial: true, narrowedTo: "akte.pdf" });
  });

  const base = { stopped: false, streamed: "", inCase: true, retried: false, cutOffMessage: "cut off" };
  it("that didn't finish: stopped, cut off, perhaps a deleted document, or an error", () => {
    expect(failureKind(new DOMException("aborted"), { ...base, stopped: true })).toBe("stopped");
    expect(failureKind(new TypeError("Failed to fetch"), { ...base, streamed: "De prijs" })).toBe("cutOff");
    expect(failureKind(new Error("cut off"), { ...base, streamed: "De prijs" })).toBe("cutOff");
    expect(failureKind(new HttpError("unknown document", 404), base)).toBe("maybeDeleted");
    expect(failureKind(new HttpError("unknown document", 404), { ...base, retried: true })).toBe("error");   // asked again once only
    expect(failureKind(new HttpError("unknown document", 404), { ...base, inCase: false })).toBe("error");
    expect(failureKind(new TypeError("Failed to fetch"), base)).toBe("error");  // nothing arrived: nothing to keep
    expect(failureKind(new HttpError("busy", 503), base)).toBe("error");
  });

  it("can be asked again when the last answer failed after its question, and nothing is being written", () => {
    const failed: Turn[] = [user([]), answer("error")];
    expect(canRegenerate(failed, false, false)).toBe(true);
    expect(canRegenerate(failed, true, false)).toBe(false);
    expect(canRegenerate(failed, false, true)).toBe(false);
    expect(canRegenerate([user([]), answer("done")], false, false)).toBe(false);
    expect(canRegenerate([answer("error")], false, false)).toBe(false);
    expect(canRegenerate([], false, false)).toBe(false);
  });
});
