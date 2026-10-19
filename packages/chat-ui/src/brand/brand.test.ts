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

// Word files can't use CSS variables, so lib/office.ts writes the brand colours as hex. They must be the
// tokens' own colours (light theme), converted from OKLCH, a translucent one as it shows on white.
describe("the colours in Word and Excel files", () => {
  const tokens = readFileSync("src/styles/tokens.css", "utf8");
  const light = tokens.slice(0, tokens.indexOf("@media"));
  const token = (name: string) => light.match(new RegExp(`--${name}:\\s*oklch\\(([^)]+)\\)`))![1];
  const hex = (value: string) => {
    const [lch, alpha] = value.split("/").map((p) => p.trim());
    const [L, C, h] = lch.split(/\s+/).map(Number);
    const a = C * Math.cos((h * Math.PI) / 180), b = C * Math.sin((h * Math.PI) / 180);
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
          s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    const linear = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
                    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
    const o = alpha === undefined ? 1 : Number(alpha);
    return linear.map((x) => {
      const srgb = 255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055);
      return Math.round(Math.min(255, Math.max(0, srgb)) * o + 255 * (1 - o)).toString(16).padStart(2, "0");
    }).join("").toUpperCase();
  };

  it("are the tokens' colours", async () => {
    const { OFFICE_COLOURS } = await import("../lib/office");
    expect(OFFICE_COLOURS.accentInk).toBe(hex(token("accent-ink")));
    expect(OFFICE_COLOURS.textDimmer).toBe(hex(token("text-dimmer")));
  });
});
