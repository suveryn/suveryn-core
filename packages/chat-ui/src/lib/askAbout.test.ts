import { describe, expect, it } from "vitest";
import type { StoredDocument } from "../api";
import type { Turn } from "../types";
import { choosable, pickMeta, restoreAbout, stillThere } from "./askAbout";

const doc = (id: string, day: number, over: Partial<StoredDocument> = {}): StoredDocument => ({
  id, filename: `${id}.pdf`, pages: 3, ocr_pages: 0, status: "ok", warnings: [],
  created_at: `2026-10-${String(day).padStart(2, "0")}T10:00:00Z`, origin: "uploaded", source: true, ...over,
});
const asked = (text: string, extra: object = {}): Turn => ({ id: text, role: "user", text, attachments: [], ...extra });

describe("Ask about", () => {
  it("restores the last question's choice when a conversation is opened again", () => {
    const turns = [asked("one", { about: [{ documentId: "a", filename: "a.pdf" }] }),
                   asked("two", { about: [{ documentId: "b", filename: "b.pdf" }, { documentId: "c", filename: "", removed: true }] })];
    expect(restoreAbout(turns)).toEqual([{ documentId: "b", filename: "b.pdf" }]);
    expect(restoreAbout([asked("whole case")])).toEqual([]);
  });

  it("takes a conversation from before Ask about at its attached documents", () => {
    const att = (id: string, status = "ready") => ({ key: id, filename: `${id}.pdf`, status, documentId: id });
    const turns = [asked("one", { attachments: [att("a"), att("x", "failed")] }), asked("two", { attachments: [att("a"), att("b", "needs_review")] })];
    expect(restoreAbout(turns as Turn[])).toEqual([{ documentId: "a", filename: "a.pdf" }, { documentId: "b", filename: "b.pdf" }]);
  });

  it("offers only the case's sources, newest first", () => {
    const docs = [doc("old", 1), doc("answer", 9, { origin: "answer" }), doc("new", 5), doc("waiting", 6, { source: false })];
    expect(choosable(docs).map((d) => d.id)).toEqual(["new", "old"]);
  });

  it("drops documents that left the case, and says so when none remain", () => {
    const docs = [doc("a", 1, { filename: "a-renamed.pdf" })];
    expect(stillThere([{ documentId: "a", filename: "a.pdf" }, { documentId: "b", filename: "b.pdf" }], docs))
      .toEqual({ about: [{ documentId: "a", filename: "a-renamed.pdf" }], gone: false });
    expect(stillThere([{ documentId: "b", filename: "b.pdf" }], docs)).toEqual({ about: [], gone: true });
    expect(stillThere([], docs)).toEqual({ about: [], gone: false });
  });

  it("describes a row by kind, pages, who added it and when", () => {
    expect(pickMeta(doc("deed", 12, { pages: 14 }), "Mieke", "en-GB")).toBe("PDF · 14 p. · Mieke, 12 Oct");
    expect(pickMeta(doc("prices", 3, { filename: "prices.xlsx", pages: 0 }), "", "en-GB")).toBe("Excel · 3 Oct");
  });
});
