/**
 * The screen previews (README, "Screen previews") are for development: never a build input, and each
 * one names its design board.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const ROOT = new URL("../..", import.meta.url);

describe("screen previews", () => {
  it("are not shipped: preview.html is not a build input", () => {
    const config = readFileSync(new URL("vite.config.ts", ROOT), "utf8");
    const input = config.match(/input:\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(input).toContain("index.html");
    expect(input).not.toContain("preview");
  });

  it("each preview has a unique id and names a design board", () => {
    const source = readFileSync(new URL("src/preview/previews.tsx", ROOT), "utf8");
    const entries = [...source.matchAll(/\{ id: "([a-z0-9-]+)", board: "([A-Z]\d{2})"/g)];
    expect(entries.length).toBeGreaterThan(0);
    const ids = entries.map((e) => e[1]);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
