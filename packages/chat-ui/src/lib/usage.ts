/**
 * Time ranges and number formats for the usage views (suveryn-tracker#7). Ranges are rolling
 * (the last hour, day, week or month); a custom range covers whole local days.
 */
import { locale } from "../i18n";

export type Preset = "hour" | "day" | "week" | "month" | "custom";
export const PRESETS: Preset[] = ["hour", "day", "week", "month", "custom"];

const HOUR = 3_600_000;
const SPAN: Record<Exclude<Preset, "custom">, number> = { hour: HOUR, day: 24 * HOUR, week: 7 * 24 * HOUR, month: 30 * 24 * HOUR };

/**
 * The range a preset means now; for "custom", from the start of `from` to the end of `to` (local
 * dates, YYYY-MM-DD). Presets have no end: they run until the server's "now".
 */
export function rangeFor(preset: Preset, now: Date, from?: string, to?: string): { start: Date; end?: Date } | null {
  if (preset !== "custom") return { start: new Date(now.getTime() - SPAN[preset]) };
  if (!from || !to) return null;
  const start = localDay(from), last = localDay(to);
  if (!start || !last || last < start) return null;
  return { start, end: new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1) };
}

function localDay(value: string): Date | null {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/** Today from local midnight (until the server's "now"): the sidebar counter's range. */
export const today = (now: Date) => ({ start: new Date(now.getFullYear(), now.getMonth(), now.getDate()) });

/** "1.2k", "34k", "1.5M" in the current language; exact below 1,000. */
export const compact = (n: number) => new Intl.NumberFormat(locale(), { notation: "compact", maximumFractionDigits: 1 }).format(n);
export const whole = (n: number) => new Intl.NumberFormat(locale()).format(n);
export const money = (amount: string | number, currency: string) =>
  new Intl.NumberFormat(locale(), { style: "currency", currency }).format(Number(amount));

/** A bucket's label for its step: a time for minutes, weekday and time for hours (a range can span two days), a date otherwise. */
export function bucketLabel(iso: string, step: string): string {
  const d = new Date(iso);
  if (step === "5 minutes") return d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (step === "1 hour") return d.toLocaleString(locale(), { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString(locale(), { day: "numeric", month: "short" });
}
