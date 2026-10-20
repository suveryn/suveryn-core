import { describe, expect, it } from "vitest";
import type { Citation } from "../api";
import type { AssistantTurn } from "../types";
import { verdictOf } from "./sources";

const passage = (text: string, removed = false): Citation => ({ text, source: { document_id: "d1", page: 2, location: "p. 2" }, removed });
const turn = (over: Partial<AssistantTurn> = {}): AssistantTurn => ({
  id: "a1", role: "assistant", text: "The price is EUR 300,000 [1]. The deposit is EUR 30,000 [2][1].", status: "done", grounded: true,
  citations: [passage("The price is EUR 300,000."), passage("A deposit of EUR 30,000.")], citationIssues: [], ...over,
});

describe("the source panel's verdict (docs/design/sidebar.md §5)", () => {
  it("says the claim is in the passage, for a marker or for the whole source", () => {
    expect(verdictOf(turn(), 1, 0)).toEqual({ kind: "sentence" });
    expect(verdictOf(turn(), 1, null)).toEqual({ kind: "source" });
  });

  it("names what the check found: for the marker opened, or every marker citing the source", () => {
    const issue = { marker: 2, n: 1, item: "30,000", found_in: [2], written_as: null };
    const t = turn({ citationIssues: [issue] });
    expect(verdictOf(t, 1, 2)).toEqual({ kind: "issues", issues: [issue] });
    expect(verdictOf(t, 1, 0)).toEqual({ kind: "sentence" });  // another marker of the same source is fine
    expect(verdictOf(t, 1, null)).toEqual({ kind: "issues", issues: [issue] });
    expect(verdictOf(t, 2, null)).toEqual({ kind: "source" });
  });

  it("says nothing was checked for a stopped answer, and nothing at all for a deleted document", () => {
    expect(verdictOf(turn({ status: "stopped" }), 1, 0)).toEqual({ kind: "unchecked" });
    expect(verdictOf(turn({ citations: [passage("", true), passage("x")] }), 1, null)).toBeNull();
  });
});
