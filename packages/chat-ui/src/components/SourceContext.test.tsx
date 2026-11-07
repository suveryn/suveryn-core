// @vitest-environment node
/**
 * Board G11: the source panel shows the passage in its context, the text before and after it dimmed; the passage
 * alone when the server sent nothing around it. Board B01: the recovery key's line says when it was last tested.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import en from "../i18n/en";
import type { AssistantTurn } from "../types";
import { keyDueLine } from "./AdminStatus";
import { SourcePanel, contextAround } from "./Messages";

const PASSAGE = "The price is EUR 300,000.";
const turn = (context?: { text: string; start: number; end: number }): AssistantTurn => ({
  id: "t1", role: "assistant", text: "The price is EUR 300,000 [1].", status: "done", grounded: true,
  citations: [{ text: PASSAGE, source: { document_id: "d1", page: 3, location: "p. 3" }, context }],
});
const none = () => {};
const panel = (t: AssistantTurn) => renderToStaticMarkup(
  <SourcePanel turn={t} open={{ n: 1, occ: null }} filenames={new Map([["d1", "deed.pdf"]])} caseRef={null} onSource={none} onClose={none} />);

describe("the passage in its context (board G11)", () => {
  const ctx = { text: `Article 2. Price. ${PASSAGE} It is paid at the deed.`, start: 18, end: 18 + PASSAGE.length };
  it("dims the text before and after the passage", () => {
    expect(contextAround({ text: PASSAGE, source: null, context: ctx })).toEqual({ before: "Article 2. Price. ", after: " It is paid at the deed." });
    const html = panel(turn(ctx));
    expect(html).toContain('<span class="source-context">Article 2. Price. </span>');
    expect(html).toContain('<span class="source-context"> It is paid at the deed.</span>');
  });
  it("shows the passage alone without context, or when the context doesn't hold it where it says", () => {
    expect(panel(turn())).not.toContain("source-context");
    expect(contextAround({ text: PASSAGE, source: null, context: { ...ctx, start: 0 } })).toBeNull();
    expect(contextAround({ text: "", source: null, removed: true, context: ctx })).toBeNull();
  });
});

describe("the recovery key's line in Needs attention (board B01)", () => {
  const now = new Date("2026-11-06T12:00:00");
  it("says when it was last tested, or that it never was", () => {
    expect(keyDueLine("2026-07-21T10:00:00Z", en, now)).toBe("Recovery key not tested since 21 July. Test every three months.");
    expect(keyDueLine("2025-07-21T10:00:00Z", en, now)).toBe("Recovery key not tested since 21 July 2025. Test every three months.");
    expect(keyDueLine(null, en, now)).toBe(en.keyNeverTested);
  });
});
