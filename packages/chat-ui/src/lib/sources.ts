/**
 * What the source panel says about a source (docs/design/chat-ui.md §5), kept apart from the panel so it
 * can be tested: whether the claim(s) citing it were checked, and what the check found.
 */
import type { CitationIssue } from "../api";
import type { AssistantTurn } from "../types";
import { markerClaims, spanParts, type PassagePart } from "./answer";

type Verdict =
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

/**
 * The passage of source ``n`` with what the claim(s) citing it rest on marked: the claim of the marker opened (``occ``),
 * or every claim citing ``n`` (from the source list, or a marker of another source). The marking is the server's, for
 * an answer (suveryn-tracker#25) and for a playbook fact alike: the browser reads no numbers or dates of its own
 * (decision of 10 November 2026). An answer that was stopped has none: nothing of it was checked.
 */
export function sourceParts(turn: AssistantTurn, n: number, occ: number | null): PassagePart[] {
  const passage = turn.citations[n - 1]?.text ?? "";
  const one = occ === null ? undefined : markerClaims(turn.text, turn.citations.length)[occ];
  return spanParts(passage, (turn.supportSpans ?? []).filter((s) => s.n === n && (one?.n !== n || s.marker === occ)));
}

/** Whether what ``sourceParts`` marks for this source was found by meaning rather than by the same words. */
export function markedByMeaning(turn: AssistantTurn, n: number, occ: number | null): boolean {
  if (!turn.supportSpans) return false;
  const one = occ === null ? undefined : markerClaims(turn.text, turn.citations.length)[occ];
  return turn.supportSpans.some((s) => s.n === n && (one?.n !== n || s.marker === occ) && s.how === "meaning");
}
