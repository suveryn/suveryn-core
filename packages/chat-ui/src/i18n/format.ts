/**
 * Every date, time, number and list the screens and the files they make show, in one place (suveryn-tracker#129; the
 * handbook's decision "Meaning on the server, words at the edge", rule 3). Each format has a name, and the language's
 * own rules come from the browser's `Intl` (CLDR): nothing here knows a month's name, a decimal separator or a
 * language's word for "and". Nothing else in the chat UI calls `Intl` or `toLocale…` to format (`format.test.ts`).
 *
 * Each takes the locale it is written in, by default the interface's (`locale()`); a file written in its document's
 * language, or the web setup with its own language, passes its own.
 */
import { lang, LOCALES } from "./languages";

const current = (): string => LOCALES[lang()];

type When = Date | string | number;
const at = (w: When): Date => (w instanceof Date ? w : new Date(w));
const dates = (options: Intl.DateTimeFormatOptions) => (w: When, l: string = current()): string =>
  new Intl.DateTimeFormat(l, options).format(at(w));

/** "5 Nov" (nl "5 nov", fr "5 nov."). */
export const day = dates({ day: "numeric", month: "short" });
/** "5 November" (nl "5 november", fr "5 novembre"). */
export const dayLong = dates({ day: "numeric", month: "long" });
/** "5 Nov 2026". */
export const dayInYear = dates({ day: "numeric", month: "short", year: "numeric" });
/** "5 November 2026" (nl "5 november 2026", fr "5 novembre 2026"). */
export const date = dates({ day: "numeric", month: "long", year: "numeric" });
/** "05/11/2026" (nl "5/11/2026"): the date in digits, as the language writes it. */
export const dateInDigits = dates({});
/** "05/11/2026" in every language that writes days first: two digits each, for a line that must keep its width. */
export const dateInTwoDigits = dates({ day: "2-digit", month: "2-digit", year: "numeric" });
/** "09:07". */
export const time = dates({ hour: "2-digit", minute: "2-digit" });
/** "09:07:42". */
export const timeWithSeconds = dates({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
/** "Thu 09:07". */
export const weekdayAndTime = dates({ weekday: "short", hour: "2-digit", minute: "2-digit" });
/** "5 Nov 2026, 09:07". */
export const dayAndTime = dates({ dateStyle: "medium", timeStyle: "short" });
/** "5 November 2026 at 09:07". */
export const dateAndTime = dates({ dateStyle: "long", timeStyle: "short" });

/** Whether two moments fall in the same calendar year, here: a date this year leaves its year out. */
export const sameYear = (a: When, b: When): boolean => at(a).getFullYear() === at(b).getFullYear();

/** "1,234.5" (nl "1.234,5"): at most `most` decimals (3), as many as the number has up to that, and at least `least`
 *  (0): "1.50" with both 2. */
export const number = (n: number, { most = 3, least = 0 }: { most?: number; least?: number } = {}, l: string = current()): string =>
  new Intl.NumberFormat(l, { minimumFractionDigits: least, maximumFractionDigits: Math.max(most, least) }).format(n);
/** "1,234" (nl "1.234"): a count, as the language writes it. */
export const whole = (n: number, l: string = current()): string => new Intl.NumberFormat(l).format(n);
/** "1.2k", "34k", "1.5M" (nl "1,2K", fr "1,2 k"): short, for an axis or a tile; exact below 1,000. */
export const compact = (n: number, l: string = current()): string =>
  new Intl.NumberFormat(l, { notation: "compact", maximumFractionDigits: 1 }).format(n);
/** "€1,234.50" (nl "€ 1.234,50", fr "1 234,50 €"): an amount in its currency. */
export const amount = (n: number | string, currency: string, l: string = current()): string =>
  new Intl.NumberFormat(l, { style: "currency", currency }).format(Number(n));

const UNITS = ["kilobyte", "megabyte", "gigabyte", "terabyte"] as const;
/** "1.2 GB", "340 MB" (fr "1,2 Go", "340 Mo"): a size in decimal units, as disks are sold, from kilobytes; one
 *  decimal below 10. */
export function bytes(n: number, l: string = current()): string {
  let i = 0;
  n /= 1000;  // from kilobytes: "0 kB", never "999 byte"
  while (n >= 1000 && i < UNITS.length - 1) { n /= 1000; i++; }
  return new Intl.NumberFormat(l, { style: "unit", unit: UNITS[i], unitDisplay: "short",
                                    maximumFractionDigits: n < 10 ? 1 : 0 }).format(n);
}

/** "2", "2 and 3", "2, 3 and 5" (nl "2, 3 en 5", fr "2, 3 et 5"). */
export const list = (items: readonly (string | number)[], l: string = current()): string =>
  new Intl.ListFormat(l, { type: "conjunction" }).format(items.map(String));
/** A list without "and", as a set of values reads ("Input tokens 1,200, Output tokens 300"). */
export const unitList = (items: readonly (string | number)[], l: string = current()): string =>
  new Intl.ListFormat(l, { type: "unit" }).format(items.map(String));
