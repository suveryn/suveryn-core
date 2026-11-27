/**
 * Every date, time, number and list is formatted in format.ts (suveryn-tracker#129): what each named format gives in
 * the three languages, and no other file of the chat UI calling `Intl` or `toLocale…` to format. Changing a text's
 * case (`toLocaleUpperCase`, `toLocaleLowerCase`: initials, a search) is not formatting.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import * as fmt from "./format";

const SRC = new URL("..", import.meta.url).pathname;
const FORMATTING = /\bIntl\b|\.toLocale(?:Date|Time)?String\(|\.toFixed\(/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === "node_modules" || name === "generated") return [];
    return statSync(path).isDirectory() ? files(path) : /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("dates, numbers and lists", () => {
  it("are formatted in format.ts and nowhere else", () => {
    const outside = files(SRC).filter((f) => relative(SRC, f) !== "i18n/format.ts")
      .flatMap((f) => readFileSync(f, "utf8").split("\n").map((line, i) => [`${relative(SRC, f)}:${i + 1}`, line] as const))
      .filter(([, line]) => !/^\s*(\/\/|\*|\/\*\*)/.test(line) && FORMATTING.test(line))
      .map(([where]) => where);
    expect(outside, "format it with a named format of i18n/format.ts").toEqual([]);
  });

  const at = new Date(2026, 10, 5, 9, 7, 42);  // 5 November 2026, 09:07:42, local time
  it.each([
    ["en-GB", "5 Nov", "5 November", "5 Nov 2026", "5 November 2026", "05/11/2026", "05/11/2026", "09:07", "09:07:42"],
    ["nl-BE", "5 nov", "5 november", "5 nov 2026", "5 november 2026", "5/11/2026", "05/11/2026", "09:07", "09:07:42"],
    ["fr-BE", "5 nov.", "5 novembre", "5 nov. 2026", "5 novembre 2026", "05/11/2026", "05/11/2026", "09:07", "09:07:42"],
  ])("say a date and a time as %s does", (l, day, dayLong, dayInYear, date, inDigits, inTwoDigits, time, seconds) => {
    expect([fmt.day(at, l), fmt.dayLong(at, l), fmt.dayInYear(at, l), fmt.date(at, l), fmt.dateInDigits(at, l),
            fmt.dateInTwoDigits(at, l), fmt.time(at, l), fmt.timeWithSeconds(at, l)])
      .toEqual([day, dayLong, dayInYear, date, inDigits, inTwoDigits, time, seconds]);
    expect(fmt.date(at.toISOString(), l)).toBe(date);  // a moment as the server sends it
  });

  it.each([
    ["en-GB", "1,234.57", "1,235", "1.2k", "€1,234.50", "188 kB", "1.2 GB", "2, 3 and 5"],
    ["nl-BE", "1.234,57", "1.235", "1,2K", "€ 1.234,50", "188 kB", "1,2 GB", "2, 3 en 5"],
    ["fr-BE", "1 234,57", "1 235", "1,2 k", "1 234,50 €", "188 ko", "1,2 Go", "2, 3 et 5"],
  ])("say a number, an amount, a size and a list as %s does", (l, number, whole, compact, amount, kb, gb, list) => {
    const said = [fmt.number(1234.567, { most: 2 }, l), fmt.whole(1235, l), fmt.compact(1234, l), fmt.amount("1234.5", "EUR", l),
                  fmt.bytes(188_000, l), fmt.bytes(1_234_000_000, l), fmt.list([2, 3, 5], l)];
    expect([fmt.bytes(0, l), fmt.bytes(999, l), fmt.bytes(2_500_000_000_000, l)].map((s) => s.replace(/[\u00a0\u202f]/g, " ")))
      .toEqual(l === "fr-BE" ? ["0 ko", "1 ko", "2,5 To"] : l === "nl-BE" ? ["0 kB", "1 kB", "2,5 TB"] : ["0 kB", "1 kB", "2.5 TB"]);  // from kilobytes
    // the browser's own spaces in French (a narrow no-break space) and before a unit are compared as spaces
    expect(said.map((s) => s.replace(/[\u00a0\u202f]/g, " "))).toEqual([number, whole, compact, amount, kb, gb, list]);
  });

  it.each([["en-GB", "A 1, B 2, C 3"], ["nl-BE", "A 1, B 2 en C 3"], ["fr-BE", "A 1, B 2 et C 3"]])(
    "list values as %s does", (l, said) => {
      expect(fmt.unitList(["A 1", "B 2", "C 3"], l)).toBe(said);
    });

  it("leaves a date's year out only when it is this year's", () => {
    expect([fmt.sameYear(new Date(2026, 0, 1), new Date(2026, 11, 31)), fmt.sameYear(new Date(2025, 11, 31), new Date(2026, 0, 1))])
      .toEqual([true, false]);
  });
});
