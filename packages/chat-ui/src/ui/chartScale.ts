/**
 * The arithmetic behind the charts (suveryn-tracker#46), kept apart from the components so it can be
 * tested on its own. d3-array gives the "nice" round numbers for the axis (0, 5k, 10k, 15k rather
 * than 0, 4.3k, 8.6k, 12.9k); everything else is a share of that maximum.
 */
import { nice, ticks } from "d3-array";

/** The axis for counts from 0 to `max`: a round top and about `count` round steps up to it, in
 *  whole numbers (no "0.5 tokens" on a small axis). */
export function valueAxis(max: number, count = 4): { top: number; ticks: number[] } {
  if (!(max > 0)) return { top: 1, ticks: [0] };
  const [, top] = nice(0, max, count);
  return { top, ticks: ticks(0, top, count).filter(Number.isInteger) };
}

/** `value` as a percentage of `top`, between 0 and 100. */
export const share = (value: number, top: number) => (top > 0 ? Math.min(100, Math.max(0, (value / top) * 100)) : 0);

export const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);

/** The index the arrow, Home and End keys move to in a row of `length` items; null for other keys. */
export function step(key: string, index: number, length: number, axis: "horizontal" | "vertical"): number | null {
  const [back, forward] = axis === "horizontal" ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
  if (key === back) return Math.max(0, index - 1);
  if (key === forward) return Math.min(length - 1, index + 1);
  if (key === "Home") return 0;
  if (key === "End") return length - 1;
  return null;
}

/**
 * The columns that get a label on the time axis, at most `max`. With `slots` (each column's place on
 * a regular clock: its hour of the day, its day counted from a Monday, …) and the intervals that read
 * well for it (every 3 or 6 hours; every 7 days), the labels fall on round times: 00:00, 06:00, 12:00
 * rather than 13:00, 18:00, 23:00. Without, or when none fits, evenly spaced from the first column.
 */
export function marks(length: number, max = 8, slots?: number[], every?: number[]): number[] {
  if (length <= 0) return [];
  if (slots && every) {
    for (const e of every) {
      const at = slots.flatMap((s, i) => (((s % e) + e) % e === 0 ? [i] : []));
      if (at.length > 0 && at.length <= max) return at;
    }
  }
  const step = Math.max(1, Math.ceil(length / max));
  return Array.from({ length: Math.ceil(length / step) }, (_, i) => i * step);
}
