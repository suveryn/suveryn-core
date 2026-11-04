/**
 * A sentence left in English in another language's file (docs/translations.md). TypeScript already fails on a
 * missing key, and rules.ts on the brand's wording; neither notices a key that is there but was never translated,
 * which happens when a string is copied from en.ts to add a key and the translation is forgotten.
 *
 * Every text is compared with the English one at the same place, also inside nested tables and what a function
 * returns. Short ones may rightly be the same word ("Status", "Documents", "Type"); a text of four words or more
 * that is identical is taken for untranslated. The tagline stays in English everywhere, on purpose.
 */
import { describe, expect, it } from "vitest";
import setupEn from "../setup/i18n/en";
import setupFr from "../setup/i18n/fr";
import setupNl from "../setup/i18n/nl";
import en from "./en";
import fr from "./fr";
import nl from "./nl";

const ARGS = ["X", "Y", "Z", 1, 2, 3];  // what a function is called with to see its words
const ON_PURPOSE = new Set(["AI for work that can't leave the premises", "AI for work that can't leave the premises."]);

/** Every text in a table, by its path (``.backupStep.copy``, ``.pages()``). */
export function texts(value: unknown, path = "", out = new Map<string, string>()): Map<string, string> {
  if (typeof value === "function") {
    try { texts((value as (...a: unknown[]) => unknown)(...ARGS), `${path}()`, out); } catch { /* needs other arguments: skipped */ }
  } else if (typeof value === "string") out.set(path, value);
  else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) texts(v, `${path}.${k}`, out);
  return out;
}

/** The texts of ``other`` identical to the English at the same place, four words or more, not kept English on purpose. */
export function untranslated(english: unknown, other: unknown): string[] {
  const base = texts(english);
  return [...texts(other)].filter(([k, s]) => base.get(k) === s && !ON_PURPOSE.has(s)
    && s.split(/\s+/).filter((w) => /\p{L}{2}/u.test(w)).length >= 4).map(([k, s]) => `${k}: ${s}`);
}

describe("every sentence is translated", () => {
  for (const [place, english, others] of [["the chat", en, { nl, fr }], ["the web setup", setupEn, { nl: setupNl, fr: setupFr }]] as const) {
    for (const [lang, table] of Object.entries(others)) {
      it(`${place}, ${lang}`, () => expect(untranslated(english, table)).toEqual([]));
    }
  }

  it("catches a sentence copied from English, inside a table or a function too, but not a shared word", () => {
    const english = { a: "Status", b: "The document could not be read.", c: { d: (n: number) => `${n} pages were read in full.` } };
    const copied = { a: "Status", b: "The document could not be read.", c: { d: (n: number) => `${n} pages were read in full.` } };
    expect(untranslated(english, copied)).toEqual([".b: The document could not be read.", ".c.d(): X pages were read in full."]);
    expect(untranslated(english, { ...copied, b: "Het document kon niet gelezen worden.", c: { d: () => "gelezen" } })).toEqual([]);
  });
});
