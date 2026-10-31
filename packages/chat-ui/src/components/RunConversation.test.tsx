/**
 * A playbook is a conversation (handovers of 30 and 31 October 2026): the playbook speaks as sūveryn with
 * the route badge, its lines are worded from their kind, events are centred lines; at review the work is in
 * its message (a card per fact under Check or Missing, Confirm held back while Check isn't empty), and the
 * panel lists every fact with its source, nothing edited there.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Case, PlaybookInfo, Run, RunSummary } from "../api";
import en from "../i18n/en";
import { RunPanel, RunThread, factCounts, reviewGroups, runChipText, runStatusWord, statusLabel, stepLabel } from "./RunConversation";

const PLAYBOOK: PlaybookInfo = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.1", name: "Deed intake", covered: true,
  facts: ["price", "epc"], steps: [
    { id: "agreement", kind: "request", needs: [], facts: [] }, { id: "read", kind: "read", needs: ["agreement"], facts: ["price", "epc"] },
    { id: "missing", kind: "ask", needs: ["read"], facts: ["price", "epc"] }, { id: "confirm", kind: "checkpoint", needs: ["missing"], facts: [] },
    { id: "summary", kind: "produce", needs: ["confirm"], facts: [] }],
  text: { en: { title: "Deed intake", summary: "", labels: { price: "Price", epc: "EPC", buyer: "Buyer" }, questions: { agreement: "Upload the agreement." } } },
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
    { id: "price", value: "EUR 415.000,00", citations: [{ n: 1, document_id: "d1", filename: "akte.pdf", page: 2, location: null, text: "De prijs bedraagt EUR 412.500,00." }],
      issues: ["EUR 415.000,00"], found: true, confirmed: null, source: "document" },
    { id: "buyer", value: "Jan De Smet", citations: [], issues: [], found: false, confirmed: null, source: "person", by: "mieke", was: null,
      at: "2026-10-30T10:06:00Z" },
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
const words = { title: "Deed intake", summary: "", labels: { price: "Price", epc: "EPC", buyer: "Buyer" }, facts_title: "Facts for the deed" };
const names = (u: string) => ({ mieke: "Mieke Delarivière", filip: "Filip Tack" }[u] ?? u);
const noop = () => undefined;
/** As React writes it into markup. */
const esc = (s: string) => s.replaceAll("'", "&#x27;");

describe("the thread", () => {
  const html = renderToStaticMarkup(
    <RunThread run={RUN} kase={KASE} playbook={PLAYBOOK} words={words} me="u-mieke" canAnswer nameOf={names} panel={null}
               onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);

  it("starts with who started what, and words the playbook's lines from their kind", () => {
    expect(html).toContain("Mieke Delarivière started Deed intake 1.1");
    expect(html).toContain(en.runAskTurn(1, 2, "EPC"));
    expect(html).toContain(en.runChanged("Price", "EUR 415.000,00"));
    expect(html).toContain("Upload the agreement.");  // the pack's question as written
  });

  it("names the playbook as speaker once per series, with the route badge, and shows events as lines", () => {
    expect(html).toContain('class="ui-badge" data-host="icon" data-tone="system"');
    expect(html).toContain('data-kind="paused"');
    expect(html).toContain("Paused by Filip Tack");
    expect(html).toContain("akte.pdf");  // the documents came with the person's turn
  });

  it("puts the review in the message: a card under Check and one under Missing, never a place word", () => {
    expect(html).toContain(en.pbReviewIntro(2, 3, 2));
    expect(html).toContain(en.pbGroupCheck);
    expect(html).toContain(en.pbGroupMissing);
    expect(html).toContain(en.pbAdjust);
    expect(html).toContain(en.pbFill);
    expect(html).toContain(esc(en.pbNotInPassage("EUR 415.000,00")));
    expect(html).toContain("De prijs bedraagt EUR 412.500,00.");  // the passage, quoted
    expect(html).toContain(en.pbAllFacts(3));
    expect(html).not.toMatch(/on the right/);
  });

  it("holds Confirm back while Check isn't empty, and says why", () => {
    expect(html).toContain(en.confirmAll);
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain(en.pbConfirmBlockedOne("Price"));
    const checked = { ...RUN, facts: RUN.facts.map((f) => (f.id === "price" ? { ...f, source: "person" as const, by: "mieke", was: f.value } : f)) };
    const ok = renderToStaticMarkup(
      <RunThread run={checked} kase={KASE} playbook={PLAYBOOK} words={words} me="u-mieke" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(ok).not.toContain('aria-disabled="true"');
    expect(reviewGroups(checked).check).toHaveLength(0);
  });

  it("carries only the playbook's title on the chip, and no hint line under the composer", () => {
    expect(html).toContain('aria-label="Deed intake"');
    expect(html).not.toContain("1.1 · running");
    expect(html).toContain(en.runAnswerPlaceholder);
    expect(html).not.toContain("composer-hint");
  });

  it("is read only for a reader", () => {
    const reader = renderToStaticMarkup(
      <RunThread run={RUN} kase={KASE} playbook={PLAYBOOK} words={words} canAnswer={false} nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(reader).toContain(en.runReadOnly);
    expect(reader).not.toContain(en.runAnswerPlaceholder);
    expect(reader).not.toContain(en.pbAdjust);
  });
});

describe("the facts list", () => {
  it("lists every fact with its source or where it came from, and edits nothing", () => {
    const html = renderToStaticMarkup(<RunPanel run={RUN} words={words} view={{ kind: "list" }} onView={noop} onClose={noop} />);
    expect(html).toContain(en.pbListTitle("Facts for the deed"));
    expect(html).toContain("All facts for the deed");
    expect(html).toContain("akte.pdf, p.2");                   // the SourceRef
    expect(html).toContain(en.sourceLabel(1, "akte.pdf", 2));  // its name
    expect(html).toContain(en.pbFromChat(""));                 // the buyer came from the conversation
    expect(html).toContain(en.answerPlaceholder);              // a fact without a value
    expect(html).toContain(esc(en.factCheckThis));
    expect(html).not.toContain(en.confirmAll);
    expect(html).not.toContain("<textarea");
  });

  it("opens a fact's source with a way back to the list", () => {
    const html = renderToStaticMarkup(<RunPanel run={RUN} words={words} view={{ kind: "source", fact: "price", fromList: true }} onView={noop} onClose={noop} />);
    expect(html).toContain("facts-back");
    expect(html).toContain("De prijs bedraagt");
  });
});

describe("the chip on a case and the breadcrumb", () => {
  it("say where the run is", () => {
    expect(stepLabel({ ...SUMMARY, step: "agreement" }, PLAYBOOK, en)).toBe(en.stepRequest);
    expect(stepLabel({ ...SUMMARY, status: "reading", step: "read" }, PLAYBOOK, en)).toBe(en.stepReading);
    expect(runChipText({ ...SUMMARY, status: "paused" }, PLAYBOOK, "Deed intake", en)).toBe("Deed intake · Paused");
    expect(runStatusWord(SUMMARY, PLAYBOOK, en)).toBe(en.pbStatusReview);
    expect(runStatusWord({ ...SUMMARY, status: "paused" }, PLAYBOOK, en)).toBe(en.pbStatusPaused);
    expect(statusLabel("cancelled", en)).toBe(en.runCancelled);
    expect(factCounts(RUN)).toEqual([2, 3]);
  });
});
