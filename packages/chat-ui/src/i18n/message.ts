/**
 * Language files hold text, not code (the handbook's decision of 13 November 2026; suveryn-tracker#147;
 * docs/translations.md). An entry that needs a value or depends on a number is one message in ICU MessageFormat,
 * the notation translators' tools read, formatted by `intl-messageformat`:
 *
 *     pages: m("{n, plural, one {# page} other {# pages}}", "n")        then, on a screen:  t.pages({ n: 3 })
 *
 * Nothing here adds to the notation: a message is formatted with exactly the values the screen gives it, by name.
 * The English file names each message's values after its text, which is what gives the screens their types; the
 * other languages write the text alone (`m("{n, plural, one {# pagina} other {# pagina''s}}")`), and a test holds
 * them to the same values as English. `.text` and `.params` are for the tests and for the export to translators.
 *
 * What a screen does, so that a message never has to:
 * - It chooses between two messages when a value may be missing (`statusCaseClosed`, `statusCaseClosedOn`).
 * - It gives a list as text (`listOf`, `listAnd` in lib/lists.ts: the language's own rules, from the browser) and
 *   how many items it has as a value of its own, for the plural.
 *
 * In the text: a quantity is `#` inside its plural or `{n, number}`, so each language groups and separates it its
 * own way ("1,234", "1.234", "1 234"); a number that names something (a page, a source, a year) is `{page}` and
 * shows as it is. An apostrophe is doubled before `{` (`l''{name}`): a single one would start a quotation.
 * The plural and number rules are CLDR's, from the browser; nothing is fetched.
 */
import { IntlMessageFormat } from "intl-messageformat";

/** A value for a message: text, a number, or a yes/no to choose by (`{before, select, true {…} other {…}}`). */
export type Value = string | number | boolean;
/** A message: what a screen calls with its values by name, and its text and value names for tests and tools. */
export interface Message<K extends string = string> {
  (values: Record<K, Value>): string;
  /** The same sentence in pieces, for a value the screen draws itself (a name in bold): text, and that value where
   *  the language puts it. The sentence stays whole for the translator; only its look is the screen's. */
  parts<T extends object>(values: Record<K, Value | T>): (string | T)[];
  readonly text: string;
  readonly params: readonly string[];
}

/** The names of the values a message's text uses (`{name}`, `{name, plural, …}`), read from its parsed form. */
export function namesIn(text: string): string[] {
  type Node = { type: number; value?: string; options?: Record<string, { value: Node[] }>; children?: Node[] };
  const names = new Set<string>();
  const walk = (nodes: Node[]) => {
    for (const node of nodes) {
      // 0 is plain text, 7 the "#" of a plural and 8 a tag; every other kind names a value
      if (node.type !== 0 && node.type !== 7 && node.type !== 8 && node.value) names.add(node.value);
      for (const option of Object.values(node.options ?? {})) walk(option.value);
      if (node.children) walk(node.children);
    }
  };
  walk(new IntlMessageFormat(text, "en", undefined, { ignoreTag: true }).getAst() as unknown as Node[]);
  return [...names];
}

/** `m` for one language: its messages are formatted with that language's plural, number and date rules. */
export function messagesIn(locale: string) {
  /** A message in ICU MessageFormat. English names its values (`m("…", "n", "file")`); the other languages don't. */
  function m<const N extends readonly string[]>(text: string, ...names: N): Message<N[number]> {
    let made: IntlMessageFormat | undefined;
    let read: readonly string[] | undefined;  // read from the text when first needed: a table of messages costs nothing to load
    const params = () => (read ??= names.length ? names : namesIn(text));
    // a value that isn't given shows as nothing rather than stopping the screen; the types and the tests catch it first
    const all = (values: Record<string, unknown>) => Object.fromEntries(params().map((name) => [name, values?.[name] ?? ""])) as Record<string, string | number>;
    // ignoreTag: "<" and ">" in a sentence are just characters
    const format = () => (made ??= new IntlMessageFormat(text, locale, undefined, { ignoreTag: true }));
    const f = (values: Record<string, Value>) => String(format().format(all(values)));
    const parts = (values: Record<string, unknown>) => format().formatToParts(all(values)).map((part) => part.value);
    return Object.defineProperties(f, { text: { value: text }, params: { get: params }, parts: { value: parts } }) as unknown as Message<N[number]>;
  }
  return { m };
}

/** What a translator is told about an entry: where it appears and what its values stand for; with `max`, how many
 *  characters a label may have in any language (a test holds every language to it). English-only: the notes are
 *  for the person translating from English, and travel with the export (suveryn-tracker#148). */
export type Note = string | { note: string; max: number };
/** Notes for a language table: by the same keys, for as many entries as need one; a table can have one for all of it. */
export type Notes<T> = { [K in keyof T]?: T[K] extends string | ((values: never) => string) ? Note : Notes<T[K]> | Note };
