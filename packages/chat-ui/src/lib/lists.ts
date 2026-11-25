/**
 * A list as the reader's language says it, for a value in a message (i18n/message.ts): the screen gives the list as
 * text and, beside it, how many items it has, for the plural. The rules are CLDR's (`list` in i18n/format.ts);
 * nothing here knows a language's word for "and".
 */
import { locale, localeOf } from "../i18n";
import { list } from "../i18n/format";

/** "2", "2 and 3", "2, 3 and 5"; "2, 3 en 5"; "2, 3 et 5". In the language of ``table`` when the text is written from
 *  one (an export in another language than the screen's), else in the current language. */
export const listAnd = (items: readonly (string | number)[], table?: object): string =>
  list(items, (table && localeOf(table)) || locale());

/** A list of pages as a message takes it: the pages as text, and how many there are. */
export const pagesOf = (pages: readonly number[], table?: object) => ({ pages: listAnd(pages, table), count: pages.length });
