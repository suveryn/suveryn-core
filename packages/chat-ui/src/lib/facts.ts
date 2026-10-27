/**
 * The facts of a text, normalised so a claim and its source compare however each writes them (suveryn-tracker#25):
 * numbers with any thousands and decimal separators ("1.275.000,00" = "1 275 000"), amounts with a scale word
 * ("1,2 million" = 1200000), number words in Dutch, French and English ("twelve" = 12), and dates in numeric and
 * written forms ("12/03/2021" = "12 March 2021" = "2021-03-12").
 *
 * The word tables below are language data, like the interface's translation tables.
 */
export type Fact = { start: number; end: number; values: string[] };

// A number on its own, not glued to letters ("oyosish4" in OCR noise is no 4).
// Grouped by . or , or by a (hard) space between thousands ("1 250"), not any space ("2021 12" is two numbers).
export const NUMBER = /(?<![\p{L}\d])(?:\d{1,3}(?:[   ]\d{3})+(?!\d)|\d+)(?:[.,]\d+)*(?![\p{L}])/gu;

const MONTHS: Record<string, number> = {};
const monthNames: [number, string][] = [
  [1, "januari jan january janvier janv"], [2, "februari feb febr february février fevrier févr fév fevr"],
  [3, "maart mrt mar march mars"], [4, "april apr avril avr"], [5, "mei may mai"], [6, "juni jun june juin"],
  [7, "juli jul july juillet juil"], [8, "augustus aug august août aout"],
  [9, "september sep sept septembre"], [10, "oktober okt october oct octobre"],
  [11, "november nov novembre"], [12, "december dec décembre decembre déc"],
];
for (const [n, names] of monthNames) for (const name of names.split(" ")) MONTHS[name] = n;
const MONTH = `(?:${Object.keys(MONTHS).sort((a, b) => b.length - a.length).join("|")})\\.?`;

// Words for numbers on their own. "een", "un", "une" and "one" are left out: mostly articles ("a"), not counts.
const NUMBER_WORDS: Record<string, number> = {};
const wordTable: [string, number[]][] = [
  ["nul één twee drie vier vijf zes zeven acht negen tien elf twaalf dertien veertien vijftien zestien zeventien achttien negentien",
    [...Array(20).keys()]],
  ["zéro zero", [0, 0]],
  ["deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize", [...Array(15).keys()].map((i) => i + 2)],
  ["two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen",
    [...Array(18).keys()].map((i) => i + 2)],
  ["twintig dertig veertig vijftig zestig zeventig tachtig negentig", [20, 30, 40, 50, 60, 70, 80, 90]],
  ["vingt trente quarante cinquante soixante septante huitante octante nonante", [20, 30, 40, 50, 60, 70, 80, 80, 90]],
  ["twenty thirty forty fifty sixty seventy eighty ninety", [20, 30, 40, 50, 60, 70, 80, 90]],
  ["honderd hundred duizend mille thousand", [100, 100, 1000, 1000, 1000]],
];
for (const [words, values] of wordTable) words.split(" ").forEach((w, i) => (NUMBER_WORDS[w] = values[i]));
const DUTCH_UNITS: Record<string, number> = { een: 1, één: 1, twee: 2, drie: 3, vier: 4, vijf: 5, zes: 6, zeven: 7, acht: 8, negen: 9 };
const DUTCH_TENS = "twintig|dertig|veertig|vijftig|zestig|zeventig|tachtig|negentig";
// Parts of a hyphenated number ("vingt-et-un", "quatre-vingt-dix", "twenty-one"), where "un" and "one" do count.
const PARTS: Record<string, number> = { ...NUMBER_WORDS, un: 1, une: 1, one: 1, et: 0, vingts: 20 };

// Scale words after a number: "1,2 miljoen", "two million", "3 mio".
const SCALES: Record<string, number> = {
  duizend: 1e3, mille: 1e3, thousand: 1e3, miljoen: 1e6, miljoenen: 1e6, million: 1e6, millions: 1e6, mio: 1e6, mln: 1e6,
  miljard: 1e9, milliard: 1e9, milliards: 1e9, billion: 1e9, mld: 1e9,
};
const SCALE = new RegExp(`^[ \\u00a0\\u202f]*(${Object.keys(SCALES).join("|")})\\.?(?![\\p{L}])`, "iu");

/** A written number's value: the last separator is decimal when 1 or 2 digits follow it, or 3 after a lone 0. */
export function numberValue(raw: string): number {
  const s = raw.replace(/[   ]/g, "");
  const last = s.match(/^(.*?)([.,])(\d+)$/);
  if (!last) return Number(s);
  const [, head, , tail] = last;
  return tail.length !== 3 || head === "0" ? Number(`${head.replace(/[.,]/g, "")}.${tail}`) : Number(s.replace(/[.,]/g, ""));
}

const show = (v: number) => String(Number.isInteger(v) ? v : Math.round(v * 100) / 100);

/** A number word's value ("twaalf", "eenentwintig", "vingt-deux", "quatre-vingt-dix", "twenty-one"), or null. */
export function wordValue(word: string): number | null {
  const w = word.toLowerCase();
  if (w in NUMBER_WORDS) return NUMBER_WORDS[w];
  const dutch = w.match(new RegExp(`^(een|één|twee|drie|vier|vijf|zes|zeven|acht|negen)(?:en|ën)(${DUTCH_TENS})$`));
  if (dutch) return DUTCH_UNITS[dutch[1]] + NUMBER_WORDS[dutch[2]];
  const parts = w.split(/[- ]+/).filter((p) => p !== "et");
  if (parts.length < 2 || parts.some((p) => !(p in PARTS))) return null;
  // "quatre-vingt(s)" is 4 × 20; otherwise the parts add up, largest first ("dix-sept", "vingt-et-un", "soixante-douze").
  const values = parts[0] === "quatre" && /^vingts?$/.test(parts[1]) ? [80, ...parts.slice(2).map((p) => PARTS[p])] : parts.map((p) => PARTS[p]);
  if (values[0] < 10 || values.slice(1).some((v, i) => v >= values[i])) return null;
  return values.reduce((a, b) => a + b, 0);
}

const DAY = "(\\d{1,2})(?:er|e|de|ste|st|nd|rd|th)?";
const PATTERNS: { re: RegExp; read: (m: RegExpExecArray) => string[] | null }[] = [
  // 2021-03-12
  { re: /(?<![\d.,/-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d])/gu, read: (m) => date(+m[1], +m[2], +m[3]) },
  // 12/03/2021, 12-03-2021, 12.03.2021, 12/03/21
  { re: /(?<![\d.,/-])(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?![\d]|[.,]\d)/gu, read: (m) => date(year(m[4]), +m[3], +m[1]) },
  // 12 March 2021, 1er mars 2021
  { re: new RegExp(`(?<![\\p{L}\\d])${DAY}\\s+(${MONTH})\\s+(\\d{4})(?!\\d)`, "giu"), read: (m) => date(+m[3], month(m[2]), +m[1]) },
  // March 12, 2021
  { re: new RegExp(`(?<![\\p{L}\\d])(${MONTH})\\s+${DAY},?\\s+(\\d{4})(?!\\d)`, "giu"), read: (m) => date(+m[3], month(m[1]), +m[2]) },
  // March 2021
  { re: new RegExp(`(?<![\\p{L}\\d])(${MONTH})\\s+(\\d{4})(?!\\d)`, "giu"),
    read: (m) => { const mo = month(m[1]); return mo ? [`m:${m[2]}-${pad(mo)}`, `n:${m[2]}`] : null; } },
  // 1.275.000,00 and 1 250, with a scale word after them
  { re: NUMBER, read: (m) => [`n:${show(numberValue(m[0]))}`] },
  // twelve, vingt-deux, eenentwintig, vingt et un
  { re: /(?<![\p{L}\d])(?:\p{L}+(?:-\p{L}+)*|(?:vingt|trente|quarante|cinquante|soixante) et (?:un|une|onze))(?![\p{L}\d])/giu,
    read: (m) => { const v = wordValue(m[0].replace(/ /g, "-")); return v === null ? null : [`n:${v}`]; } },
];

const pad = (n: number) => String(n).padStart(2, "0");
const year = (y: string) => (y.length === 4 ? +y : +y < 50 ? 2000 + +y : 1900 + +y);
const month = (name: string) => MONTHS[name.toLowerCase().replace(/\.$/, "")] ?? 0;
function date(y: number, m: number, d: number): string[] | null {
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  return [`d:${y}-${pad(m)}-${pad(d)}`, `m:${y}-${pad(m)}`, `n:${y}`];
}

/** The facts of a text with where they are, earlier patterns (dates) before later ones (numbers) where they overlap. */
export function facts(text: string): Fact[] {
  const out: Fact[] = [];
  const taken = (a: number, z: number) => out.some((f) => a < f.end && z > f.start);
  for (const { re, read } of PATTERNS) {
    for (const m of text.matchAll(re)) {
      const start = m.index!;
      let end = start + m[0].length;
      if (taken(start, end)) continue;
      let values = read(m as RegExpExecArray);
      if (!values) continue;
      // "in acht nemen" ("to take into account") is no 8.
      if (/^acht$/i.test(m[0]) && /\bin\s+$/i.test(text.slice(Math.max(0, start - 4), start))) continue;
      const scale = values.length === 1 && values[0].startsWith("n:") ? SCALE.exec(text.slice(end)) : null;
      if (scale) {
        values = [`n:${show(Number(values[0].slice(2)) * SCALES[scale[1].toLowerCase()])}`];
        end += scale[0].length;
      }
      out.push({ start, end, values });
    }
  }
  return out.sort((a, b) => a.start - b.start);
}

/** All normalised values of a text's facts. */
export const factValues = (text: string) => new Set(facts(text).flatMap((f) => f.values));
