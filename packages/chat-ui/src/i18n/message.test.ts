/**
 * Language files hold text, not code (the handbook's decision of 13 November 2026; suveryn-tracker#147): a message
 * with a value or a plural is ICU MessageFormat text and nothing else, it parses in its language, every language
 * gives it the same values, and no sentence is glued from pieces.
 */
import { readFileSync } from "node:fs";
import { IntlMessageFormat } from "intl-messageformat";
import { describe, expect, it } from "vitest";
import { TEXT as SETUP } from "../setup/i18n";
import { TABLES_FOR_TESTS as CHAT } from "./index";
import { LOCALES, type Lang } from "./languages";
import { messagesIn, namesIn } from "./message";
import { samplesFor } from "./rules";

type Entry = { path: string; value: unknown };
/** Every entry of a table, nested ones by their path. */
function entries(table: object, prefix = ""): Entry[] {
  return Object.entries(table).flatMap(([key, value]) =>
    value && typeof value === "object" && !Array.isArray(value) ? entries(value, `${prefix}${key}/`) : [{ path: prefix + key, value }]);
}
type Msg = { text: string; params: readonly string[] } & ((values: Record<string, string | number | boolean>) => string);
const isMessage = (v: unknown): v is Msg => typeof v === "function" && typeof (v as { text?: unknown }).text === "string";
const TABLES: Record<string, Record<Lang, object>> = { chat: CHAT, setup: SETUP };
const FILES: Record<string, string> = { chat: "./", setup: "../setup/i18n/" };

describe("a message with a value or a plural", () => {
  const { m } = messagesIn("nl-BE");
  const fr = messagesIn("fr-BE"), en = messagesIn("en-GB");

  it("takes its values by name and picks the plural by the language's own rules", () => {
    const pages = m("{n, plural, one {# pagina} other {# pagina''s}}", "n");
    expect([pages({ n: 1 }), pages({ n: 3 })]).toEqual(["1 pagina", "3 pagina's"]);
    const frPages = fr.m("{n, plural, one {# page} other {# pages}}", "n");
    expect([0, 1, 2].map((n) => frPages({ n }))).toEqual(["0 page", "1 page", "2 pages"]);  // French: zero is singular
    expect(m("{who} deelde {what}", "who", "what")({ what: "het dossier", who: "Anna" })).toBe("Anna deelde het dossier");
  });

  it("writes a quantity as the language writes it, and a number that names something as it is", () => {
    const text = "{n, plural, one {# page} other {# pages}} · {size, number} MB · page {page}";
    const values = { n: 1234, size: 2.5, page: 1234 };
    expect(en.m(text, "n", "size", "page")(values)).toBe("1,234 pages · 2.5 MB · page 1234");
    expect(m(text, "n", "size", "page")(values)).toBe("1.234 pages · 2,5 MB · page 1234");
    expect(fr.m(text, "n", "size", "page")(values)).toBe("1 234 pages · 2,5 MB · page 1234");
  });

  it("keeps its text and the names of its values beside it, for the tests and the translators' export", () => {
    const shared = en.m("{who} shared {what}", "who", "what");
    expect([shared.text, [...shared.params]]).toEqual(["{who} shared {what}", ["who", "what"]]);
    // another language writes the text alone; its values are read from it
    expect([...m("{what} gedeeld door {who}").params].sort()).toEqual(["what", "who"]);
    expect(m("{what} gedeeld door {who}")({ who: "Anna", what: "Het dossier" })).toBe("Het dossier gedeeld door Anna");
  });

  it("chooses by a word or a yes/no, and takes < and > and a doubled apostrophe as plain characters", () => {
    const was = m("{kind, select, answer {een antwoord} other {een playbookresultaat}}", "kind");
    expect([was({ kind: "answer" }), was({ kind: "playbook" })]).toEqual(["een antwoord", "een playbookresultaat"]);
    expect(m("na een {comma, select, true {komma} other {punt}}", "comma")({ comma: true })).toBe("na een komma");
    expect(fr.m("l''{what} <b>", "what")({ what: "eau" })).toBe("l'eau <b>");
  });

  it("refuses a message that doesn't parse when it is first used, never showing half of it", () => {
    expect(() => m("{n, plural, one {# pagina}", "n")({ n: 1 })).toThrow();
  });

  it("finds every branch of a message to check its words", () => {
    const samples = samplesFor("{before, select, true {{n, plural, =0 {none} one {# day before} other {# days before}}} other {{n, plural, one {# day} other {# days}}}} {name}");
    expect(new Set(samples.map((s) => `${s.before}/${s.n}`))).toEqual(new Set(["true/1", "true/3", "true/0", "zz/1", "zz/3", "zz/0"]));
    expect(samples.every((s) => s.name === "X")).toBe(true);
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
          expect(namesIn(value.text).sort(), `${where}: the values its text uses are the ones English names`).toEqual([...en.params].sort());
          for (const values of samplesFor(value.text)) expect(() => value(values), `${where} ${JSON.stringify(values)}`).not.toThrow();
        }
      }
    }
    expect(messages).toBeGreaterThan(800);
  });

  it("use the notation and nothing of our own: no value a screen doesn't give by name", () => {
    // What a message once asked the code behind it for ("was this given?", a list's count, a list said in a
    // sentence) the screen now gives as a value like any other, or settles by choosing between two messages.
    for (const [name, table] of Object.entries(TABLES)) {
      for (const lang of Object.keys(table) as Lang[]) {
        for (const { path, value } of entries(table[lang])) {
          if (!isMessage(value)) continue;
          expect(namesIn(value.text).filter((n) => /^has_|_and$/.test(n)), `${name} ${lang} ${path}`).toEqual([]);
          // a count is "#" in its own plural: "{n}" there would show it ungrouped where "#" groups it
          expect(value.text, `${name} ${lang} ${path}: write # for the count inside its plural`).not.toMatch(/\{(\w+), plural,(?:(?!\{\w+, plural,).)*\{\1\}/s);
        }
      }
    }
  });

  it("keep code out: an entry is a sentence, a table of sentences, or a message", () => {
    for (const [name, table] of Object.entries(TABLES)) {
      for (const lang of Object.keys(table) as Lang[]) {
        const code = entries(table[lang]).filter((e) => typeof e.value === "function" && !isMessage(e.value)).map((e) => e.path);
        expect(code, `${name} ${lang}`).toEqual([]);
        // only English names a message's values (that gives the screens their types); the others write the text alone
        const source = readFileSync(new URL(`${FILES[name]}${lang}.ts`, import.meta.url), "utf8");
        const named = (source.match(/\bm\("(?:[^"\\]|\\.)*", "/g) ?? []).length;
        if (lang === "en") expect(named, `${name} en`).toBeGreaterThan(10); else expect(named, `${name} ${lang}`).toBe(0);
      }
    }
  });
});

describe("whole sentences (suveryn-tracker#147)", () => {
  /** The tables whose entries are reasons: what went wrong, said on its own or after the sentence saying what failed. */
  const REASONS = /^(messages|messagesBare|messageAreas|messageKinds|backupStep|clockErrors)\/|^(messageInternalRef|conversationsUnreachable|uploadInterrupted|streamCutOff|streamError\w+|chosenDeletedMeanwhile)$/;

  it("a reason is a sentence of its own: a capital, a full stop, in every language", () => {
    let reasons = 0;
    for (const [name, table] of Object.entries(TABLES)) {
      for (const lang of Object.keys(table) as Lang[]) {
        for (const { path, value } of entries(table[lang])) {
          if (!REASONS.test(path)) continue;
          const texts = typeof value === "string" ? [value] : isMessage(value) ? samplesFor(value.text).map((v) => value(v)) : [];
          for (const text of texts) {
            reasons++;
            expect(text, `${name} ${lang} ${path}`).toMatch(/^[\p{Lu}"«„]/u);
            expect(text, `${name} ${lang} ${path}`).toMatch(/[.!?…]$/);
          }
        }
      }
    }
    expect(reasons).toBeGreaterThan(300);
  });

  it("a row of the access log is one sentence with the person in it, and the screen can draw that person itself", () => {
    for (const lang of Object.keys(CHAT) as Lang[]) {
      const rows = entries(CHAT[lang]).filter((e) => /^event[A-Z]/.test(e.path));
      expect(rows.length).toBeGreaterThan(25);
      for (const { path, value } of rows) {
        expect(isMessage(value) && value.params.includes("who"), `${lang} ${path}: say who, inside the sentence`).toBe(true);
        if (!isMessage(value)) continue;
        for (const values of samplesFor(value.text)) expect(value(values), `${lang} ${path}`).toContain("X");
      }
    }
    const who = { name: "Nora" };
    expect(CHAT.en.eventClosed.parts({ who })).toEqual([who, " closed the case"]);
    expect(CHAT.en.eventAsked.parts({ who, n: 2 })).toEqual([who, " asked a question about 2 documents"]);
  });

  it("no entry is a piece to glue on: none starts or ends with a space, or ends on a colon and a value to follow", () => {
    for (const [name, table] of Object.entries(TABLES)) {
      for (const lang of Object.keys(table) as Lang[]) {
        for (const { path, value } of entries(table[lang])) {
          const text = typeof value === "string" ? value : isMessage(value) ? value.text : "";
          expect(text, `${name} ${lang} ${path}`).not.toMatch(/^\s|\s$|\{ \S|\S \}$/);
          // "Couldn't save: {why}" made a sentence of two halves; the reason is now a sentence after a full stop
          expect(text, `${name} ${lang} ${path}`).not.toMatch(/: \{(why|reason)\}\.?$/);
        }
      }
    }
  });

  it("no screen changes the case of a text or ends it with a full stop of its own", () => {
    const files = Object.keys(import.meta.glob(["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../preview/**", "!../ui/**"]));
    expect(files.length).toBeGreaterThan(60);
    const offenders = files.filter((f) => {
      const source = readFileSync(new URL(f, import.meta.url), "utf8");
      return /charAt\(0\)\.to(Upper|Lower)Case\(\)|toLocale(Lower|Upper)Case\(/.test(source);
    });
    expect(offenders).toEqual([]);
  });
});

describe("notes for the translator (the decision's rule 4)", () => {
  type Leaf = { path: string; note: string | { note: string; max: number } };
  const isNote = (v: unknown): v is Leaf["note"] => typeof v === "string" || (!!v && typeof v === "object" && typeof (v as { note?: unknown }).note === "string");
  const leaves = (notes: object, prefix = ""): Leaf[] => Object.entries(notes).flatMap(([key, v]) =>
    isNote(v) ? [{ path: prefix + key, note: v }] : leaves(v as object, `${prefix}${key}/`));
  const at = (table: object, path: string): unknown => path.split("/").reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], table);

  it("every entry that chooses by a word says what the words are", async () => {
    const all = { chat: (await import("./notes")).notes, setup: (await import("../setup/i18n/notes")).notes };
    for (const [name, table] of Object.entries(TABLES)) {
      const noted = new Set(leaves(all[name as keyof typeof all]).map((l) => l.path));
      const missing = entries(table.en).filter((e) => isMessage(e.value) && /, select,/.test(e.value.text) && !noted.has(e.path)).map((e) => e.path);
      expect(missing, `${name}: a message with a select needs a note in notes.ts`).toEqual([]);
    }
  });

  it("is about an entry that exists, and a length it sets holds in every language", async () => {
    const all = { chat: (await import("./notes")).notes, setup: (await import("../setup/i18n/notes")).notes };
    let checked = 0;
    for (const [name, table] of Object.entries(TABLES)) {
      for (const { path, note } of leaves(all[name as keyof typeof all])) {
        expect(at(table.en, path), `${name} ${path}`).toBeDefined();
        checked++;
        if (typeof note === "string") continue;
        for (const lang of Object.keys(table) as Lang[]) {
          const text = at(table[lang], path);
          expect(typeof text, `${name} ${path}: a length is for a plain label`).toBe("string");
          expect([...(text as string)].length, `${name} ${lang} ${path}: "${text}" is longer than ${note.max}`).toBeLessThanOrEqual(note.max);
        }
      }
    }
    expect(checked).toBeGreaterThan(25);
  });

  it("explains the values that mean the same everywhere, and only values that exist", async () => {
    const { valueNotes } = await import("./notes");
    const used = new Set(entries(CHAT.en).flatMap((e) => (isMessage(e.value) ? [...e.value.params] : [])));
    expect(Object.keys(valueNotes).filter((name) => !used.has(name))).toEqual([]);
    expect(valueNotes.why).toMatch(/whole sentence/);
  });
});
