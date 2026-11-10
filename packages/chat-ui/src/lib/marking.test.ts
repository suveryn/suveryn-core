/**
 * The source card shows the server's marking (suveryn-tracker#25; decision of 10 November 2026: the browser reads no
 * numbers, dates or sentences of a passage itself). What is marked is tested where it is worked out
 * (harness/tests/test_marking.py, marking_cases.json); here: which marker a click is, and that the card shows the
 * server's ranges for it. Fictional text only.
 */
import { describe, expect, it } from "vitest";
import { answerSentences, markerClaims, spanParts, toBlocks, type PassagePart } from "./answer";
import { markedByMeaning, sourceParts } from "./sources";
import type { AssistantTurn } from "../types";

/** The marked runs of a passage: consecutive marked parts joined. */
const runs = (parts: PassagePart[]) => parts.reduce<string[]>((acc, p, i) => {
  if (!p.mark) return acc;
  if (i > 0 && parts[i - 1].mark) acc[acc.length - 1] += p.text; else acc.push(p.text);
  return acc;
}, []);
const strong = (parts: PassagePart[]) => parts.filter((p) => p.mark === "term").map((p) => p.text);

describe("which claim a marker is", () => {
  it("numbers the markers as the answer shows them, each with the claim before it (reported: a table of rows)", () => {
    const answer = "| Nr | Vak | Bron |\n| --- | --- | --- |\n| 3 | Functie van het slachtoffer | [1] |\n" +
      "| 12 | Datum werkhervatting na ongeval | [1] |\n\nZie ook [2].";
    const markers = markerClaims(answer, 2);
    const occ = toBlocks(answer, 2).flatMap((b) => (b.kind === "table" ? b.rows.flat(2) : b.segments)).filter((x) => x.kind === "cite");
    expect(occ.map((x) => (x.kind === "cite" ? [x.n, x.occ] : null))).toEqual([[1, 0], [1, 1], [2, 2]]);
    expect(markers.map((x) => x.n)).toEqual([1, 1, 2]);
    expect(markerClaims("Zie [9].", 3)).toEqual([]);  // a marker past the citations names nothing
  });

  it("doesn't end a sentence at an abbreviation or an initial", () => {
    expect(markerClaims("Under art. 3 the seller bears the costs of the survey [1].", 1)[0].claim)
      .toBe("Under art. 3 the seller bears the costs of the survey");
    expect(answerSentences("See no. 4 and p. 12 of the annex. J. Smith signed it.")).toEqual(["See no. 4 and p. 12 of the annex.", "J. Smith signed it."]);
  });
});

describe("the server's marking (suveryn-tracker#25, step 2)", () => {
  const passage = "The lease runs nine years. Either party may give notice of 12 weeks.";
  const turn = (spans?: AssistantTurn["supportSpans"]): AssistantTurn => ({
    id: "a", role: "assistant", status: "done", grounded: true, text: "The notice period is twelve weeks [1]. It runs nine years [1].",
    citations: [{ text: passage, source: { document_id: "d", page: null, location: null } }], ...(spans ? { supportSpans: spans } : {}),
  });

  it("shows the server's ranges for the marker opened, or every marker's from the source list", () => {
    const spans = [{ marker: 0, n: 1, ranges: [[27, 68]] as [number, number][], facts: [[59, 61]] as [number, number][] },
                   { marker: 1, n: 1, ranges: [[0, 26]] as [number, number][], facts: [] }];
    expect(runs(sourceParts(turn(spans), 1, 0))).toEqual(["Either party may give notice of 12 weeks."]);
    expect(strong(sourceParts(turn(spans), 1, 0))).toEqual(["12"]);
    expect(runs(sourceParts(turn(spans), 1, 1))).toEqual(["The lease runs nine years."]);
    expect(runs(sourceParts(turn(spans), 1, null))).toEqual(["The lease runs nine years.", "Either party may give notice of 12 weeks."]);
    // the server marked nothing for a marker: nothing is marked, no guess
    expect(runs(sourceParts(turn([]), 1, 0))).toEqual([]);
    // out of bounds is clipped
    expect(runs(spanParts("short", [{ ranges: [[2, 99]], facts: [] }]))).toEqual(["ort"]);
  });

  it("says when a sentence was found by meaning (step 3)", () => {
    const spans = [{ marker: 0, n: 1, ranges: [[27, 68]] as [number, number][], facts: [], how: "meaning" as const },
                   { marker: 1, n: 1, ranges: [[0, 26]] as [number, number][], facts: [], how: "words" as const }];
    expect(markedByMeaning(turn(spans), 1, 0)).toBe(true);
    expect(markedByMeaning(turn(spans), 1, 1)).toBe(false);
    expect(markedByMeaning(turn(spans), 1, null)).toBe(true);
    expect(markedByMeaning(turn(), 1, 0)).toBe(false);
  });

  it("marks nothing without the server's marking (an answer that was stopped: nothing of it was checked)", () => {
    expect(runs(sourceParts(turn(), 1, 0))).toEqual([]);
    expect(sourceParts(turn(), 1, null)).toEqual([{ text: passage, mark: null }]);
  });
});
