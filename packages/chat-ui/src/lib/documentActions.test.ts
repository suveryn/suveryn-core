import { describe, expect, it } from "vitest";
import { HttpError, type StoredDocument } from "../api";
import en from "../i18n/en";
import type { AssistantTurn, Turn, UserTurn } from "../types";
import { afterDelete, citingCheck, deleteRefusal, saveState } from "./documentActions";

const asking = (documentId?: string): UserTurn =>
  ({ id: "u", role: "user", text: "?", attachments: documentId ? [{ key: "k", filename: "deed.pdf", status: "ready", documentId }] : [] });
const answer = (extra: Partial<AssistantTurn> = {}): AssistantTurn =>
  ({ id: "a1", role: "assistant", text: "…", citations: [], status: "done", grounded: true, ...extra });
const doc = (id: string) => ({ id, filename: `${id}.pdf`, created_at: "2026-11-04" }) as StoredDocument;

describe("deleting a document (App.tsx remove and deleteNow, now lib/documentActions.ts)", () => {
  it("asks which saved conversations cite it, skips the question without history, refuses when history can't be read", () => {
    expect(citingCheck(true, "ok")).toBe("ask");
    expect(citingCheck(false, undefined)).toBe("skip");        // the health check hasn't answered yet
    expect(citingCheck(false, "unavailable")).toBe("skip");    // this server keeps no history
    expect(citingCheck(false, "failed")).toBe("refuse");       // it does, but can't be read: nothing is deleted
    expect(citingCheck(false, "starting")).toBe("refuse");
  });

  it("says why it couldn't ask: the database gone (a 503, checked at once) or the error as it came", () => {
    expect(deleteRefusal(new HttpError("Service Unavailable", 503), en)).toEqual({ why: en.conversationsUnreachable, unreachable: true });
    expect(deleteRefusal(new Error("Forbidden"), en)).toEqual({ why: "Forbidden", unreachable: false });
  });

  it("then starts afresh when the open conversation went with it, or marks the document removed where it shows", () => {
    const turns: Turn[] = [asking("d1"), answer()];
    const base = { documentId: "d1", turns, conversationId: "c-open", conversations: "delete" as const, deleted: ["c-open", "c-other"] };
    expect(afterDelete(base)).toBe("new");
    expect(afterDelete({ ...base, deleted: ["c-other"] })).toBe("clean");               // kept, and it shows the document
    expect(afterDelete({ ...base, conversations: "clean" })).toBe("clean");
    expect(afterDelete({ ...base, conversations: "clean", turns: [asking(), answer()] })).toBe("keep");  // never showed it
    const cited: Turn[] = [asking(), answer({ citations: [{ n: 1, source: { document_id: "d1" } }] as unknown as AssistantTurn["citations"] })];
    expect(afterDelete({ ...base, conversations: "clean", turns: cited })).toBe("clean");  // cited in an answer counts too
  });
});

describe("save to case", () => {
  const where = { inCase: true, contributes: true, closed: false, readOnly: false, savedHere: new Set<string>(), documents: [doc("saved-1")] };
  const saved = { documentId: "saved-1", filename: "Answer.docx" };

  it("is offered on a finished answer in an open case, to a contributor only", () => {
    expect(saveState(answer(), where)).toEqual({ saved: null, undoable: false });
    for (const not of [{ inCase: false }, { contributes: false }, { closed: true }, { readOnly: true }])
      expect(saveState(answer(), { ...where, ...not })).toBeNull();
    expect(saveState(answer({ status: "streaming" }), where)).toBeNull();
    expect(saveState(answer({ status: "error" }), where)).toBeNull();
  });

  it("shows where it was saved while that document exists, with Undo only on this page", () => {
    expect(saveState(answer({ saved }), where)).toEqual({ saved, undoable: false });                       // saved earlier
    expect(saveState(answer({ saved }), { ...where, savedHere: new Set(["a1"]) })).toEqual({ saved, undoable: true });
    expect(saveState(answer({ saved }), { ...where, documents: [] })).toEqual({ saved: null, undoable: false });  // deleted since
    expect(saveState(answer({ saved }), { ...where, documents: [], savedHere: new Set(["a1"]) }))
      .toEqual({ saved, undoable: true });   // just saved here, before the list is read again
  });
});
