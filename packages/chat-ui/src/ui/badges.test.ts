/**
 * Overlay icons (suveryn-brand guidelines, "Overlay icons", tokens v3.5): one rule for every badge.
 * Each host has its own size, offset and stroke from the badge tokens, never a share of the host;
 * the icon fills its box; no disc, ring or fill.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./ui.css", import.meta.url), "utf8");
const tokens = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");
const avatar = readFileSync(new URL("./avatar.tsx", import.meta.url), "utf8");

/** The declarations of the rule whose selector is exactly `selector`. */
function rule(selector: string): Record<string, string> {
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule ${selector}`);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return Object.fromEntries(body.split(";").map((d) => d.split(/:(.*)/s).slice(0, 2).map((x) => x.trim()))
    .filter((d) => d.length === 2 && d[0]));
}
/** Every rule whose selector mentions `.ui-badge`, as text. */
const badgeRules = [...css.matchAll(/([^{}]*\.ui-badge[^{}]*)\{([^}]*)\}/g)].map((m) => m[0]);

describe("overlay icons (ui.css, tokens v3.5)", () => {
  it("tokens.css has size, offset and stroke for each of the five badge tokens", () => {
    for (const name of ["badge-icon", "badge-avatar-sm", "badge-avatar", "badge-avatar-lg", "badge-avatar-xl"]) {
      for (const suffix of ["", "-offset", "-stroke"]) expect(tokens).toMatch(new RegExp(`--${name}${suffix}: `));
    }
  });

  it("the badge takes its size, offset and stroke from the tokens, and no percentage or calc", () => {
    const b = rule(".ui-badge");
    expect(b.width).toBe("var(--badge)");
    expect(b.height).toBe("var(--badge)");
    expect(b.right).toBe("var(--badge-offset)");
    expect(b.bottom).toBe("var(--badge-offset)");
    expect(b["--badge"]).toBe("var(--badge-icon)");
    expect(rule(".ui-badge svg")["stroke-width"]).toBe("var(--badge-stroke)");
    for (const r of badgeRules) {
      if (!/\.ui-badge svg \{/.test(r)) expect(r).not.toMatch(/\d%|calc\(/); // a share of the host, as before v3.5
      expect(r).not.toMatch(/background|box-shadow|border-radius/);
    }
  });

  it("the icon fills its box", () => {
    expect(rule(".ui-badge svg").width).toBe("100%");
    expect(rule(".ui-badge svg").height).toBe("100%");
  });

  it("each Avatar size maps to its own step", () => {
    const steps = { small: "badge-avatar-sm", normal: "badge-avatar", large: "badge-avatar-lg", huge: "badge-avatar-xl" };
    for (const [size, token] of Object.entries(steps)) {
      const r = rule(`.ui-badge[data-host="${size}"]`);
      expect(r["--badge"]).toBe(`var(--${token})`);
      expect(r["--badge-offset"]).toBe(`var(--${token}-offset)`);
      expect(r["--badge-stroke"]).toBe(`var(--${token}-stroke)`);
    }
    expect(avatar).toContain('data-host={size} data-tone="role"'); // the administrator's shield follows the avatar's size
  });

  it("colour by meaning: ink for a role, teal-ink when the system signals something", () => {
    expect(rule(".ui-badge").color).toBe("var(--text)");
    expect(rule('.ui-badge[data-tone="system"]').color).toBe("var(--teal-ink)");
  });
});
