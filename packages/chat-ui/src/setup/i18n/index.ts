/**
 * The web setup's text (suveryn-tracker#37): one table per language (en.ts, nl.ts, fr.ts), on the
 * same language list and current choice as the chat (src/i18n/languages.ts). The setup starts from
 * the language chosen at installation (``initialLang`` with the appliance's answer). How to add a
 * language: docs/translations.md.
 */
import type { Lang } from "../../i18n/languages";
import { useLang } from "../../i18n/languages";
import en, { type Text } from "./en";
import fr from "./fr";
import nl from "./nl";

export { initialLang, lang, LANGS, LANGUAGE_NAMES, LOCALES, pickLang, setLang, useLang, type Lang } from "../../i18n/languages";
export type { Text };

/** Every language's table: TypeScript refuses to build when one is missing or incomplete. */
export const TEXT: Record<Lang, Text> = { en, nl, fr };

/** The current language's text; the component re-renders when the language changes. */
export function useText(): Text {
  return TEXT[useLang()];
}
