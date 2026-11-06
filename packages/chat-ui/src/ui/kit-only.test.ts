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

  it("no screen lays out a dialog's buttons itself: Dialog takes them by role (docs/design/chat-ui.md, \"Dialogs\")", () => {
    const screens = sources(SRC).filter((f) => !relative(SRC, f).startsWith("ui/"));
    for (const f of screens) {
      const text = readFileSync(f, "utf8");
      const where = relative(SRC, f);
      expect(text, where).not.toMatch(/ui-dialog-actions/);
      // every <Dialog …> names its kind in its opening tag (read up to its first child or the end)
      for (const open of text.matchAll(/<Dialog\b[\s\S]{0,800}?(?:\}>|">|\n\s*<)/g)) {
        expect(open[0], where).toMatch(/\bkind="(confirmation|choice|form|information)"/);
      }
    }
  });

  it("TextButton has no danger variant (the brand has no danger colour)", () => {
    expect(readFileSync(join(SRC, "ui/Button.tsx"), "utf8")).not.toMatch(/danger\??:|data-danger/);
  });
});
