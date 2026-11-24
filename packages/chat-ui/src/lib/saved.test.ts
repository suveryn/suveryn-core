import { describe, expect, it } from "vitest";
import JSZip from "jszip";
import type { Citation } from "../api";
import { setLang, t } from "../i18n";
import type { AssistantTurn } from "../types";
import documents from "../../../api-gateway/tests/documents_answers.json";
import { answerExport, savedTurn, savedWord, type SavedAnswer } from "./saved";

const passage: Citation = { text: "The price is EUR 300,000.", source: { document_id: "d1", page: 2, location: "p. 2" } };
const turn: AssistantTurn = {
  id: "turn-1", role: "assistant", text: "The price is EUR 300,000 [1].", citations: [passage], status: "done", grounded: true,
  model: "Qwen3.8-27B", calculations: [], unverifiedFigures: [], citationIssues: [], instructionLikeSources: [],
};

/** An answer as the gateway saves it to its case, copied from the answer it stored (conversations.SavedAnswer, #251). */
const saved: SavedAnswer = {
  question: "What is the price?", answer: turn.text, answeredOn: "2026-10-19T10:00:00Z", model: turn.model, citations: [passage],
  calculations: [], unverifiedFigures: [], citationIssues: [], instructionLikeSources: [], supportSpans: [],
  filenames: { d1: "deed.pdf" }, turnId: "turn-1", caseRef: "2026/0611",
};

describe("an answer saved to its case (docs/design/chat-ui.md §5)", () => {
  it("gives it back as the answer it was, to build the same Word file", () => {
    setLang("en", false);
    const again = savedTurn(JSON.parse(JSON.stringify(saved)));  // as it comes back from the server
    const nameOf = () => "deed.pdf";
    const when = new Date(saved.answeredOn);
    const before = answerExport({ ...turn, supportSpans: [] }, "What is the price?", nameOf, t(), "2026/0611", when);
    expect(answerExport(again, "What is the price?", nameOf, t(), "2026/0611", when)).toEqual(before);
    expect(before.mark).toMatch(/sūveryn-ref A-[0-9a-f]{8}$/);  // the same reference: built from the answer's id
  });

  it("builds the Word file again, mark and a deleted source's note included", async () => {
    setLang("en", false);
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

  it("builds the Word file of an answer the server copied from the one it stored (#251)", async () => {
    setLang("en", false);
    const copied = documents.content_from_turn.body.content as unknown as SavedAnswer;
    expect(Object.keys(copied).sort()).toEqual(Object.keys(saved).sort());
    const zip = await JSZip.loadAsync(await (await savedWord(copied, t(), "en")).arrayBuffer());
    const body = await zip.file("word/document.xml")!.async("string");
    const footers = await Promise.all(Object.keys(zip.files).filter((f) => /word\/footer\d*\.xml/.test(f)).map((f) => zip.file(f)!.async("string")));
    expect(body).toContain(copied.question);
    expect(footers.join("")).toMatch(/sūveryn-ref A-[0-9a-f]{8}/);
  });
});
