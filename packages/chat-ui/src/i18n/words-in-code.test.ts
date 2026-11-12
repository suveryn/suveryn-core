/**
 * Code is English; a language's words live in its files only (docs/translations.md, principles 5 and 6). The same
 * test as the Python packages' (harness/tests/test_language.py), for the chat UI: every string the code holds (not
 * its comments) is read for a Dutch or French word of the word files (packages/<package>/src/<module>/lang/) that
 * isn't English too (suveryn-tracker#116).
 *
 * Not read: the tables themselves (src/i18n, src/setup/i18n), tests, and the screen previews (src/preview), whose
 * fictional sample case is in Dutch because the design boards it is compared with are.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = new URL("..", import.meta.url).pathname;
const PACKAGES = new URL("../../..", import.meta.url).pathname;
const NOT_READ = /^(i18n|setup\/i18n|preview)\/|\.test\.tsx?$/;
// Lists that are not a language's words: an English instruction quoting them, a file name's language codes.
const NOT_WORDS = new Set(["formal_address", "file_markers"]);
// Words of Dutch or French that are also English, or the code's own (as harness/tests/test_language.py), and
// where one file uses another as a name (an icon's).
const ALSO_CODE = new Set(["day", "week", "month", "year", "workday", "eur", "usd", "gbp", "later", "exact"]);
const ALSO_CODE_IN: Record<string, string[]> = { "ui/allowedIcons.ts": ["mars", "van"] };

const fold = (s: string) => s.normalize("NFKD").toLowerCase().replace(/\p{M}/gu, "");
const tokens = (s: string) => (fold(s).match(/\p{L}{3,}/gu) ?? []);

function files(dir: string, test: (path: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === "node_modules" || name === "dist") return [];
    return statSync(path).isDirectory() ? files(path, test) : test(path) ? [path] : [];
  });
}

/** The words of a language in every package's word files. */
function wordsOf(lang: string): Set<string> {
  const out = new Set<string>();
  const take = (v: unknown): void => {
    if (typeof v === "string") tokens(v).forEach((w) => out.add(w));
    else if (Array.isArray(v)) v.forEach(take);
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) { take(k); take(x); }
  };
  for (const path of files(PACKAGES, (p) => /\/src\/[^/]+\/lang\/[a-z]{2}\.json$/.test(p) && p.endsWith(`/${lang}.json`))) {
    const table = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
    take(Object.fromEntries(Object.entries(table).filter(([k]) => !k.startsWith("_") && !NOT_WORDS.has(k))));
  }
  return out;
}

/** The strings in a source file, its comments left out. */
function strings(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:\\])\/\/.*$/gm, "$1");
  return [...code.matchAll(/"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g)].map((m) => m[1] ?? m[2] ?? m[3]);
}

describe("no word of a language in the chat UI's code (suveryn-tracker#116)", () => {
  it("finds the word files of the harness, the rag and the gateway", () => {
    const dirs = files(PACKAGES, (p) => p.endsWith("/lang/en.json")).map((p) => relative(PACKAGES, p));
    expect(dirs).toEqual(expect.arrayContaining([
      "api-gateway/src/suveryn_api_gateway/lang/en.json", "harness/src/suveryn_harness/lang/en.json", "rag/src/suveryn_rag/lang/en.json"]));
  });

  it("holds none outside the tables", () => {
    const english = wordsOf("en");
    const foreign = new Set([...wordsOf("nl"), ...wordsOf("fr")].filter((w) => !english.has(w)));
    const found: Record<string, string[]> = {};
    for (const path of files(SRC, (p) => /\.tsx?$/.test(p))) {
      const name = relative(SRC, path);
      if (NOT_READ.test(name)) continue;
      const allowed = new Set([...ALSO_CODE, ...(ALSO_CODE_IN[name] ?? [])]);
      const hits = new Set(strings(readFileSync(path, "utf8")).flatMap(tokens).filter((w) => foreign.has(w) && !allowed.has(w)));
      if (hits.size) found[name] = [...hits].sort();
    }
    expect(found).toEqual({});
  });
});
