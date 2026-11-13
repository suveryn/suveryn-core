/**
 * Failures are codes, never recognised by their English words (the handbook's decision of 12 November 2026,
 * suveryn-tracker#127): the chat UI tells failures apart by the server's code (lib/messages.ts), and a
 * calculation that couldn't be done by its code, worded in every language.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { TABLES_FOR_TESTS } from "../i18n";
import { messageText } from "./messages";

const SRC = new URL("..", import.meta.url).pathname;
const sources = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
});
const CALC = ["calc.number_style", "calc.decimal_separator", "calc.division_by_zero", "calc.no_figures", "calc.syntax"];

describe("failures as codes (suveryn-tracker#127, #139)", () => {
  it("never tells a failure by the server's English words", () => {
    // a server text (detail, message, error) matched against a pattern or a string
    const matched = /\/[^/\n]+\/[a-z]*\.test\((?:[\w.?]*\.)?(?:detail|message|error)\)|(?:detail|message|error)\??\.(?:includes|startsWith|match)\(/;
    const found = sources(SRC).filter((f) => matched.test(readFileSync(f, "utf8"))).map((f) => relative(SRC, f));
    expect(found).toEqual([]);
  });

  it("says why a calculation couldn't be done in every language, from its code", () => {
    for (const [lang, m] of Object.entries(TABLES_FOR_TESTS)) {
      const said = CALC.map((code) => m.calcFailed({ expression: "1 / 0", why: messageText({ kind: "warning", code }, m) }));
      expect(new Set(said).size, lang).toBe(CALC.length);  // a sentence of its own for each code
    }
  });
});
