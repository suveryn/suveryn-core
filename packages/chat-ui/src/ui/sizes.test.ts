/**
 * Fields and buttons of one size are equally high, so that they line up side by side (ui.css,
 * "sizes"): 44px regular, 32px small. Worked out from the rules as written: line height, padding
 * and a 1px border top and bottom, and the min-height that holds it.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./ui.css", import.meta.url), "utf8");
/** The declarations of the rule whose selector is exactly `selector`. */
function rule(selector: string): Record<string, string> {
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule ${selector}`);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return Object.fromEntries(body.split(";").map((d) => d.split(":").map((x) => x.trim())).filter((d) => d.length === 2));
}
const px = (v: string) => Number(v.replace("px", ""));
/** Height from line height and vertical padding (`padding: 7px 10px` or `padding: 7px var(--…)`). */
const height = (r: Record<string, string>, base: Record<string, string> = {}) => {
  const all = { ...base, ...r };
  return px(all["line-height"]) + 2 * px(all.padding.split(" ")[0]) + 2;
};

describe("control sizes (ui.css)", () => {
  it("regular: fields and buttons are 44px", () => {
    expect(height(rule(".ui-input"))).toBe(44);
    expect(px(rule(".ui-input")["min-height"])).toBe(44);
    expect(px(rule(".ui-button")["min-height"])).toBe(44);
  });

  it("small: fields, buttons, the select and the period choice are 32px", () => {
    expect(height(rule('.ui-field[data-size="small"] .ui-input'))).toBe(32);
    expect(px(rule('.ui-field[data-size="small"] .ui-input')["min-height"])).toBe(32);
    expect(px(rule('.ui-button[data-size="small"]')["min-height"])).toBe(32);
    expect(height(rule(".ui-select-button"))).toBe(32);
    expect(height(rule(".ui-segment"))).toBe(32); // its 1px top and bottom are the group's border
  });
});
