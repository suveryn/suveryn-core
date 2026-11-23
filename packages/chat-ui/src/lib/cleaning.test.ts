/** A saved conversation is the chat UI's own data (for now: the server will store each turn, suveryn-tracker#251): the
 *  gateway keeps it as it is and reads in it only the documents it names, to take a deleted one's passages and file
 *  name out. These tests hold the two together: every member of a saved turn says whether it names a document, and the
 *  chat UI's clean-up and the gateway's run on the same saved turns (packages/api-gateway/tests/saved_turns_to_clean.json). */
import { describe, expect, it } from "vitest";
import cases from "../../../api-gateway/tests/saved_turns_to_clean.json";
import type { AssistantTurn, Attachment, Chosen, Turn, UserTurn } from "../types";
import type { Citation } from "../api";
import type { SavedAnswer } from "./saved";
import { withoutDocument } from "./conversations";

/** How a member of what the chat UI saves names a document. "id": by its id, where the gateway's clean-up looks for it
 *  (conversations.py ``_references``, the rag's ``without``) and the chat UI's (`withoutDocument`); "no": it names none.
 *  Adding a member to a saved turn or a saved answer fails the typecheck here until it says which. */
type Names = "id" | "no" | "own" | "by name";
const TURN: Record<keyof UserTurn | keyof AssistantTurn, Names> = {
  id: "no", role: "no", text: "no", attachments: "id", about: "id",
  citations: "id", calculations: "no", unverifiedFigures: "no", citationIssues: "no", supportSpans: "no", instructionLikeSources: "no",
  partial: "no", status: "no", step: "no", grounded: "no", error: "no", failure: "no", cutOff: "no", model: "no", thinking: "no", reasoning: "no",
  thoughtSeconds: "no", thinkingCut: "no", truncated: "no",
  saved: "own",          // the answer's own copy saved to the case: its name is the conversation's question, not a source's
  narrowedTo: "by name", // the one document the question named, by its file name: not taken out when it is deleted (a gap of its own)
};
const ATTACHMENT: Record<keyof Attachment | keyof Chosen, Names> = {
  key: "no", filename: "id", status: "no", jobId: "no", documentId: "id", error: "no", progress: "no", pages: "no", reading: "no", failure: "no",
  lost: "no", reviewPages: "no", reviewKind: "no", note: "no", removed: "no", noticed: "no", notAdded: "no", archive: "no",
};
const CITATION: Record<keyof Citation, Names> = { text: "id", source: "id", context: "id", removed: "no" };
const ANSWER: Record<keyof SavedAnswer, Names> = {
  question: "no", answer: "no", answeredOn: "no", model: "no", citations: "id", calculations: "no", unverifiedFigures: "no", citationIssues: "no",
  supportSpans: "no", instructionLikeSources: "no", filenames: "id", turnId: "no", caseRef: "no",
};

describe("what the chat UI saves, and a deleted document", () => {
  it("names a document only where the clean-up looks", () => {
    const by = (table: Record<string, Names>) => Object.entries(table).filter(([, how]) => how === "id").map(([member]) => member).sort();
    expect(by(TURN)).toEqual(["about", "attachments", "citations"]);
    expect(by(ATTACHMENT)).toEqual(["documentId", "filename"]);
    expect(by(CITATION)).toEqual(["context", "source", "text"]);
    expect(by(ANSWER)).toEqual(["citations", "filenames"]);
  });

  it("loses the document's passages and file name, as the gateway takes them out, and keeps the rest", () => {
    const cleaned = JSON.stringify(withoutDocument(cases.turns as Turn[], cases.deleted));
    expect(cases.gone.filter((gone) => cleaned.includes(gone))).toEqual([]);
    expect(cases.stays.filter((stays) => !cleaned.includes(stays) && !JSON.stringify(cases.answer).includes(stays))).toEqual([]);
  });
});
