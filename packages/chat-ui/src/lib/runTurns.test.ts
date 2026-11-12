/**
 * The run's thread in the reader's language (decision of 12 November 2026, suveryn-tracker#126): every kind of playbook
 * turn the server writes (its turn_kinds.json, also read by the gateway's test) has words on the screen in every
 * language, and a person's button or form answer is worded from its values.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { TABLES_FOR_TESTS } from "../i18n";
import { listedTitle } from "./conversations";
import { setLang } from "../i18n/languages";
import { EVENTS, eventText, personTurnText, playbookTurnText, type TurnMeta } from "./runTurns";

const KINDS: string[] = JSON.parse(readFileSync(
  new URL("../../../api-gateway/src/suveryn_api_gateway/turn_kinds.json", import.meta.url), "utf8")).kinds;
const WORDS = { title: "Akte-intake", summary: "", labels: { price: "Prijs", kind: "Inbreng", "kind.cash": "In geld" },
                questions: { agreement: "Laad de verkoopovereenkomst op." }, steps: { agreement: "Verkoopovereenkomst", reports: "Verslagen" } };
const SAMPLE: TurnMeta = { step: "agreement", facts: ["price"], found: 1, total: 2, fact: "kind", value: "cash", documents: ["a.pdf"],
                           reads: ["agreement_read"], reason: "dubbel" };

describe("a playbook's turns, worded on the screen (suveryn-tracker#126)", () => {
  it("has words for every kind the server writes, in every language", () => {
    expect(KINDS.length).toBeGreaterThan(10);
    for (const [lang, m] of Object.entries(TABLES_FOR_TESTS)) {
      for (const kind of KINDS) {
        const text = EVENTS.has(kind) ? eventText({ ...SAMPLE, kind }, "Ines", "10:58", m) : playbookTurnText({ ...SAMPLE, kind }, m, WORDS);
        expect(text, `${lang} ${kind}`).toBeTruthy();
        expect(text, `${lang} ${kind}`).not.toMatch(/undefined|\[object/);
      }
    }
  });

  it("words a choice by its option and a step by its name, in the reader's language", () => {
    const { en, nl, fr } = TABLES_FOR_TESTS;
    expect(playbookTurnText({ kind: "request", step: "agreement" }, nl, WORDS)).toBe("Laad de verkoopovereenkomst op.");
    expect(playbookTurnText({ kind: "changed", fact: "kind", value: "cash" }, en, WORDS)).toBe(en.runChanged("Inbreng", "In geld"));
    expect(playbookTurnText({ kind: "late_documents", step: "agreement", documents: ["a.pdf"], reads: ["x"] }, nl, WORDS))
      .toBe("a.pdf: toegevoegd aan Verkoopovereenkomst. Sūveryn leest het opnieuw voor de gegevens die erin staan.");
    expect(playbookTurnText({ kind: "late_documents", step: "agreement", documents: ["a.pdf", "b.pdf"], reads: [] }, fr, WORDS))
      .toBe("a.pdf, b.pdf : ajoutés à Verkoopovereenkomst. Sūveryn les lira avec les autres.");
  });

  it("words a person's button or form answer from its values; what they wrote stays as written", () => {
    const { en, nl } = TABLES_FOR_TESTS;
    expect(personTurnText({ text: "", meta: { none: true } }, nl, WORDS)).toBe(nl.runNoDocument);
    expect(personTurnText({ text: "", meta: { case_documents: true } }, en, WORDS)).toBe(en.runUseCaseDocuments);
    expect(personTurnText({ text: "", meta: { unknown: true } }, en, WORDS)).toBe(en.answerPlaceholder);
    expect(personTurnText({ text: "", meta: { answers: { kind: "cash", price: "" } } }, nl, WORDS)).toBe("Inbreng: In geld");
    expect(personTurnText({ text: "", meta: { answers: { price: "" } } }, nl, WORDS)).toBe(nl.answerPlaceholder);
    expect(personTurnText({ text: "Het is 412.500 euro.", meta: { answers: { price: "412.500" } } }, nl, WORDS)).toBe("Het is 412.500 euro.");
  });

  it("lists a run's conversation by its title in the reader's language", () => {
    const run = { title: "Akte-intake", titles: { en: "Deed intake", nl: "Akte-intake", fr: "Analyse de l'acte" } };
    setLang("fr");
    expect(listedTitle(run)).toBe("Analyse de l'acte");
    setLang("en");
    expect(listedTitle(run)).toBe("Deed intake");
    expect(listedTitle({ title: "Mijn vraag", titles: null })).toBe("Mijn vraag");
  });
});
