import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import lock from "./brand-lock.json";

// The brand files and tokens.css are copies from suveryn-brand (scripts/brand-sync.mjs). Editing one
// by hand makes it drift from the brand; change suveryn-brand instead and run `npm run brand:sync`.
describe("brand files", () => {
  for (const [path, hash] of Object.entries(lock.files)) {
    it(`${path} matches suveryn-brand@${lock.commit.slice(0, 7)}`, () => {
      expect(createHash("sha256").update(readFileSync(path)).digest("hex")).toBe(hash);
    });
  }
});

// The type scale (tokens v3.2): a stylesheet names a style (font-size: var(--text-ui-sm)), never a
// pixel size of its own, so the product can't drift from the brand's fourteen styles again.
describe("the type scale", () => {
  const tokens = readFileSync("src/styles/tokens.css", "utf8");
  const typeSection = tokens.slice(tokens.indexOf("/* type"), tokens.indexOf("/* spacing"));  // --text-dim is a colour
  const styles = new Set([...typeSection.matchAll(/--text-([\w-]+):/g)].map((m) => m[1]));
  const sheets = ["src/styles/app.css", "src/ui/ui.css", "src/setup/setup.css"];
  const allowed = new Set(["26px"]);  // the setup page's wordmark below 480px (the brand's wordmark-lg usage note)

  it("names fourteen styles", () => {
    expect([...styles].sort()).toEqual(["body", "body-sm", "caption", "control", "h1", "h2", "h3", "label", "subtitle", "title",
                                        "ui", "ui-sm", "wordmark", "wordmark-lg"]);
  });

  for (const sheet of sheets) {
    it(`${sheet} uses the scale, not pixel sizes`, () => {
      const css = readFileSync(sheet, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      const literal = [...css.matchAll(/font-size:\s*([0-9.]+px)/g)].map((m) => m[1]).filter((px) => !allowed.has(px));
      expect(literal).toEqual([]);
      const used = [...css.matchAll(/font-size:\s*var\(--text-([\w-]+)\)/g)].map((m) => m[1]);
      expect(used.filter((s) => !styles.has(s))).toEqual([]);
    });
  }
});
