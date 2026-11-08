/**
 * Spacing on a 4 px grid (suveryn-brand's guidelines, "Spacing: a 4 px grid"; the handbook's decision of
 * 8 November 2026): every margin, padding, gap, offset and size in the stylesheets is a multiple of 4 px.
 * Allowed off the grid: 1 to 3 px (a line, an optical nudge), and a padding one less than a step (7, 11,
 * 15 px) where a 1 px border makes up the rest. Font sizes, line heights, radii, borders and shadows aren't
 * spacing and aren't checked here; media queries neither.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const FILES = ["../ui/ui.css", "./app.css", "../setup/setup.css", "../preview/preview.css"];
const PROP = /(?<![\w-])(margin(?:-[a-z-]+)?|padding(?:-[a-z-]+)?|gap|row-gap|column-gap|top|right|bottom|left|inset|width|height|min-width|max-width|min-height|max-height|flex-basis)\s*:([^;{}]*)/g;

export function offGrid(css: string): string[] {
  const found: string[] = [];
  for (const line of css.split("\n")) {
    if (/@media|@container/.test(line)) continue;
    for (const [, prop, value] of line.matchAll(PROP)) {
      for (const [, n] of value.matchAll(/(?<![\w.-])(\d+(?:\.\d+)?)px/g)) {
        const px = Number(n);
        const ok = px <= 3 || px % 4 === 0 || (prop.startsWith("padding") && px % 4 === 3);
        if (!ok) found.push(`${prop}: ${n}px`);
      }
    }
  }
  return found;
}

describe("spacing on a 4 px grid", () => {
  for (const file of FILES) {
    it(file.replace(/^\.\.?\//, ""), () => {
      expect(offGrid(readFileSync(new URL(file, import.meta.url), "utf8"))).toEqual([]);
    });
  }
  it("names what is off the grid", () => {
    expect(offGrid(".a { padding: 11px 14px; gap: 6px; margin-top: 2px; border: 1px solid; }")).toEqual(["padding: 14px", "gap: 6px"]);
  });
});
