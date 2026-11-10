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
import { RunPanel, RunSourcePanel, RunThread, computedHow, factCounts, reviewGroups, runChipText, runStatusWord, statusLabel, stepLabel, waitsFor, lastRunLine } from "./RunConversation";

const PLAYBOOK: PlaybookInfo = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.1", name: "Deed intake", covered: true,
  facts: ["price", "epc"], steps: [
    { id: "agreement", kind: "request", needs: [], facts: [] }, { id: "read", kind: "read", needs: ["agreement"], facts: ["price", "epc"] },
    { id: "missing", kind: "ask", needs: ["read"], facts: ["price", "epc"] }, { id: "confirm", kind: "checkpoint", needs: ["missing"], facts: [] },
    { id: "summary", kind: "produce", needs: ["confirm"], facts: [] }],
  text: { en: { title: "Deed intake", summary: "", labels: { price: "Price", epc: "EPC", buyer: "Buyer" }, questions: { agreement: "Upload the agreement." } } },
};
const SUMMARY: RunSummary = {
  id: "r1", case_id: "c1", playbook_id: PLAYBOOK.id, playbook_version: "1.1", status: "waiting", documents: ["d1"], started_by: "ines",
  started_at: "2026-10-30T09:58:00Z", finished_at: null, confirmed_by: null, confirmed_at: null, model: null, error: null,
  result_document_id: null, out_of_date: false, step: "confirm", language: "en", paused_by: null, paused_at: null, ended_by: null,
  ended_reason: null, starter: "u-ines", conversation_id: "conv-1",
};
const RUN: Run = {
  ...SUMMARY, playbook: PLAYBOOK, instruction_like_sources: [], steps: {},
  facts: [
    { id: "price", value: "EUR 415.000,00", citations: [{ n: 1, document_id: "d1", filename: "akte.pdf", page: 2, location: null, text: "De prijs bedraagt EUR 412.500,00." }],
      issues: ["EUR 415.000,00"], found: true, confirmed: null, source: "document" },
    { id: "buyer", value: "Jan De Smet", citations: [], issues: [], found: false, confirmed: null, source: "person", by: "ines", was: null,
      at: "2026-10-30T10:06:00Z" },
    { id: "epc", value: "", citations: [], issues: [], found: false, confirmed: null, source: "none" },
  ],
  turns: [
    { seq: 1, role: "playbook", step_id: "agreement", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "Upload the agreement.", meta: {} },
    { seq: 2, role: "user", step_id: "agreement", by: "ines", at: SUMMARY.started_at, text: "Here it is.",
      meta: { attachments: [{ documentId: "d1", filename: "akte.pdf" }] } },
    { seq: 3, role: "playbook", step_id: "missing", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "1 of 2 facts found.",
      meta: { kind: "ask", facts: ["epc"], found: 1, total: 2 } },
    { seq: 4, role: "playbook", step_id: "missing", by: "lotte", at: SUMMARY.started_at, text: "Paused by lotte.", meta: { kind: "paused" } },
    { seq: 5, role: "playbook", step_id: "confirm", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "1 of 2 facts found.",
      meta: { kind: "checkpoint", found: 1, total: 2, issues: 1 } },
    { seq: 6, role: "playbook", step_id: "confirm", by: PLAYBOOK.id, at: SUMMARY.started_at, text: "Changed: Price is now EUR 415.000,00.",
      meta: { kind: "changed", fact: "price", value: "EUR 415.000,00" } },
  ],
};
const KASE = { id: "c1", reference: "2026/0611", name: "Verkoop Peeters", type: "sale", state: "open", manager: "u-ines" } as unknown as Case;
const words = { title: "Deed intake", summary: "", labels: { price: "Price", epc: "EPC", buyer: "Buyer" }, facts_title: "Facts for the deed" };
const names = (u: string) => ({ ines: "Ines Wouters", lotte: "Lotte Verbeke" }[u] ?? u);
const noop = () => undefined;
/** As React writes it into markup. */
const esc = (s: string) => s.replaceAll("'", "&#x27;");

describe("the thread", () => {
  const html = renderToStaticMarkup(
    <RunThread run={RUN} kase={KASE} playbook={PLAYBOOK} words={words} me="u-ines" canAnswer nameOf={names} panel={null}
               onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);

  it("starts with who started what, and words the playbook's lines from their kind", () => {
    expect(html).toContain("Ines Wouters started Deed intake 1.1");
    expect(html).toContain(en.runAskTurn(1, 2, "EPC"));
    expect(html).toContain(en.runChanged("Price", "EUR 415.000,00"));
    expect(html).toContain("Upload the agreement.");  // the pack's question as written
  });

  it("names the playbook as speaker once per series, with the route badge, and shows events as lines", () => {
    expect(html).toContain('class="ui-badge" data-host="icon" data-tone="system"');
    expect(html).toContain('data-kind="paused"');
    expect(html).toContain("Paused by Lotte Verbeke");
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
    const checked = { ...RUN, facts: RUN.facts.map((f) => (f.id === "price" ? { ...f, source: "person" as const, by: "ines", was: f.value } : f)) };
    const ok = renderToStaticMarkup(
      <RunThread run={checked} kase={KASE} playbook={PLAYBOOK} words={words} me="u-ines" canAnswer nameOf={names} panel={null}
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

  it("opens a fact's source in the conversation's own source panel (board P02)", () => {
    const html = renderToStaticMarkup(<RunSourcePanel run={RUN} fact="price" fromList caseRef="2026/0611" present={new Set(["d1"])} caseId="c1"
                                                      onView={noop} onClose={noop} />);
    expect(html).toContain("De prijs bedraagt");
    expect(html).toContain(en.sourceOf(1, 1));                                   // "1 of 1", with its arrows
    expect(html).toContain(en.openAtPage(2));                                    // the document at its page
    expect(html).toContain(en.copyPassage);
    expect(html).toContain("EUR 415.000,00");                                    // what the check didn't find, as under an answer
    expect(html).not.toContain(en.verdictSource);
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

describe("lists (format 3)", () => {
  const FORMATION: PlaybookInfo = {
    ...PLAYBOOK, id: "playbook/be-notary/company-formation", slug: "company-formation", facts: ["company_name", "founders", "conditions"],
    lists: { founders: ["name", "shares"], conditions: [] },
    text: { en: { title: "Company formation", summary: "", labels: { company_name: "Company name", founders: "Founder(s)", "founders.name": "Name",
                                                                       "founders.shares": "Shares", conditions: "Conditions" } } },
  };
  const fwords = { ...FORMATION.text!.en, facts_title: "" };
  const run: Run = {
    ...RUN, playbook_id: FORMATION.id, turns: [RUN.turns[4]],
    facts: [
      { id: "company_name", value: "Suveryn Labs BV", citations: [], issues: [], found: true, confirmed: null, source: "document" },
      { id: "founders", value: "", citations: [], issues: [], found: false, confirmed: null, source: "none" },   // the read's "none", later superseded by entries
      { id: "founders[1].name", value: "Filip Tack", citations: [], issues: [], found: true, confirmed: null, source: "document" },
      { id: "founders[1].shares", value: "650", citations: [{ n: 1, document_id: "d1", filename: "ontwerp.pdf", page: 1, location: null, text: "600 aandelen" }],
        issues: ["650"], found: true, confirmed: null, source: "document" },
      { id: "conditions", value: "", citations: [], issues: [], found: false, confirmed: null, source: "none" },
    ],
  };

  it("labels an entry's values by the list, the entry's number and the field, and hides a list behind its entries", () => {
    const { check, missing } = reviewGroups(run);
    expect(check.map((f) => f.id)).toEqual(["founders[1].shares"]);
    expect(missing.map((f) => f.id)).toEqual(["conditions"]);   // not "founders": it has an entry
    expect(factCounts(run)).toEqual([2, 3]);   // a list is one fact, found with an entry (board P01): not its fields
    const html = renderToStaticMarkup(
      <RunThread run={run} kase={KASE} playbook={FORMATION} words={fwords} me="u-ines" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html).toContain("Founder(s) 1 · Shares");
    expect(html).toContain("Conditions</span><em class=\"fact-unknown\">None in the documents</em>");  // a list with no entries: an entry to add, not a value to fill in
    expect(html.match(/fact-card-entry/g)?.length).toBe(1);   // a list with entries isn't in the message: one more is added in the panel
    expect(html).not.toContain(">Fill in<");
  });

  it("shows the checks with their result, and never holds Confirm back for one", () => {
    const checked: Run = {
      ...run, facts: run.facts.filter((f) => f.id !== "founders[1].shares"),
      checks: { shares_add_up: { status: "fails", rule: "sum(founders.shares) == shares", left: "1050", right: "1000", missing: [] },
                a_founder: { status: "holds", rule: "count(founders) >= 1", left: "1", right: "1", missing: [] },
                plan_before_deed: { status: "open", rule: "plan_date <= deed_date", left: "", right: "", missing: ["founders[2].name"] } },
    };
    const playbook: PlaybookInfo = { ...FORMATION, steps: [...FORMATION.steps!, { id: "shares_add_up", kind: "check", needs: [], facts: [] },
                                              { id: "a_founder", kind: "check", needs: [], facts: [] }, { id: "plan_before_deed", kind: "check", needs: [], facts: [] }],
                       text: { en: { ...FORMATION.text!.en, checks: { shares_add_up: "The founders' shares add up to the shares issued" } } } };
    const html = renderToStaticMarkup(
      <RunThread run={checked} kase={KASE} playbook={playbook} words={{ ...fwords, checks: playbook.text!.en.checks }} me="u-ines" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html).toContain("The founders&#x27; shares add up to the shares issued");
    expect(html).toContain("Does not hold: 1050 against 1000.");
    // only a check that fails is in the message (board P01); the others are in the panel
    expect(html).not.toContain("count(founders) &gt;= 1");
    expect(html).not.toContain("Not checked yet");
    expect(html).not.toContain("data-blocked");   // a failed check is a point for the notary, never a block
    const panel = renderToStaticMarkup(<RunPanel run={checked} words={{ ...fwords, checks: playbook.text!.en.checks }} view={{ kind: "list" }}
                                                 steps={playbook.steps} lists={FORMATION.lists} onView={noop} onClose={noop} />);
    expect(panel).toContain("count(founders) &gt;= 1");   // no sentence in the words: the rule as written
    expect(panel).toContain(en.pbCheckHolds);
    expect(panel).toContain("Not checked yet: Founder(s) 2 · Name is needed.");
  });

  it("offers a choice's options as buttons when the playbook asks, and says why a step was skipped", () => {
    const playbook: PlaybookInfo = { ...FORMATION, facts: [...FORMATION.facts, "contribution_kind"], choices: { contribution_kind: ["cash", "in_kind"] },
      text: { en: { ...FORMATION.text!.en, labels: { ...FORMATION.text!.en.labels, contribution_kind: "Contribution", "contribution_kind.cash": "In cash", "contribution_kind.in_kind": "In kind" },
                    steps: { bank: "Bank certificate" } } } };
    const words = { ...playbook.text!.en, facts_title: "" };
    const asking: Run = { ...run, step: "kind_known", turns: [
      { seq: 1, role: "playbook", step_id: "kind_known", by: FORMATION.id, at: SUMMARY.started_at, text: "0 of 1 facts found.", meta: { kind: "ask", facts: ["contribution_kind"], found: 0, total: 1 } },
      { seq: 2, role: "playbook", step_id: "bank", by: FORMATION.id, at: SUMMARY.started_at, text: "Bank certificate: not needed.", meta: { kind: "skipped_step", step: "bank", fact: "contribution_kind", value: "in_kind", when: "contribution_kind != in_kind" } },
      { seq: 3, role: "playbook", step_id: "reports", by: FORMATION.id, at: SUMMARY.started_at, text: "x", meta: { kind: "skipped_step", step: "reports", fact: "contribution_kind", value: "", when: "contribution_kind != cash" } },
    ] };
    const html = renderToStaticMarkup(
      <RunThread run={asking} kase={KASE} playbook={playbook} words={words} me="u-ines" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html).toContain("aria-label=\"Contribution\"");
    expect(html).toContain(">In cash</button>");
    expect(html).toContain(">In kind</button>");
    expect(html).toContain("Bank certificate: not needed, Contribution is In kind.");
    expect(html).toContain("reports: skipped, Contribution is not known.");
  });

  it("offers 'There is none' only at a request the playbook can do without", () => {
    const steps = [{ id: "agreement", kind: "request" as const, needs: [], facts: [] },
                   { id: "title_deed", kind: "request" as const, needs: ["agreement"], facts: [], allow_none: true }];
    const playbook: PlaybookInfo = { ...PLAYBOOK, steps };
    const at = (step: string): Run => ({ ...RUN, step, steps: {}, facts: [], turns: [
      { seq: 1, role: "playbook", step_id: step, by: PLAYBOOK.id, at: SUMMARY.started_at, text: "Upload it.", meta: {} }] });
    const html = (run: Run) => renderToStaticMarkup(
      <RunThread run={run} kase={KASE} playbook={playbook} words={words} me="u-ines" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html(at("agreement"))).toContain(en.runUseCaseDocuments);
    expect(html(at("agreement"))).not.toContain(en.runNoDocument);
    expect(html(at("title_deed"))).toContain(`>${en.runNoDocument}</button>`);
  });

  it("says when documents were longer than one reading takes", () => {
    const reading: Run = { ...run, step: "missing", turns: [
      { seq: 1, role: "playbook", step_id: "founders_read", by: FORMATION.id, at: SUMMARY.started_at, text: "x",
        meta: { kind: "read_in_part", step: "founders_read", documents: ["financial-plan.pdf", "statutes.pdf"] } },
    ] };
    const html = renderToStaticMarkup(
      <RunThread run={reading} kase={KASE} playbook={FORMATION} words={fwords} me="u-ines" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html).toContain("financial-plan.pdf, statutes.pdf: longer than sūveryn reads at once.");
    expect(html).toContain("a fact not found may still be in them.");
  });

  it("leaves confirming to the case manager when the checkpoint says so; others still see the cards", () => {
    const playbook: PlaybookInfo = { ...FORMATION, steps: FORMATION.steps!.map((s) => s.id === "confirm" ? { ...s, by: "manager" as const } : s) };
    const asClerk = renderToStaticMarkup(
      <RunThread run={run} kase={KASE} playbook={playbook} words={fwords} me="u-bob" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(asClerk).toContain("The case manager confirms the facts.");
    expect(asClerk).not.toContain("Confirm the facts");
    expect(asClerk).toContain(">Adjust<");   // a clerk prepares and corrects
    const asManager = renderToStaticMarkup(
      <RunThread run={run} kase={KASE} playbook={playbook} words={fwords} me="u-ines" canAnswer nameOf={names} panel={null}
                 onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(asManager).toContain("Confirm the facts");
  });

  it("shows a list as one block in the panel, its entries' other fields dimmed, Add at its end (board P03)", () => {
    const two: Run = { ...run, facts: [...run.facts, { id: "founders[2].name", value: "Ines Wouters", citations: [], issues: [], found: true, confirmed: null, source: "document" }] };
    const html = renderToStaticMarkup(<RunPanel run={two} words={fwords} view={{ kind: "list" }} lists={FORMATION.lists} kase={KASE} canAnswer
                                                onView={noop} onClose={noop} />);
    expect(html).toContain("data-fact=\"founders\"");
    expect(html).toContain("Filip Tack and Ines Wouters");            // the entries on one line
    expect(html).toContain("fact-entry-more\">Filip Tack · 650");      // an entry's other field, under it
    expect(html).not.toContain("Founder(s) 1 · Name");                 // not a block per entry and field
    expect(html).toContain("Founder(s) 1 · Shares: " + esc(en.factCheckThis));
    expect(html.match(/>Add</g)?.length).toBe(2);                      // one more founder, a first condition
    expect(html).toContain("data-fact=\"conditions\"");
    expect(html).toContain(en.pbNoEntries);
    const reader = renderToStaticMarkup(<RunPanel run={two} words={fwords} view={{ kind: "list" }} lists={FORMATION.lists} onView={noop} onClose={noop} />);
    expect(reader).not.toContain(">Add<");
  });
});


describe("a date sūveryn worked out (board P01)", () => {
  const computed = { written: "binnen vier maanden na de ondertekening", from: "agreement_date", base: "2026-10-12", date: "2027-02-12",
                     amount: 4, unit: "month" as const, direction: "after" as const };
  const run: Run = { ...RUN, facts: [{ id: "deed_deadline", value: "12 februari 2027", issues: [], found: true, confirmed: null, source: "document",
    needs: "computed", computed, citations: [{ n: 1, document_id: "d1", filename: "akte.pdf", page: 4, location: null,
      text: "De akte wordt verleden uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst, en in elk geval na de vervulling van de voorwaarde." }] }] };
  const dwords = { ...words, labels: { deed_deadline: "Deed by" } };

  it("is under Check with how it was worked out, the term in ink and its context dimmed", () => {
    expect(reviewGroups(run).check.map((f) => f.id)).toEqual(["deed_deadline"]);
    expect(computedHow(computed, en)).toBe("Worked out: 12 October 2026 plus four months.");
    // working days name the pack's calendar; a share says of what (decision of 10 November 2026)
    expect(computedHow({ ...computed, amount: 10, unit: "workday", calendar: { en: "Monday to Friday, Belgian public holidays" } }, en))
      .toBe("Worked out: 12 October 2026 plus ten working days (Monday to Friday, Belgian public holidays).");
    expect(computedHow({ kind: "share", written: "tien procent van de koopprijs", from: "price", percent: "10", of: "385000.00", amount: "38500.00" }, en))
      .toBe("Worked out: 10% of 385,000.");
    const html = renderToStaticMarkup(<RunThread run={run} kase={KASE} playbook={PLAYBOOK} words={dwords} me="u-ines" canAnswer nameOf={names}
                                                 panel={null} onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html).toContain("12 februari 2027");
    expect(html).toContain("Worked out: 12 October 2026 plus four months.");
    expect(html).toContain('<span class="quote-cited">binnen vier maanden na de ondertekening</span><span class="quote-context"> van deze overeenkomst, en …</span>');
    expect(html).toContain("data-blocked");   // to check before the facts are confirmed
  });

  it("says in the source panel that the date itself isn't in the passage", () => {
    const html = renderToStaticMarkup(<RunSourcePanel run={run} fact="deed_deadline" fromList={false} caseRef={null} onView={noop} onClose={noop} />);
    expect(html).toContain(esc(en.pbDateNotInPassage));
    expect(html).toContain("Worked out: 12 October 2026 plus four months.");
  });
});

describe("who a run waits for (board P04, 7)", () => {
  it("names the person who started it, you, or a member at the checkpoint", () => {
    const asking = { ...SUMMARY, step: "missing", step_kind: "ask" as const };
    expect(waitsFor(asking, PLAYBOOK, en, "u-bob", "Ines Wouters")).toBe("waiting for Ines");
    expect(waitsFor(asking, PLAYBOOK, en, "u-ines", "Ines Wouters")).toBe(en.waitsForYou);
    expect(waitsFor(SUMMARY, PLAYBOOK, en, "u-ines", "Ines Wouters")).toBe(en.waitsForMember);   // at the checkpoint
    expect(runChipText({ ...asking, title: { en: "Deed intake" } }, PLAYBOOK, "", en, "en", { me: "u-bob", starterName: "Ines Wouters" }))
      .toBe("Deed intake · waiting for Ines");
  });
});

describe("typing while sūveryn reads (board P04, 3)", () => {
  it("keeps the field open, with its hint", () => {
    const html = renderToStaticMarkup(<RunThread run={{ ...RUN, status: "reading" }} kase={KASE} playbook={PLAYBOOK} words={words} me="u-ines" canAnswer
                                                 nameOf={names} panel={null} onChanged={noop} onPanel={noop} onDocumentsChanged={noop} />);
    expect(html).toContain(`placeholder="${en.runTypeAhead}"`);
    expect(html).not.toMatch(/<textarea[^>]*readonly/);
  });
});

describe("the playbook menu's line about the last run (board P04, 9)", () => {
  const now = new Date("2026-11-06T16:00:00");
  it("says when it ran and how it ended, or who an open run waits for", () => {
    const done = { ...SUMMARY, status: "done" as const, finished_at: "2026-11-06T15:00:00" };
    expect(lastRunLine(done, PLAYBOOK, en, "u-ines", null, now)).toBe("Last: today, done · starts a new conversation");
    expect(lastRunLine({ ...done, status: "cancelled", finished_at: "2026-11-05T15:00:00" }, PLAYBOOK, en, "u-ines", null, now))
      .toBe(`Last: ${en.yesterday.toLowerCase()}, ${en.runCancelled.toLowerCase()} · starts a new conversation`);
    const asking = { ...SUMMARY, step: "missing", step_kind: "ask" as const };
    expect(lastRunLine(asking, PLAYBOOK, en, "u-bob", "Mieke Delarivière", now)).toBe("Running: waiting for Mieke · opens that conversation");
  });
});
