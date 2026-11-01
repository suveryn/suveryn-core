/**
 * VM regression 03c8f74: the findings fixed in the chat UI, each where a test can reach it.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Case, PlaybookInfo, Run, RunFact } from "../api";
import en from "../i18n/en";
import nl from "../i18n/nl";
import type { AssistantTurn } from "../types";
import { AnswerNotes } from "./Messages";
import { RunThread, reviewGroups } from "./RunConversation";

const PLAYBOOK = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.1", name: "Deed intake", covered: true,
  facts: ["deadline", "soil"], steps: [{ id: "confirm", kind: "checkpoint", needs: [], facts: [] }],
  text: { en: { title: "Deed intake", summary: "", labels: { deadline: "Deed deadline", soil: "Soil certificate" } } },
} as PlaybookInfo;
const at = "2026-11-01T10:00:00Z";
const DEADLINE: RunFact = {
  id: "deadline", value: "uiterlijk vier maanden na de opschortende voorwaarde", found: true, confirmed: null, source: "document", issues: [],
  needs: "not_a_date", citations: [{ n: 1, document_id: "d1", filename: "compromis.pdf", page: 3, location: null,
                                      text: "De akte wordt verleden uiterlijk vier maanden na de vervulling van de opschortende voorwaarde." }],
};
const RUN = {
  id: "r1", case_id: "c1", playbook_id: PLAYBOOK.id, playbook_version: "1.1", status: "waiting", documents: ["d1"], started_by: "alice",
  started_at: at, finished_at: null, confirmed_by: null, confirmed_at: null, model: null, error: null, result_document_id: null,
  out_of_date: false, language: "en", paused_by: null, paused_at: null, ended_by: null, ended_reason: null, starter: "u-alice",
  conversation_id: "conv", instruction_like_sources: [], steps: {}, step: "confirm",
  facts: [DEADLINE, { id: "soil", value: "", citations: [], issues: [], found: false, confirmed: null, source: "none" }],
  turns: [
    { seq: 1, role: "playbook", step_id: "confirm", by: PLAYBOOK.id, at, text: "", meta: { kind: "checkpoint", found: 1, total: 2, issues: 0 } },
    { seq: 2, role: "user", step_id: "confirm", by: "alice", at, text: "Soil certificate: not known yet.", meta: {} },
    { seq: 3, role: "playbook", step_id: "confirm", by: PLAYBOOK.id, at, text: "", meta: { kind: "already_unknown", facts: ["soil"] } },
  ],
} as unknown as Run;
const KASE = { id: "c1", reference: "TEST-R", name: "Test", type: "sale", state: "open", manager: "u-alice" } as unknown as Case;
const words = { title: "Deed intake", summary: "", labels: { deadline: "Deed deadline", soil: "Soil certificate" } };
const esc = (s: string) => s.replaceAll("'", "&#x27;");
const thread = renderToStaticMarkup(
  <RunThread run={RUN} kase={KASE} playbook={PLAYBOOK} words={words} me="u-alice" canAnswer nameOf={(u) => u} panel={null}
             onChanged={() => undefined} onPanel={() => undefined} onDocumentsChanged={() => undefined} />);

describe("Check by meaning (decision 1)", () => {
  it("puts a deadline that isn't a date under Check, and says why", () => {
    expect(reviewGroups(RUN).check.map((f) => f.id)).toEqual(["deadline"]);
    expect(thread).toContain(esc(en.pbNotADate));
    expect(thread).toContain(en.pbGroupCheck);
    expect(thread).not.toContain(esc(en.pbNotInPassage("")));
  });
});

describe("not known yet in words at the checkpoint (finding 8)", () => {
  it("says the fact is already not known yet", () => {
    expect(thread).toContain(en.runAlreadyUnknown("Soil certificate"));
    expect(nl.runAlreadyUnknown("Bodemattest")).toBe("Bodemattest staat al als nog niet bekend.");
  });
});

describe("an answer's own notices", () => {
  const render = (t: Pick<AssistantTurn, "thinkingCut" | "narrowedTo">) => renderToStaticMarkup(<AnswerNotes turn={t} />);

  it("says when the question named one document and only that one was read (decision 2)", () => {
    expect(render({ narrowedTo: "R2 (FR).pdf" })).toContain(en.narrowedTo("R2 (FR).pdf"));
    expect(render({})).toBe("");
  });

  it("says when Thorough thought too long and the answer was written without thinking (finding 1)", () => {
    expect(render({ thinkingCut: true })).toContain(en.thinkingCut);
  });
});
