import { describe, expect, it } from "vitest";
import type { StoredDocument } from "../api";
import { afterDeletion, MAX_DOCUMENTS, questionDocuments } from "./questionDocuments";

const doc = (id: string, day: number, over: Partial<StoredDocument> = {}): StoredDocument => ({
  id, filename: `${id}.pdf`, pages: 1, ocr_pages: 0, status: "ok", warnings: [], chunks: 1,
  created_at: `2026-10-${String(day).padStart(2, "0")}T10:00:00Z`, origin: "uploaded", source: true, ...over,
});

describe("the documents a question reads", () => {
  it("in a personal conversation: what was attached, nothing else", () => {
    expect(questionDocuments(["a", "b"], null)).toEqual(["a", "b"]);
    expect(questionDocuments([], null)).toEqual([]);
  });

  it("in a case: what was attached, or, with nothing attached, the case's sources, newest first", () => {
    const docs = [doc("old", 1), doc("new", 9), doc("other", 5)];
    expect(questionDocuments(["other"], docs)).toEqual(["other"]);  // attaching is choosing
    expect(questionDocuments([], docs)).toEqual(["new", "other", "old"]);
  });

  it("never sūveryn's own output, nor an upload waiting for the person's choice", () => {
    const docs = [doc("deed", 2), doc("answer", 3, { origin: "answer" }), doc("summary", 4, { origin: "playbook" }),
                  doc("noticed", 5, { source: false })];
    expect(questionDocuments([], docs)).toEqual(["deed"]);
  });

  it("at most the server's limit", () => {
    const docs = Array.from({ length: 60 }, (_, i) => doc(`d${i}`, (i % 28) + 1));
    expect(questionDocuments([], docs)).toHaveLength(MAX_DOCUMENTS);
  });
});

describe("a question refused because a document was deleted meanwhile (Pod check of 547f48e)", () => {
  const now = [doc("kept", 1), doc("answer", 2, { origin: "generated", source: false })];
  it("about the whole case: asked again with the sources there are now", () => {
    expect(afterDeletion(["kept", "deleted"], 0, now)).toBe("retry");
  });
  it("about chosen documents: the person is told one is gone", () => {
    expect(afterDeletion(["kept", "deleted"], 2, now)).toBe("chosenGone");
  });
  it("nothing was deleted, or nothing is left: the refusal stands", () => {
    expect(afterDeletion(["kept"], 0, now)).toBeNull();
    expect(afterDeletion(["deleted"], 0, [doc("answer", 2, { origin: "generated", source: false })])).toBeNull();
  });
});
