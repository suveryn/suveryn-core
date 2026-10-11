import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./app.css", import.meta.url), "utf8");
const rule = (selector: string) => css.match(new RegExp(`^${selector.replace(".", "\\.")} \\{([^}]*)\\}`, "m"))?.[1] ?? "";

describe("layout (suveryn-tracker#23)", () => {
  it("only the conversation scrolls, never the page: one row as high as the window", () => {
    expect(rule(".app")).toMatch(/grid-template-rows:\s*minmax\(0,\s*1fr\)/);
    expect(rule(".app")).toMatch(/overflow:\s*hidden/);
    expect(rule(".main")).toMatch(/min-height:\s*0/);
    expect(rule(".conversation")).toMatch(/min-height:\s*0/);
    expect(rule(".conversation")).toMatch(/overflow-y:\s*auto/);
  });
});
