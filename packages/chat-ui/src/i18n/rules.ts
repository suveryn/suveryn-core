/**
 * The copy rules every string table follows, in every language (docs/translations.md), checked by the
 * chat's and the web setup's tests alike, so a new language or a new table gets the same checks:
 * nothing empty, Dutch formal (u, uw), French formal (vous), "sūveryn" in lower case except where it
 * opens a sentence, no em dashes, and the fixed terms (docs/translations.md) where a test can see them.
 */
import { IntlMessageFormat } from "intl-messageformat";
import type { Lang } from "./languages";
import type { Message } from "./message";

/** Values that walk every branch of a message: each word a `select` chooses by (and one it doesn't know), one and
 *  several for a plural (and none where it has `=0`), "X" or 3 for a plain value. At most 48 combinations. */
export function samplesFor(text: string): Record<string, string | number>[] {
  type Node = { type: number; value?: string; options?: Record<string, { value: Node[] }> };
  const choices = new Map<string, Set<string | number>>();
  const add = (name: string, ...values: (string | number)[]) => choices.set(name, new Set([...(choices.get(name) ?? []), ...values]));
  const walk = (nodes: Node[]) => {
    for (const node of nodes) {
      if (!node.value || node.type === 0 || node.type === 7 || node.type === 8) continue;
      const keys = Object.keys(node.options ?? {});
      if (node.type === 5) add(node.value, ...keys.map((k) => (k === "other" ? "zz" : k)));
      else if (node.type === 6) add(node.value, 1, 3, ...(keys.includes("=0") ? [0] : []));
      else if (node.type === 2) add(node.value, 3);
      else if (!choices.has(node.value)) add(node.value, "X");
      for (const option of Object.values(node.options ?? {})) walk(option.value);
    }
  };
  walk(new IntlMessageFormat(text, "en", undefined, { ignoreTag: true }).getAst() as unknown as Node[]);
  let all: Record<string, string | number>[] = [{}];
  for (const [name, values] of choices) {
    // a value that is both a count and a plain value keeps its numbers
    const list = [...values].some((v) => typeof v === "number") ? [...values].filter((v) => typeof v === "number") : [...values];
    all = all.flatMap((sample) => list.map((v) => ({ ...sample, [name]: v }))).slice(0, 48);
  }
  return all;
}

/** Every string in a table, as [path, text]: a message is formatted once for each of its branches (``samplesFor``),
 *  objects and arrays are walked. */
export function strings(table: unknown, path = ""): [string, string][] {
  if (typeof table === "string") return [[path, table]];
  if (typeof table === "function") {
    const message = table as Message;
    return samplesFor(message.text).map((values, i) => [`${path}(${i})`, message(values)] as [string, string]);
  }
  if (Array.isArray(table)) return table.flatMap((x, i) => strings(x, `${path}[${i}]`));
  if (table && typeof table === "object") return Object.entries(table).flatMap(([k, x]) => strings(x, path ? `${path}.${k}` : k));
  return [];
}

/** What breaks the rules in one language's strings: [path, why]; empty when all is well. */
export function copyProblems(lang: Lang, texts: [string, string][]): [string, string][] {
  const out: [string, string][] = [];
  for (const [path, text] of texts) {
    if (!text.trim()) out.push([path, "empty"]);
    if (text.includes("—")) out.push([path, "em dash"]);
    if (lang === "nl" && /(^|[^\p{L}])(je|jij|jouw|jullie)(?![\p{L}])/iu.test(text)) out.push([path, "informal Dutch"]);
    if (lang === "fr" && /(^|[^\p{L}])(tu|toi|ton|ta|tes)(?![\p{L}'’])/iu.test(text)) out.push([path, "informal French"]);
    // Dutch says "gedeelde map" and "ondersteuning" (docs/translations.md); a written address may hold "\\share"
    if (lang === "nl" && /(?<![\\\p{L}])share(?!\p{L})/iu.test(text)) out.push([path, "\"share\" in Dutch: gedeelde map"]);
    if (lang === "nl" && /(?<!\p{L})support/iu.test(text)) out.push([path, "\"support\" in Dutch: ondersteuning"]);
    // One word for the office and one for the machine (pod round of aebf5bc, findings 11 and 13).
    if (lang === "fr" && /(?<!\p{L})(cabinet|bureau)(?!\p{L})/iu.test(text)) out.push([path, "the office in French: étude"]);
    if (lang === "nl" && /(?<!\p{L})toestel(?!\p{L})/iu.test(text)) out.push([path, "the machine in Dutch: appliance"]);
    // sūveryn in lower case, capitalised only where it opens a sentence (a label, a line, after . ! ? :);
    // "Sūveryn Labs" is the company's name; "suveryn-backups" is a folder's name on a backup disk, as written there
    const misspelt = /suveryn/i.test(text.replaceAll("sūveryn", "").replaceAll("Sūveryn", "").replaceAll("suveryn-backups", ""));
    const capitalMidSentence = /(?<![.!?:]\s|^)Sūveryn(?! Labs)/u.test(text);
    const lowerAfterStop = /[.!?]\s+sūveryn/u.test(text);
    if (misspelt || capitalMidSentence || lowerAfterStop) out.push([path, "sūveryn's spelling or case"]);
  }
  return out;
}
