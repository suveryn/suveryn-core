/**
 * Whether a count takes the singular form, by the language's own plural rules (CLDR, built into
 * the browser as Intl.PluralRules), never by `n === 1` (suveryn-tracker#117). French takes the
 * singular for 0 and 1 ("0 page"), English and Dutch for 1 only ("0 pages", "0 pagina's").
 *
 * Every language in LANGS has two forms, singular and plural. A language with more (Polish's
 * "few" and "many", say) needs a helper that returns the category instead; docs/translations.md.
 */
export function singularIn(locale: string): (n: number) => boolean {
  const rules = new Intl.PluralRules(locale);
  return (n) => rules.select(n) === "one";
}
