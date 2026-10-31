/**
 * A playbook is a conversation (handover of 30 October 2026, boards 52 to 54): the playbook speaks as
 * sūveryn with the route badge, its lines are worded from their kind in the interface language, events
 * are centred lines, the composer's chip says the run's state in words, and the facts panel says where
 * each value came from.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Case, PlaybookInfo, Run, RunSummary } from "../api";
import en from "../i18n/en";
import { FactsPanel, RunThread, factCounts, runChipText, statusLabel, stepLabel } from "./RunConversation";

const PLAYBOOK: PlaybookInfo = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.1", name: "Deed intake", covered: true,
  facts: ["price", "epc"], steps: [
    { id: "agreement", kind: "request", needs: [], facts: [] }, { id: "read", kind: "read", needs: ["agreement"], facts: ["price", "epc"] },
    { id: "missing", kind: "ask", needs: ["read"], facts: ["price", "epc"] }, { id: "confirm", kind: "checkpoint", needs: ["missing"], facts: [] },
    { id: "summary", kind: "produce", needs: ["confirm"], facts: [] }],
  text: { en: { title: "Deed intake", summary: "", labels: { price: "Price", epc: "EPC" }, questions: { agreement: "Upload the agreement." } } },
};
const SUMMARY: RunSummary = {
  id: "r1", case_id: "c1", playbook_id: PLAYBOOK.id, playbook_version: "1.1", status: "waiting", documents: ["d1"], started_by: "mieke",
  started_at: "2026-10-30T09:58:00Z", finished_at: null, confirmed_by: null, confirmed_at: null, model: null, error: null,
  result_document_id: null, out_of_date: false, step: "confirm", language: "en", paused_by: null, paused_at: null, ended_by: null,
  ended_reason: null, starter: "u-mieke", conversation_id: "conv-1",
};
const RUN: Run = {
  ...SUMMARY, instruction_like_sources: [], steps: {},
  facts: [
    { id: "price", value: "EUR 415.000,00", citations: [{ n: 1, document_id: "d1", filename: "akte.pdf", page: 2, location: null, text: "EUR 412.500,00" }],
      issues: [], found: true, confirmed: null, source: "person", by: "mieke", was: "EUR 412.500,00" },
    { id: "epc", value: "", citations: [], issues: [], found: false, confirmed: null, source: "none" },
  ],
  turns: [
    { seq: 1, role: "playbook", step_id: "agreement", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "Upload the agreement.", meta: {} },
    { seq: 2, role: "user", step_id: "agreement", by: "mieke", at: SUMMARY.started_at, text: "Here it is.",
      meta: { attachments: [{ documentId: "d1", filename: "akte.pdf" }] } },
    { seq: 3, role: "playbook", step_id: "missing", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "1 of 2 facts found.",
      meta: { kind: "ask", facts: ["epc"], found: 1, total: 2 } },
    { seq: 4, role: "playbook", step_id: "missing", by: "filip", at: SUMMARY.started_at, text: "Paused by filip.", meta: { kind: "paused" } },
    { seq: 5, role: "playbook", step_id: "confirm", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "1 of 2 facts found.",
      meta: { kind: "checkpoint", found: 1, total: 2, issues: 1 } },
    { seq: 6, role: "playbook", step_id: "confirm", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "Changed: Price is now EUR 415.000,00.",
      meta: { kind: "changed", fact: "price", value: "EUR 415.000,00" } },
  ],
};
const KASE = { id: "c1", reference: "2026/0611", name: "Verkoop Peeters", type: "sale", state: "open", manager: "u-mieke" } as unknown as Case;
const words = { title: "Deed intake", summary: "", labels: { price: "Price", epc: "EPC" }, facts_title: "Facts for the deed" };
const names = (u: string) => ({ mieke: "Mieke Delarivière", filip: "Filip Tack" }[u] ?? u);
const noop = () => undefined;
/** As React writes it into markup. */
const esc = (s: string) => s.replaceAll("'", "&#x27;");

describe("the thread", () => {
  const html = renderToStaticMarkup(
    <RunThread run={RUN} kase={KASE} playbook={PLAYBOOK} words={words} me="u-mieke" canAnswer nameOf={names} factsOpen={false}
               onChanged={noop} onOpenFacts={noop} onDocumentsChanged={noop} />);

  it("starts with who started what, and words the playbook's lines from their kind", () => {
    expect(html).toContain("Mieke Delarivière started Deed intake 1.1");
    expect(html).toContain(en.runAskTurn(1, 2, "EPC"));
    expect(html).toContain(esc(en.runCheckpointTurn(1, 2) + " " + en.runCheckpointIssues(1)));
    expect(html).toContain(en.runChanged("Price", "EUR 415.000,00"));
    expect(html).toContain("Upload the agreement.");  // the pack's question as written
  });

  it("names the playbook as speaker once per series, with the route badge, and shows events as lines", () => {
    expect(html.match(/class="run-speaker"/g)).toHaveLength(3);  // the first turn, after the person, after the pause
    expect(html).toContain('class="ui-badge" data-host="icon" data-tone="system"');
    expect(html).toContain('data-kind="paused"');
    expect(html).toContain("Paused by Filip Tack");
    expect(html).toContain("akte.pdf");  // the documents came with the person's turn
  });

  it("offers the facts chip at the checkpoint, and the run's chip and line in the composer", () => {
    expect(html).toContain("Facts for the deed · 1 of 2");
    expect(html).toContain(en.runChipRunning("Deed intake", "1.1"));
    expect(html).toContain(en.runWaitsOnYou("Deed intake", en.runWaitsCheck));
    expect(html).toContain(en.runAnswerPlaceholder);
  });

  it("is read only for a reader", () => {
    const reader = renderToStaticMarkup(
      <RunThread run={RUN} kase={KASE} playbook={PLAYBOOK} words={words} canAnswer={false} nameOf={names} factsOpen={false}
                 onChanged={noop} onOpenFacts={noop} onDocumentsChanged={noop} />);
    expect(reader).toContain(en.runReadOnly);
    expect(reader).not.toContain(en.runAnswerPlaceholder);
  });
});

describe("the facts panel", () => {
  it("says where each value came from, and offers to confirm at the checkpoint", () => {
    const html = renderToStaticMarkup(
      <FactsPanel run={RUN} kase={KASE} words={words} canConfirm nameOf={names} onChanged={noop} onClose={noop} />);
    expect(html).toContain("Facts for the deed");
    expect(html).toContain(en.factsCount(1, 2));
    expect(html).toContain(en.factChangedIn("EUR 412.500,00"));
    expect(html).toContain(en.answerPlaceholder);  // a fact without a value, said once
    expect(html).toContain(en.confirmAll);
    expect(html).toContain(en.changeValue("Price", "EUR 415.000,00"));
  });
});

describe("the chip on a case", () => {
  it("says where the run is", () => {
    expect(stepLabel({ ...SUMMARY, step: "agreement" }, PLAYBOOK, en)).toBe(en.stepRequest);
    expect(stepLabel({ ...SUMMARY, status: "reading", step: "read" }, PLAYBOOK, en)).toBe(en.stepReading);
    expect(runChipText({ ...SUMMARY, status: "paused" }, PLAYBOOK, "Deed intake", en)).toBe("Deed intake · Paused");
    expect(statusLabel("cancelled", en)).toBe(en.runCancelled);
    expect(factCounts(RUN)).toEqual([1, 2]);
  });
});
