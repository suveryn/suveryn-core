/**
 * The rule of the component library (README, "Components"): product screens use only src/ui, never
 * React Aria directly, so one place decides how every control looks and behaves. This test fails
 * when a screen imports react-aria, react-aria-components or react-stately.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = new URL("..", import.meta.url).pathname;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("component library (suveryn-tracker#44)", () => {
  it("no product screen imports React Aria; only src/ui does", () => {
    const offenders = sources(SRC)
      .filter((f) => !relative(SRC, f).startsWith("ui/"))
      .filter((f) => /from\s+["'](react-aria|react-aria-components|react-stately)["']/.test(readFileSync(f, "utf8")))
      .map((f) => relative(SRC, f));
    expect(offenders).toEqual([]);
  });
});
