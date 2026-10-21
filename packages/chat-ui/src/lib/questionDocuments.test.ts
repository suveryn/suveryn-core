import { describe, expect, it } from "vitest";
import type { StoredDocument } from "../api";
import { MAX_DOCUMENTS, questionDocuments } from "./questionDocuments";

const doc = (id: string, day: number, over: Partial<StoredDocument> = {}): StoredDocument => ({
  id, filename: `${id}.pdf`, pages: 1, ocr_pages: 0, status: "ok", warnings: [], chunks: 1,
  created_at: `2026-10-${String(day).padStart(2, "0")}T10:00:00Z`, origin: "uploaded", source: true, ...over,
});

describe("the documents a question reads", () => {
  it("in a personal conversation: what was attached, nothing else", () => {
    expect(questionDocuments(["a", "b"], null)).toEqual({ ids: ["a", "b"], focus: false });
    expect(questionDocuments([], null)).toEqual({ ids: [], focus: false });
  });

  it("in a case: what was attached, or, with nothing attached, the case's sources, newest first", () => {
    const docs = [doc("old", 1), doc("new", 9), doc("other", 5)];
    expect(questionDocuments(["other"], docs)).toEqual({ ids: ["other"], focus: false });  // attaching is choosing
    expect(questionDocuments([], docs)).toEqual({ ids: ["new", "other", "old"], focus: true });  // the server narrows them
    expect(questionDocuments([], [doc("only", 1)])).toEqual({ ids: ["only"], focus: false });  // one: nothing to narrow
  });

  it("never sūveryn's own output, nor an upload waiting for the person's choice", () => {
    const docs = [doc("deed", 2), doc("answer", 3, { origin: "answer" }), doc("summary", 4, { origin: "playbook" }),
                  doc("noticed", 5, { source: false })];
    expect(questionDocuments([], docs).ids).toEqual(["deed"]);
  });

  it("at most the server's limit", () => {
    const docs = Array.from({ length: 60 }, (_, i) => doc(`d${i}`, (i % 28) + 1));
    expect(questionDocuments([], docs).ids).toHaveLength(MAX_DOCUMENTS);
  });
});
