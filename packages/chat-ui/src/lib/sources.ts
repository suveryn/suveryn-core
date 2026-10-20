/**
 * What the source panel says about a source (docs/design/sidebar.md §5), kept apart from the panel so it
 * can be tested: whether the claim(s) citing it were checked, and what the check found.
 */
import type { CitationIssue } from "../api";
import type { AssistantTurn } from "../types";

export type Verdict =
  | { kind: "sentence" }    // opened from a marker: everything in its sentence is in the passage
  | { kind: "source" }      // opened from the source list: everything the answer takes from it is
  | { kind: "unchecked" }   // the answer was stopped: nothing was checked
  | { kind: "issues"; issues: CitationIssue[] }
  | null;                   // the document was deleted: nothing to check against

/** ``occ``: the marker opened (its occurrence in the answer), or null from the source list (every claim citing ``n``). */
export function verdictOf(turn: AssistantTurn, n: number, occ: number | null): Verdict {
  if (turn.citations[n - 1]?.removed) return null;
  if (turn.status !== "done") return { kind: "unchecked" };
  const issues = (turn.citationIssues ?? []).filter((i) => (occ === null ? i.n === n : i.marker === occ));
  if (issues.length) return { kind: "issues", issues };
  return { kind: occ === null ? "source" : "sentence" };
}
