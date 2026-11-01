/**
 * VM regression e0f2e26: the findings fixed in the chat UI, each where a test can reach it.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Case, CaseEvent, PlaybookInfo, Run } from "../api";
import en from "../i18n/en";
import nl from "../i18n/nl";
import { eventLabel } from "./CaseMembers";
import { failureWords } from "./Messages";
import { RunThread } from "./RunConversation";

const PLAYBOOK = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.1", name: "Deed intake", covered: true,
  facts: ["soil"], steps: [{ id: "agreement", kind: "request", needs: [], facts: [] }, { id: "missing", kind: "ask", needs: ["agreement"], facts: ["soil"] }],
  text: { en: { title: "Deed intake", summary: "", labels: { soil: "Soil certificate" } } },
} as PlaybookInfo;
const BASE = {
  id: "r1", case_id: "c1", playbook_id: PLAYBOOK.id, playbook_version: "1.1", status: "waiting", documents: [], started_by: "alice",
  started_at: "2026-10-31T23:26:00Z", finished_at: null, confirmed_by: null, confirmed_at: null, model: null, error: null,
  result_document_id: null, out_of_date: false, language: "en", paused_by: null, paused_at: null, ended_by: null, ended_reason: null,
  starter: "u-alice", conversation_id: "conv", instruction_like_sources: [], steps: {}, facts: [],
} as unknown as Run;
const KASE = { id: "c1", reference: "TEST-B", name: "Beukenstraat", type: "sale", state: "open", manager: "u-bob" } as unknown as Case;
const words = { title: "Deed intake", summary: "", labels: { soil: "Soil certificate" } };
const at = BASE.started_at;
const thread = (run: Run) => renderToStaticMarkup(
  <RunThread run={run} kase={KASE} playbook={PLAYBOOK} words={words} me="u-alice" canAnswer nameOf={(u) => u} panel={null}
             onChanged={() => undefined} onPanel={() => undefined} onDocumentsChanged={() => undefined} />);

describe("the run's quick replies", () => {
  it("keep 'Not known yet' on the question still standing, also after an answer that couldn't be placed (finding 6)", () => {
    const run = { ...BASE, step: "missing", turns: [
      { seq: 1, role: "playbook", step_id: "missing", by: PLAYBOOK.id, at, text: "", meta: { kind: "ask", facts: ["soil"], found: 12, total: 13 } },
      { seq: 2, role: "user", step_id: "missing", by: "bob", at, text: "Good morning.", meta: {} },
      { seq: 3, role: "playbook", step_id: "missing", by: PLAYBOOK.id, at, text: "", meta: { kind: "unplaced", facts: ["soil"] } },
    ] } as Run;
    expect(thread(run)).toContain(`>${en.answerPlaceholder}</button>`);
  });

  it("offer the documents already in the case at the request, which always asks (question 1)", () => {
    const run = { ...BASE, step: "agreement", turns: [
      { seq: 1, role: "playbook", step_id: "agreement", by: PLAYBOOK.id, at, text: "Upload the signed sale agreement.", meta: {} },
    ] } as Run;
    expect(thread(run)).toContain(en.runUseCaseDocuments);
  });
});

describe("words that follow the reader", () => {
  it("word a failed answer from its code in the language of the moment (finding 10)", () => {
    expect(failureWords({ failure: "model", error: "le modèle est injoignable pour le moment" }, nl)).toBe(nl.streamErrorModel);
    expect(failureWords({ error: "the server's own words" }, nl)).toBe("the server's own words");
  });

  it("name who received a case and which playbook started, in the access log (finding 12)", () => {
    const e = (action: string, detail: Record<string, string>) => ({ id: 1, action, detail, user: "u-alice", at } as unknown as CaseEvent);
    expect(eventLabel(e("handed_over", { manager: "u-bob" }), nl, (u) => (u === "u-bob" ? "Test Bob" : ""))).toBe("droeg het dossier over aan Test Bob");
    expect(eventLabel(e("playbook_started", { playbook: PLAYBOOK.id }), nl, () => "", () => "Akte-intake")).toBe("startte Akte-intake");
    expect(eventLabel(e("handed_over", {}), nl)).toBe(nl.eventHandedOver);
  });

  it("end a refused setting with a full stop (finding 13)", () => {
    expect(nl.settingsFailed(nl.adminRightsRefused)).toMatch(/ondersteuning\.$/);
    expect(en.settingsFailed("done.")).toBe("The settings couldn't be saved: done.");
  });
});
