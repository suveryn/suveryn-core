/**
 * Language files hold text, not code (the handbook's decision of 13 November 2026; suveryn-tracker#147): a message
 * with a value or a plural is ICU MessageFormat text, the same shape in every language, and it parses.
 */
import { IntlMessageFormat } from "intl-messageformat";
import { describe, expect, it } from "vitest";
import { TEXT as SETUP } from "../setup/i18n";
import { TABLES_FOR_TESTS as CHAT } from "./index";
import { LOCALES, type Lang } from "./languages";
import { messagesIn, namesIn } from "./message";

type Entry = { path: string; value: unknown };
/** Every entry of a table, nested ones by their path. */
function entries(table: object, prefix = ""): Entry[] {
  return Object.entries(table).flatMap(([key, value]) =>
    value && typeof value === "object" && !Array.isArray(value) ? entries(value, `${prefix}${key}/`) : [{ path: prefix + key, value }]);
}
const isMessage = (v: unknown): v is { text: string; params: readonly string[] } & ((...a: unknown[]) => string) =>
  typeof v === "function" && typeof (v as { text?: unknown }).text === "string";
const TABLES: Record<string, Record<Lang, object>> = { chat: CHAT, setup: SETUP };

describe("a message with a value or a plural", () => {
  const { m, mp } = messagesIn("nl-BE");
  const fr = messagesIn("fr-BE");

  it("fills in its values by position and picks the plural by the language's own rules", () => {
    const pages = m("{n, plural, one {{n} pagina} other {{n} pagina''s}}", "n");
    expect([pages(1), pages(3), pages(1234)]).toEqual(["1 pagina", "3 pagina's", "1234 pagina's"]);  // a number as given, never grouped
    const frPages = fr.m("{n, plural, one {{n} page} other {{n} pages}}", "n");
    expect([frPages(0), frPages(1), frPages(2)]).toEqual(["0 page", "1 page", "2 pages"]);  // French: zero is singular
    expect(m("{who} deelde {what}", "who", "what")("Anna", "het dossier")).toBe("Anna deelde het dossier");
  });

  it("keeps its text and the names of its values beside it, for the tests and the translators' export", () => {
    const shared = m("{who} deelde {what}", "who", "what");
    expect(shared.text).toBe("{who} deelde {what}");
    expect(shared.params).toEqual(["who", "what"]);
    expect(mp("groter dan {max_mb} MB").params).toEqual(["max_mb"]);
  });

  it("asks whether a value was given with has_, and shows a missing one as nothing", () => {
    const closed = m("{has_date, select, yes {Dossier gesloten · verwijderd op {date}} other {Dossier gesloten}}", "date");
    expect([closed("3 mei"), closed(null), closed(undefined), closed("")]).toEqual(["Dossier gesloten · verwijderd op 3 mei", "Dossier gesloten", "Dossier gesloten", "Dossier gesloten"]);
    const internal = mp("{has_ref, select, yes {referentie: {ref}} other {geen referentie}}");
    expect([internal({ ref: "7F3K-92QD" }), internal({})]).toEqual(["referentie: 7F3K-92QD", "geen referentie"]);
    expect(m("a {x} b", "x")(undefined)).toBe("a  b");
  });

  it("writes a list as its items and counts them for a plural", () => {
    const list = m("{pages_count, plural, one {p. {pages}} other {pp. {pages}}}", "pages");
    expect([list([4]), list([4, 7, 9])]).toEqual(["p. 4", "pp. 4, 7, 9"]);
    const hint = m("{has_pages, select, yes {op {pages}} other {op sommige pagina''s}}", "pages");
    expect([hint([2]), hint([]), hint(undefined)]).toEqual(["op 2", "op sommige pagina's", "op sommige pagina's"]);
  });

  it("chooses by a word or a yes/no, and takes < and > and a doubled apostrophe as plain characters", () => {
    const was = m("{kind, select, answer {een antwoord} other {een playbookresultaat}}", "kind");
    expect([was("answer"), was("playbook")]).toEqual(["een antwoord", "een playbookresultaat"]);
    expect(m("na een {comma, select, true {komma} other {punt}}", "comma")(true)).toBe("na een komma");
    expect(fr.m("l''{what} <b>", "what")("eau")).toBe("l'eau <b>");
  });

  it("refuses a message that doesn't parse when it is first used, never showing half of it", () => {
    expect(() => m("{n, plural, one {{n} pagina}", "n")(1)).toThrow();
  });
});

describe("the language files (suveryn-tracker#147)", () => {
  it("hold a message as text that parses in its language, with the same values in every language", () => {
    let messages = 0;
    for (const [name, table] of Object.entries(TABLES)) {
      const english = new Map(entries(table.en).map((e) => [e.path, e.value]));
      for (const lang of Object.keys(table) as Lang[]) {
        for (const { path, value } of entries(table[lang])) {
          const en = english.get(path);
          const where = `${name} ${lang} ${path}`;
          expect(isMessage(value), `${where}: a message in English is a message here, and the other way round`).toBe(isMessage(en));
          if (!isMessage(value) || !isMessage(en)) continue;
          messages++;
          expect(() => new IntlMessageFormat(value.text, LOCALES[lang], undefined, { ignoreTag: true }), where).not.toThrow();
          expect([...value.params], `${where}: the same values, in the same order, as English`).toEqual([...en.params]);
          const used = namesIn(value.text);
          expect(used.filter((n) => !value.params.includes(n)), `${where}: a value its text uses but nobody gives`).toEqual([]);
          expect(value.text, `${where}: # groups a number ("1,234"); write {n}`).not.toMatch(/(^|[^'])#/);
        }
      }
    }
    expect(messages).toBeGreaterThan(800);
  });

  it("keep code out: an entry is text, and the few that are real logic are counted and may only go down", () => {
    // What is left as a function, and why: a full stop added unless the reason ends a sentence (settingsFailed); a
    // lookup whose key has a hyphen (kind); numbers in words (pbTerm); a title's first letter lowered (pbListTitle);
    // "pages 2, 3 and 5" (the five note… entries); where a citation was found (citationIssue). A new entry is text.
    const LOGIC = { chat: 10, setup: 0 };
    for (const [name, table] of Object.entries(TABLES)) {
      const code = entries(table.en).filter((e) => typeof e.value === "function" && !isMessage(e.value)).map((e) => e.path);
      expect(code.length, `${name}: ${code.join(", ")}`).toBe(LOGIC[name as keyof typeof LOGIC]);
    }
  });
});
