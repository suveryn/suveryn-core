/**
 * Failures are codes, never recognised by their English words (the handbook's decision of 12 November 2026,
 * suveryn-tracker#127): the chat UI tells failures apart by the server's ``reason`` or ``error_code``, and a
 * calculation that couldn't be done by its ``reason``, worded in every language.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { TABLES_FOR_TESTS } from "../i18n";

const SRC = new URL("..", import.meta.url).pathname;
const sources = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
});
const REASONS = ["number_style", "decimal_separator", "division_by_zero", "no_figures", "syntax"];  // suveryn_harness.calc.REASONS

describe("failures as codes (suveryn-tracker#127)", () => {
  it("never tells a failure by the server's English words", () => {
    // a server text (detail, message, error) matched against a pattern or a string
    const matched = /\/[^/\n]+\/[a-z]*\.test\((?:[\w.?]*\.)?(?:detail|message|error)\)|(?:detail|message|error)\??\.(?:includes|startsWith|match)\(/;
    const found = sources(SRC).filter((f) => matched.test(readFileSync(f, "utf8"))).map((f) => relative(SRC, f));
    expect(found).toEqual([]);
  });

  it("says why a calculation couldn't be done in every language, from its code", () => {
    for (const [lang, m] of Object.entries(TABLES_FOR_TESTS)) {
      const said = REASONS.map((r) => m.calcFailed("1 / 0", r));
      expect(new Set(said).size, lang).toBe(REASONS.length);  // a sentence of its own for each code
      expect(m.calcFailed("1 / 0", ""), lang).toBe(m.calcFailed("1 / 0", "syntax"));  // no code (saved before): the plain one
    }
  });
});
