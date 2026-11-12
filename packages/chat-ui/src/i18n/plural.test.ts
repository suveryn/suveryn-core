/**
 * Counts take the singular by each language's plural rules (CLDR, through Intl.PluralRules), not by
 * `n === 1` (suveryn-tracker#117): French says "0 page", English "0 pages", Dutch "0 pagina's".
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import setupFr from "../setup/i18n/fr";
import en from "./en";
import fr from "./fr";
import { LOCALES } from "./languages";
import nl from "./nl";
import { singularIn } from "./plural";

describe("plural rules (suveryn-tracker#117)", () => {
  it("follow CLDR: French takes the singular for 0 and 1, English and Dutch for 1 only", () => {
    const fr1 = singularIn(LOCALES.fr), en1 = singularIn(LOCALES.en), nl1 = singularIn(LOCALES.nl);
    expect([0, 1, 1.5, 2, 1000000].map(fr1)).toEqual([true, true, true, false, false]);
    expect([0, 1, 1.5, 2].map(en1)).toEqual([false, true, false, false]);
    expect([0, 1, 1.5, 2].map(nl1)).toEqual([false, true, false, false]);
  });

  it("are what the tables say for 0, 1 and 2", () => {
    expect([0, 1, 2].map(fr.pages)).toEqual(["0 page", "1 page", "2 pages"]);
    expect([0, 1, 2].map(en.pages)).toEqual(["0 pages", "1 page", "2 pages"]);
    expect([0, 1, 2].map(nl.pages)).toEqual(["0 pagina's", "1 pagina", "2 pagina's"]);
    expect(fr.casesDue(0)).toBe("0 dossier sera bientôt supprimé");
    expect(fr.usersCount(1, 10)).toBe("1 utilisateur sur 10");
    expect(setupFr.certifiedValue(0, 2)).toBe("0 connecteur · 2 playbooks");
  });

  it("no table chooses a plural by comparing with 1", () => {
    const tables = ["en", "nl", "fr"].flatMap((l) => [`./${l}.ts`, `../setup/i18n/${l}.ts`]);
    const offenders = tables.filter((t) =>
      /[=!]==\s*1\b|\.length\s*[<>]=?\s*[12]\b/.test(readFileSync(new URL(t, import.meta.url), "utf8")));
    expect(offenders).toEqual([]);
  });
});
