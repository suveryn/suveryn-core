/**
 * Charts (suveryn-tracker#46): the axis arithmetic, the keyboard steps, and the colour rules in
 * ui.css (each series 3:1 against the backgrounds and against the other, so they tell apart in
 * greyscale too).
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { marks, share, step, sum, valueAxis } from "./chartScale";

describe("the value axis", () => {
  it("rounds the top up and steps in round numbers", () => {
    expect(valueAxis(12_900)).toEqual({ top: 15_000, ticks: [0, 5_000, 10_000, 15_000] });
    expect(valueAxis(1_000)).toEqual({ top: 1_000, ticks: [0, 200, 400, 600, 800, 1_000] });
    expect(valueAxis(7)).toEqual({ top: 8, ticks: [0, 2, 4, 6, 8] });
    expect(valueAxis(1)).toEqual({ top: 1, ticks: [0, 1] });
  });

  it("has an axis without values", () => {
    expect(valueAxis(0)).toEqual({ top: 1, ticks: [0] });
    expect(valueAxis(Number.NaN)).toEqual({ top: 1, ticks: [0] });
  });

  it("keeps every value on the axis", () => {
    for (const max of [1, 3, 99, 101, 4_321, 987_654, 12_345_678]) {
      const { top, ticks } = valueAxis(max);
      expect(top).toBeGreaterThanOrEqual(max);
      expect(ticks[0]).toBe(0);
      expect(ticks.at(-1)).toBeLessThanOrEqual(top);
    }
  });

  it("gives shares between 0 and 100", () => {
    expect(share(50, 200)).toBe(25);
    expect(share(300, 200)).toBe(100);
    expect(share(-1, 200)).toBe(0);
    expect(share(5, 0)).toBe(0);
    expect(sum([1, 2, 3])).toBe(6);
  });
});

describe("the time axis", () => {
  it("spaces labels evenly from the first column without a clock", () => {
    expect(marks(24)).toEqual([0, 3, 6, 9, 12, 15, 18, 21]);
    expect(marks(31)).toEqual([0, 4, 8, 12, 16, 20, 24, 28]);
    expect(marks(4)).toEqual([0, 1, 2, 3]);
    expect(marks(0)).toEqual([]);
  });

  it("puts labels on round times with one", () => {
    // 25 hourly columns from 13:00: every 3 hours, on 15:00, 18:00, … 12:00.
    const hours = Array.from({ length: 25 }, (_, i) => (13 + i) % 24);
    expect(marks(25, 8, hours, [1, 2, 3, 6, 12]).map((i) => hours[i])).toEqual([15, 18, 21, 0, 3, 6, 9, 12]);
    // 31 days, counted from a Monday: every 7 days, on the Mondays.
    const days = Array.from({ length: 31 }, (_, i) => 9_400 + i);
    expect(marks(31, 8, days, [1, 2, 7, 14]).every((i) => days[i] % 7 === 0)).toBe(true);
    // Fewer labels at phone width are the same marks, every other one hidden by ui.css.
    expect(marks(12, 8, Array.from({ length: 12 }, (_, i) => i), [1, 3, 6, 12])).toEqual([0, 3, 6, 9]);
  });

  it("falls back to even spacing when no interval fits", () => {
    expect(marks(40, 8, Array.from({ length: 40 }, (_, i) => i), [1, 2])).toEqual([0, 5, 10, 15, 20, 25, 30, 35]);
  });
});

describe("moving between columns with the keyboard", () => {
  it("steps with the arrows of its direction, and jumps with Home and End", () => {
    expect(step("ArrowRight", 2, 5, "horizontal")).toBe(3);
    expect(step("ArrowLeft", 0, 5, "horizontal")).toBe(0);
    expect(step("ArrowRight", 4, 5, "horizontal")).toBe(4);
    expect(step("ArrowDown", 1, 5, "vertical")).toBe(2);
    expect(step("Home", 3, 5, "horizontal")).toBe(0);
    expect(step("End", 0, 5, "horizontal")).toBe(4);
    expect(step("ArrowDown", 1, 5, "horizontal")).toBeNull();
    expect(step("Enter", 1, 5, "horizontal")).toBeNull();
  });
});

describe("chart colours (ui.css)", () => {
  const tokens = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");
  const ui = readFileSync(new URL("./ui.css", import.meta.url), "utf8");
  const value = (css: string, name: string) => css.match(new RegExp(`--${name}:\\s*([^;]+);`))?.[1].trim();
  /** A colour token to its hex value, following var() through tokens.css. */
  const hex = (name: string): string => {
    const v = value(ui, name) ?? value(tokens, name);
    if (!v) throw new Error(`--${name} not found`);
    const ref = v.match(/^var\(--([\w-]+)\)$/);
    return ref ? hex(ref[1]) : v;
  };
  const luminance = (h: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a: string, b: string) => {
    const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };

  it("are opaque hex colours", () => {
    for (const n of ["chart-1", "chart-2", "bg", "surface"]) expect(hex(n), n).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it("stand out 3:1 against the page and the cards", () => {
    for (const s of ["chart-1", "chart-2"]) {
      for (const bg of ["bg", "surface", "surface-alt"]) expect(contrast(hex(s), hex(bg)), `${s} on ${bg}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("tell apart from each other without colour", () => {
    expect(contrast(hex("chart-1"), hex("chart-2"))).toBeGreaterThanOrEqual(3);
  });

  it("are given to every series the charts draw", () => {
    for (const i of [0, 1]) expect(ui).toContain(`.ui-chart [data-series="${i}"] { background: var(--chart-${i + 1}); }`);
  });
});
