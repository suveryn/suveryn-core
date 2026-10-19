/**
 * The chat UI's text (suveryn-tracker#8): one string table per language (en.ts, nl.ts, fr.ts), and
 * hooks that re-render on a change of language. Which languages exist, and which one is current, is
 * src/i18n/languages.ts, shared with the web setup; how to add a language: docs/translations.md.
 *
 * Model answers are in the language of the question, whatever the interface language. The sign-in
 * page is opened in the interface language (signIn passes it on).
 */
import en, { type Messages } from "./en";
import fr from "./fr";
import { lang, LOCALES, useLang, type Lang } from "./languages";
import nl from "./nl";

export { initialLang, lang, LANGS, LANGUAGE_NAMES, LOCALES, pickLang, setLang, useLang, type Lang } from "./languages";

/** Every language's table: TypeScript refuses to build when a language has no table, or a table
 *  misses a string of en.ts. */
const TABLES: Record<Lang, Messages> = { en, nl, fr };

/** The current language's strings, for code outside React components. */
export const t = (): Messages => TABLES[lang()];
/** Locale tag for dates and numbers in the current language. */
export const locale = (): string => LOCALES[lang()];

/** The current language's strings; the component re-renders when the language changes. */
export function useT(): Messages {
  return TABLES[useLang()];
}

export type { Messages };
/** Every language's table (tests compare them). */
export const TABLES_FOR_TESTS = TABLES;
