/**
 * Language files hold text, not code (the handbook's decision of 13 November 2026; suveryn-tracker#147;
 * docs/translations.md). An entry that needs a value or depends on a number is one message in ICU MessageFormat,
 * the notation translators' tools read, formatted by `intl-messageformat`:
 *
 *     pages: m("{n, plural, one {{n} page} other {{n} pages}}", "n")        then, on a screen:  t.pages(3)
 *
 * `m` gives the function the screens already call, and keeps the text and the names of its values beside it
 * (`.text`, `.params`), for the tests and for the export to translators. The plural rules are CLDR's, from the
 * browser; nothing is fetched.
 *
 * Three conventions, the same in every language file:
 * - A value is written `{name}`; a number shows as it is given (no grouping), as it always did. Use `{n}` inside a
 *   plural's branches, not `#`, which would group it ("1,234").
 * - A value that may be missing can be asked about with `has_<name>`, which is `yes` or `no`:
 *   `{has_ref, select, yes {… reference: {ref}} other {…}}`. Missing means not given, empty, or 0.
 * - A list is written `{name}` too: its items, separated by ", ". How many there are is `{name_count}`, for a
 *   plural: `{pages_count, plural, one {p.} other {pp.}} {pages}`. `{name_and}` is the list as the language says it
 *   in a sentence ("2, 3 and 5", "2, 3 en 5", "2, 3 et 5": CLDR's rules, from the browser's `Intl.ListFormat`).
 * - An apostrophe before `{` is doubled (`l''{name}`): a single one would start a quotation in ICU MessageFormat.
 */
import { IntlMessageFormat } from "intl-messageformat";

/** A value for a message: text, a number, or a yes/no to choose by (`{comma, select, true {…} other {…}}`);
 *  anything missing shows as nothing. */
export type Arg = string | number | boolean | readonly (string | number)[] | null | undefined;
/** A message with its values by position: what a screen calls, and its text and value names for tests and tools. */
export interface Message<A extends readonly unknown[]> {
  (...args: A): string;
  readonly text: string;
  readonly params: readonly string[];
}
/** A message whose values come as one object (a code's parameters, lib/messages.ts). */
export interface ParamsMessage {
  (p: Record<string, Arg>): string;
  readonly text: string;
  readonly params: readonly string[];
}

const HAS = /\bhas_([A-Za-z0-9_]+)/g;
const given = (v: Arg) => v !== undefined && v !== null && v !== "" && v !== 0 && v !== false && !(Array.isArray(v) && v.length === 0);

/** The values a message is formatted with: every name it uses, missing ones as nothing, and its `has_` questions. */
function valuesFor(text: string, names: readonly string[], get: (name: string) => Arg, locale: string): Record<string, string | number> {
  const values: Record<string, string | number> = {};
  for (const name of names) {
    const v = get(name);
    // a list: its items, how many, and as the language says it; a single value counts as one
    const items = Array.isArray(v) ? v : given(v) ? [v as string | number] : [];
    values[name] = Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? String(v) : ((v as string | number | null | undefined) ?? "");
    values[`${name}_count`] = items.length;
    values[`${name}_and`] = items.length > 1 ? new Intl.ListFormat(locale, { type: "conjunction" }).format(items.map(String)) : String(items[0] ?? "");
  }
  for (const [, name] of text.matchAll(HAS)) values[`has_${name}`] = given(get(name)) ? "yes" : "no";
  return values;
}

/** The names of the values a message's text uses (`{name}`, `{name, plural, …}`), read from its parsed form;
 *  a list's count (`{pages_count, …}`) is the list's, and a `has_` question isn't a value. */
export function namesIn(text: string): string[] {
  type Node = { type: number; value?: string; options?: Record<string, { value: Node[] }>; children?: Node[] };
  const names = new Set<string>();
  const walk = (nodes: Node[]) => {
    for (const node of nodes) {
      // 0 is plain text and 7 the "#" of a plural; every other kind names a value
      if (node.type !== 0 && node.type !== 7 && node.type !== 8 && node.value) names.add(node.value);
      for (const option of Object.values(node.options ?? {})) walk(option.value);
      if (node.children) walk(node.children);
    }
  };
  walk(new IntlMessageFormat(text, "en", undefined, { ignoreTag: true }).getAst() as unknown as Node[]);
  return [...new Set([...names].filter((n) => !n.startsWith("has_")).map((n) => n.replace(/_(count|and)$/, "")))];
}

/** `m` and `mp` for one language: its messages are formatted with that language's plural rules. */
export function messagesIn(locale: string) {
  const formatter = (text: string) => {
    let made: IntlMessageFormat | undefined;
    // ignoreTag: "<" and ">" in a sentence are just characters
    return (values: Record<string, string | number>) => String((made ??= new IntlMessageFormat(text, locale, undefined, { ignoreTag: true })).format(values));
  };
  /** A message whose values are given by position, in the order of `params`. */
  function m<const N extends readonly string[]>(text: string, ...params: N): Message<{ [K in keyof N]: Arg }> {
    const format = formatter(text);
    const f = (...args: Arg[]) => format(valuesFor(text, params, (name) => args[params.indexOf(name)], locale));
    return Object.assign(f, { text, params }) as unknown as Message<{ [K in keyof N]: Arg }>;
  }
  /** A message whose values are given as one object: the parameters of one of the server's codes. */
  function mp(text: string): ParamsMessage {
    const format = formatter(text);
    let names: string[] | undefined;  // read from the text when first needed: a table of messages costs nothing to load
    const params = () => (names ??= namesIn(text));
    const f = (p: Record<string, Arg>) => format(valuesFor(text, [...new Set([...params(), ...[...text.matchAll(HAS)].map(([, name]) => name)])], (name) => p?.[name], locale));
    return Object.defineProperties(f, { text: { value: text }, params: { get: params } }) as unknown as ParamsMessage;
  }
  return { m, mp };
}

/** A reason as the end of a sentence: with a full stop, unless it already ends one ("…: done." never "done.."). */
export const asSentence = (text: string): string => (/[.!?]$/.test(text) ? text : `${text}.`);
/** A title inside a sentence: its first letter lowered ("All facts for the deed"). */
export const lowerFirst = (text: string): string => text.charAt(0).toLowerCase() + text.slice(1);
