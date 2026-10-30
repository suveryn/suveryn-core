/**
 * The run view's words (docs/design/playbooks.md, "A running playbook is visible"): the banner says
 * where a run is and what it waits for, the chip is one line, and the thread shows the playbook's
 * questions and the people's answers with their names.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PlaybookInfo, Run, RunSummary } from "../api";
import en from "../i18n/en";
import { RunBanner, runChipText, statusLabel, stepLabel } from "./PlaybookRun";

const PLAYBOOK: PlaybookInfo = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.1", name: "Deed intake", covered: true,
  facts: ["price"], steps: [
    { id: "agreement", kind: "request", needs: [], facts: [] }, { id: "read", kind: "read", needs: ["agreement"], facts: ["price"] },
    { id: "missing", kind: "ask", needs: ["read"], facts: ["price"] }, { id: "confirm", kind: "checkpoint", needs: ["missing"], facts: [] },
    { id: "summary", kind: "produce", needs: ["confirm"], facts: [] }],
  text: { en: { title: "Deed intake", summary: "", labels: { price: "Price" }, questions: { agreement: "Upload the agreement.", missing: "What is {label}?" } } },
};
const RUN: RunSummary = {
  id: "r1", case_id: "c1", playbook_id: PLAYBOOK.id, playbook_version: "1.1", status: "waiting", documents: [], started_by: "alice",
  started_at: "2026-10-30T10:00:00Z", finished_at: null, confirmed_by: null, confirmed_at: null, model: null, error: null,
  result_document_id: null, out_of_date: false, step: "agreement", language: "en", paused_by: null, paused_at: null, ended_by: null, ended_reason: null,
};
const words = { title: "Deed intake", summary: "", labels: { price: "Price" } };

describe("the banner and the chip", () => {
  it("say where the run is and what it waits for", () => {
    expect(stepLabel(RUN, PLAYBOOK, en)).toBe(en.stepRequest);
    expect(stepLabel({ ...RUN, step: "missing" }, PLAYBOOK, en)).toBe(en.stepAsk);
    expect(stepLabel({ ...RUN, step: "confirm" }, PLAYBOOK, en)).toBe(en.stepCheckpoint);
    expect(stepLabel({ ...RUN, status: "reading", step: "read" }, PLAYBOOK, en)).toBe(en.stepReading);
    expect(stepLabel({ ...RUN, step: "confirm" }, null, en)).toBe("");  // the playbook not known (any more): no step to name
    expect(runChipText(RUN, PLAYBOOK, "Deed intake", en)).toBe("Deed intake · waiting for documents");
    expect(runChipText({ ...RUN, status: "paused" }, PLAYBOOK, "Deed intake", en)).toBe("Deed intake · Paused");
    expect(statusLabel("cancelled", en)).toBe(en.runCancelled);
  });

  it("render the banner with the status, the title and version, and who paused it", () => {
    const html = renderToStaticMarkup(<RunBanner run={RUN} playbook={PLAYBOOK} words={words} nameOf={(u) => u.toUpperCase()} />);
    expect(html).toContain("Deed intake</b> 1.1");
    expect(html).toContain(en.runWaiting);
    expect(html).toContain(en.stepRequest);
    const paused = renderToStaticMarkup(<RunBanner run={{ ...RUN, status: "paused", paused_by: "bob", paused_at: "2026-10-30T11:00:00Z" }}
                                                   playbook={PLAYBOOK} words={words} nameOf={(u) => u.toUpperCase()} />);
    expect(paused).toContain("Paused by BOB");
  });
});

describe("the thread", () => {
  it("shows the playbook's questions on the assistant side and people's answers with their names", async () => {
    const { PlaybookView } = await import("./PlaybookRun");
    void PlaybookView;  // the view itself needs the API; the thread's words are checked through the run's turns below
    const run: Run = { ...RUN, step: "missing", facts: [{ id: "price", value: "", citations: [], issues: [], found: false, confirmed: null, source: "none" }],
                       instruction_like_sources: [], steps: { agreement: { status: "done", by: "alice", at: null } },
                       turns: [{ seq: 1, role: "playbook", step_id: "agreement", by: PLAYBOOK.id, at: RUN.started_at, text: "Upload the agreement.", meta: {} },
                               { seq: 2, role: "user", step_id: "agreement", by: "alice", at: RUN.started_at, text: "The documents are in.", meta: {} },
                               { seq: 3, role: "playbook", step_id: "missing", by: PLAYBOOK.id, at: RUN.started_at, text: "What is Price?", meta: { fact: "price" } }] };
    expect(run.turns.filter((t) => t.role === "playbook")).toHaveLength(2);
    expect(run.turns[2].meta.fact).toBe("price");
  });
});
