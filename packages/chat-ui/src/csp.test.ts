/**
 * The source keeps to the appliance's Content-Security-Policy (style-src 'self', script-src 'self',
 * no data:, no other host). The rules and the reasons: docs/content-security-policy.md. This checks
 * what can be seen in the source; the browser check (docs/spikes/react-aria) counts real violations.
 */
import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = new URL("..", import.meta.url).pathname;

function files(dir: string, ext: RegExp): string[] {
  return readdirSync(join(ROOT, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name), ext) : ext.test(e.name) ? [join(dir, e.name)] : []);
}
const read = (f: string) => readFileSync(join(ROOT, f), "utf8");
/** Code without its comments, so a rule may be explained in a comment. */
const code = (f: string) => read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

const sources = files("src", /\.(ts|tsx)$/).filter((f) => !f.endsWith(".test.ts"));
const styles = files("src", /\.css$/);
const pages = ["index.html", "setup.html"];

describe("the Content-Security-Policy (docs/content-security-policy.md)", () => {
  it("writes no <style> element, stylesheet rule or markup into the page", () => {
    for (const f of sources) {
      const c = code(f);
      expect(c, f).not.toMatch(/createElement\(\s*["'`]style["'`]/);
      expect(c, f).not.toMatch(/\binsertRule\b|\badoptedStyleSheets\b/);
      expect(c, f).not.toMatch(/dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML/);
    }
  });

  it("runs no code from strings", () => {
    for (const f of sources) expect(code(f), f).not.toMatch(/\beval\(|new Function\(|set(?:Timeout|Interval)\(\s*["'`]/);
  });

  it("loads nothing from another host and inlines nothing as data: URLs", () => {
    for (const f of sources) {
      const c = code(f);
      expect(c, f).not.toMatch(/fetch\(\s*["'`]https?:|new URL\(\s*["'`]https?:|["'`]data:[a-z]+\//);
    }
    for (const f of styles) {
      const urls = [...code(f).matchAll(/url\(\s*["']?([^"')]+)/g)].map((m) => m[1]);
      for (const u of urls) expect(u, f).not.toMatch(/^(https?:|\/\/|data:)/);
      expect(code(f), f).not.toMatch(/@import\s+["']?(https?:|\/\/)/);
    }
  });

  it("has HTML entry pages with no inline script, style or event handler", () => {
    for (const f of pages) {
      const h = read(f);
      expect(h, f).not.toMatch(/<style[\s>]/i);
      expect(h, f).not.toMatch(/\sstyle=/i);
      expect(h, f).not.toMatch(/\son[a-z]+=/i);
      for (const s of h.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
        expect(s[1], f).toMatch(/\bsrc=/);
        expect(s[2].trim(), f).toBe("");
      }
    }
  });

  it("keeps Vite from inlining assets as data: URLs", () => {
    expect(read("vite.config.ts")).toMatch(/assetsInlineLimit:\s*0/);
  });

  it("pre-empts React Aria's pressable <style> by the id it checks, and carries its rule (exception 1)", async () => {
    const require = createRequire(import.meta.url);
    const usePress = readFileSync(join(dirname(require.resolve("react-aria/package.json")),
                                       "dist/private/interactions/usePress.mjs"), "utf8");
    const { PRESSABLE_STYLE_ID } = await import("./ui/csp");
    expect(usePress, "React Aria's id for its pressable style changed: update src/ui/csp.ts")
      .toContain(`STYLE_ID = '${PRESSABLE_STYLE_ID}'`);
    expect(usePress, "React Aria still skips the style when that id exists").toMatch(/getElementById\([^)]*STYLE_ID\)\) return;/);
    expect(usePress, "React Aria's pressable rule changed: update src/ui/ui.css").toMatch(/touch-action: pan-x pan-y pinch-zoom;/);
    expect(usePress.match(/createElement\('style'\)/g)?.length, "React Aria writes another <style> in usePress").toBe(1);
  });

  it("knows every place React Aria writes styling at run time", () => {
    // A React Aria update that adds one fails here: check it under the CSP before using it
    // (docs/content-security-policy.md, "Adding a library").
    const require = createRequire(import.meta.url);
    const writers: string[] = [];
    for (const pkg of ["react-aria", "react-aria-components", "react-stately"]) {
      const dir = join(dirname(require.resolve(`${pkg}/package.json`)), "dist");
      const walk = (d: string): void => readdirSync(d, { withFileTypes: true }).forEach((e) => {
        const f = join(d, e.name);
        if (e.isDirectory()) walk(f);
        else if (f.endsWith(".mjs") && /createElement\(['"]style['"]\)|\binsertRule\b|\badoptedStyleSheets\b/.test(readFileSync(f, "utf8"))) {
          writers.push(`${pkg}/${f.slice(dir.length + 1)}`);
        }
      });
      walk(dir);
    }
    expect(writers.sort()).toEqual([
      "react-aria-components/private/TokenField.mjs",            // not used by sūveryn (see below)
      "react-aria/private/interactions/usePress.mjs",            // exception 1: src/ui/csp.ts
      "react-aria/private/overlays/usePreventScroll.mjs",        // exception 2: vite.config.ts
    ]);
    // TokenField adds a constructed stylesheet; it isn't handled, so it isn't used.
    for (const f of sources) expect(code(f), f).not.toMatch(/\bTokenField\b/);
  });

  it("keeps the React Aria workaround imported for its effect", () => {
    expect(read("src/ui/index.ts")).toMatch(/^import "\.\/csp";$/m);
    expect(JSON.parse(read("package.json")).sideEffects, "sideEffects would let the bundler drop src/ui/csp.ts").toBeUndefined();
  });
});
