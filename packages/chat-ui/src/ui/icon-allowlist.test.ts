/**
 * The rule in claude/ui-components.md: icons come from one set, lucide-react, listed whole in
 * allowedIcons.ts (`npm run icons:sync`). This fails when a file imports a lucide-react name that
 * isn't on that list (an older alias: use lucide's own name, so one icon has one name everywhere),
 * and when the list no longer matches the installed lucide-react.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { icons } from "lucide-react";
import { describe, expect, it } from "vitest";
import { ALLOWED_ICONS } from "./allowedIcons";

const SRC = new URL("..", import.meta.url).pathname;
const ALLOWED = new Set<string>(ALLOWED_ICONS);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

// `import { A, B as C } from "lucide-react"` — the `s` flag lets this match across lines, since
// prettier wraps a long import list onto several.
const IMPORT = /import\s*\{([^}]+)\}\s*from\s*["']lucide-react["']/gs;

describe("icon usage (claude/ui-components.md)", () => {
  it("every lucide-react icon used in the product is on the allowlist", () => {
    const offenders: string[] = [];
    for (const file of sources(SRC)) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(IMPORT)) {
        const names = match[1]
          .split(",")
          .map((n) => n.trim().split(/\s+as\s+/)[0].trim())
          .filter(Boolean);
        for (const name of names) {
          if (!ALLOWED.has(name)) offenders.push(`${relative(SRC, file)}: ${name}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("the allowlist is every icon in the installed lucide-react (npm run icons:sync)", () => {
    expect([...ALLOWED_ICONS]).toEqual(Object.keys(icons).sort());
  });

  it("the allowlist has no duplicate entries", () => {
    expect(new Set(ALLOWED_ICONS).size).toBe(ALLOWED_ICONS.length);
  });
});
