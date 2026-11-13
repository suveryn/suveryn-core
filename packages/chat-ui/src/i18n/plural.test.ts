/**
 * Counts take the singular by each language's plural rules (CLDR, through Intl.PluralRules), not by
 * `n === 1` (suveryn-tracker#117): French says "0 page", English "0 pages", Dutch "0 pagina's".
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import setupFr from "../setup/i18n/fr";
import en from "./en";
import fr from "./fr";
import nl from "./nl";

describe("plural rules (suveryn-tracker#117)", () => {
  it("are what the tables say for 0, 1 and 2", () => {
    expect([0, 1, 2].map((n) => fr.pages({ n }))).toEqual(["0 page", "1 page", "2 pages"]);
    expect([0, 1, 2].map((n) => en.pages({ n }))).toEqual(["0 pages", "1 page", "2 pages"]);
    expect([0, 1, 2].map((n) => nl.pages({ n }))).toEqual(["0 pagina's", "1 pagina", "2 pagina's"]);
    expect(fr.casesDue({ n: 0 })).toBe("0 dossier sera bientôt supprimé");
    expect(fr.usersCountOf({ n: 1, max: 10 })).toBe("1 utilisateur sur 10");
    expect([en.pages({ n: 1234 }), nl.pages({ n: 1234 })]).toEqual(["1,234 pages", "1.234 pagina's"]);  // each language groups a number its own way
    expect(setupFr.certifiedValue({ c: 0, p: 2 })).toBe("0 connecteur · 2 playbooks");
  });

  it("no table chooses a plural by comparing with 1", () => {
    const tables = ["en", "nl", "fr"].flatMap((l) => [`./${l}.ts`, `../setup/i18n/${l}.ts`]);
    const offenders = tables.filter((t) =>
      /[=!]==\s*1\b|\.length\s*[<>]=?\s*[12]\b/.test(readFileSync(new URL(t, import.meta.url), "utf8")));
    expect(offenders).toEqual([]);
  });
});
