/**
 * The copy rules every string table follows, in every language (docs/translations.md), checked by the
 * chat's and the web setup's tests alike, so a new language or a new table gets the same checks:
 * nothing empty, Dutch formal (u, uw), French formal (vous), "sūveryn" in lower case except where it
 * opens a sentence, no em dashes.
 */
import type { Lang } from "./languages";

/** Every string in a table, as [path, text]: functions are called with ``samples[key]`` (lists of
 *  argument lists) or two default argument lists, objects and arrays are walked. */
export function strings(table: unknown, samples: Record<string, unknown[][]> = {}, path = ""): [string, string][] {
  if (typeof table === "string") return [[path, table]];
  if (typeof table === "function") {
    const key = path.split(".").pop() ?? "";
    const calls = samples[key] ?? [["X", "Y", 3], ["Y", 2, null]];
    return calls.map((args, i) => [`${path}(${i})`, String((table as (...a: unknown[]) => unknown)(...args))] as [string, string]);
  }
  if (Array.isArray(table)) return table.flatMap((x, i) => strings(x, samples, `${path}[${i}]`));
  if (table && typeof table === "object") return Object.entries(table).flatMap(([k, x]) => strings(x, samples, path ? `${path}.${k}` : k));
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
    // sūveryn in lower case, capitalised only where it opens a sentence (a label, a line, after . ! ? :);
    // "Sūveryn Labs" is the company's name
    const misspelt = /suveryn/i.test(text.replaceAll("sūveryn", "").replaceAll("Sūveryn", ""));
    const capitalMidSentence = /(?<![.!?:]\s|^)Sūveryn(?! Labs)/u.test(text);
    const lowerAfterStop = /[.!?]\s+sūveryn/u.test(text);
    if (misspelt || capitalMidSentence || lowerAfterStop) out.push([path, "sūveryn's spelling or case"]);
  }
  return out;
}
