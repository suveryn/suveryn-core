import { describe, expect, it } from "vitest";
import JSZip from "jszip";
import type { Citation } from "../api";
import { setLang, t } from "../i18n";
import type { AssistantTurn } from "../types";
import { answerExport, answerFileName, savedAnswer, savedTurn, savedWord, searchText } from "./saved";

const passage: Citation = { text: "The price is EUR 300,000.", source: { document_id: "d1", page: 2, location: "p. 2" } };
const turn: AssistantTurn = {
  id: "turn-1", role: "assistant", text: "The price is EUR 300,000 [1].", citations: [passage], status: "done", grounded: true,
  model: "Qwen3.8-27B", calculations: [], unverifiedFigures: [], citationIssues: [], instructionLikeSources: [],
};

describe("an answer saved to its case (docs/design/chat-ui.md §5)", () => {
  it("names the file after the question, without what a file name can't hold", () => {
    expect(answerFileName("What is the price?")).toBe("What is the price.docx");
    expect(answerFileName("Price / costs: 2026*")).toBe("Price costs 2026.docx");
    expect(answerFileName("x".repeat(200))).toBe(`${"x".repeat(80)}.docx`);
    expect(answerFileName("???")).toBe("answer.docx");
  });

  it("keeps what builds the same Word file, and gives it back as the answer it was", () => {
    setLang("en", false);
    const saved = savedAnswer(turn, "What is the price?", new Map([["d1", "deed.pdf"], ["d9", "other.pdf"]]), "2026/0611",
                              new Date("2026-10-19T10:00:00Z"));
    expect(saved.filenames).toEqual({ d1: "deed.pdf" });  // only the sources it has
    expect(searchText(saved)).toBe("What is the price?\n\nThe price is EUR 300,000.");
    const again = savedTurn(JSON.parse(JSON.stringify(saved)));  // as it comes back from the server
    const nameOf = () => "deed.pdf";
    const when = new Date(saved.answeredOn);
    const before = answerExport(turn, "What is the price?", nameOf, t(), "2026/0611", when);
    expect(answerExport(again, "What is the price?", nameOf, t(), "2026/0611", when)).toEqual(before);
    expect(before.mark).toMatch(/sūveryn-ref A-[0-9a-f]{8}$/);  // the same reference: built from the answer's id
  });

  it("builds the Word file again, mark and a deleted source's note included", async () => {
    setLang("en", false);
    const saved = savedAnswer(turn, "What is the price?", new Map([["d1", "deed.pdf"]]), "2026/0611");
    const removed = { ...saved, citations: [{ text: "", source: { document_id: "d1", page: 2, location: null }, removed: true }], filenames: {} };
    for (const [s, expected] of [[saved, "deed.pdf"], [removed, t().sourceRemoved]] as const) {
      const zip = await JSZip.loadAsync(await (await savedWord(s, t(), "en")).arrayBuffer());
      const body = await zip.file("word/document.xml")!.async("string");
      const footers = await Promise.all(Object.keys(zip.files).filter((f) => /word\/footer\d*\.xml/.test(f)).map((f) => zip.file(f)!.async("string")));
      expect(body).toContain("What is the price?");
      expect(body).toContain(expected);
      expect(footers.join("")).toMatch(/sūveryn-ref A-[0-9a-f]{8}/);
    }
  });
});
