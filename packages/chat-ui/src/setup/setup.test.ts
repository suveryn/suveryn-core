import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { PREVENT_SCROLL_STYLE, reactAriaCsp } from "../../vite.config";
import { checkAdministrator, isCommonPassword } from "./administrator";
import { copyProblems, strings } from "../i18n/rules";
import { LANGS, pickLang, TEXT } from "./i18n";

const en = TEXT.en;
const ok = { name: "Filip Tack", email: "filip@firm.example", password: "correct horse battery", confirm: "correct horse battery" };

const keysOf = (v: unknown, path = ""): string[] =>
  v && typeof v === "object" && !Array.isArray(v)
    ? Object.entries(v).flatMap(([k, x]) => [`${path}.${k}`, ...keysOf(x, `${path}.${k}`)]) : [];
/** Defaults that fit the setup's functions (counts, days, names). */
const SAMPLES_FOR = (fns: string[]) => Object.fromEntries(fns.map((k) => [k, [[1, 6, "x"], [365, 2, "y"]]]));

describe("the web setup's text", () => {
  it("has every string in every language, and keeps the copy rules (docs/translations.md)", () => {
    const fns = Object.entries(en).filter(([, v]) => typeof v === "function").map(([k]) => k);
    for (const l of LANGS) {
      expect(keysOf(TEXT[l]).sort(), l).toEqual(keysOf(en).sort());
      expect(copyProblems(l, strings(TEXT[l], SAMPLES_FOR(fns))), l).toEqual([]);
    }
  });
  it("keeps the tagline in English", () => {
    for (const l of LANGS) expect(TEXT[l].tagline).toBe("AI for work that can't leave the premises.");
  });
  it("picks a supported language from the browser's", () => {
    expect(pickLang(["de-DE", "nl-BE"])).toBe("nl");
    expect(pickLang(["de"])).toBe("en");
  });
});

describe("the administrator account", () => {
  const check = (a: Partial<typeof ok>) => checkAdministrator({ ...ok, ...a }, "notary-brussels-01", en);
  it("accepts a good account", () => expect(check({})).toEqual({}));
  it("needs a name and a valid email address", () => {
    expect(check({ name: " " })).toEqual({ name: en.errNameMissing });
    expect(check({ email: "" })).toEqual({ email: en.errEmailMissing });
    expect(check({ email: "filip@firm" })).toEqual({ email: en.errEmailInvalid });
  });
  it("needs at least 15 characters, counted as characters", () => {
    expect(check({ password: "short one", confirm: "short one" }).password).toBe(en.errPasswordShort(15));
    expect(check({ password: "ūūūūūūūaaaaaaaa", confirm: "ūūūūūūūaaaaaaaa" })).toEqual({});
  });
  it("refuses common and patterned passwords", () => {
    for (const p of ["passwordpassword", "aaaaaaaaaaaaaaaa", "abcdefghijklmnop", "123456789012345"]) {
      expect(isCommonPassword(p), p).toBe(true);
      expect(check({ password: p, confirm: p }).password).toBe(en.errPasswordCommon);
    }
  });
  it("refuses the name, the email address or the appliance's name in the password", () => {
    for (const p of ["my name is Filip, hello", "a long tack password!", "brussels office 2026", "the notary password"]) {
      expect(check({ password: p, confirm: p }).password, p).toBe(en.errPasswordPersonal);
    }
  });
  it("needs the confirmation to match, but only once the password itself is right", () => {
    expect(check({ confirm: "something else" })).toEqual({ confirm: en.errConfirm });
    expect(check({ password: "short", confirm: "other" })).toEqual({ password: en.errPasswordShort(15) });
  });
});

describe("React Aria under the appliance's CSP", () => {
  const require = createRequire(import.meta.url);
  const file = join(dirname(require.resolve("react-aria/package.json")), "dist/private/overlays/usePreventScroll.mjs");

  it("replaces the inline <style> of usePreventScroll with an attribute", () => {
    const code = readFileSync(file, "utf8");
    expect(code).toContain(PREVENT_SCROLL_STYLE);
    const plugin = reactAriaCsp();
    const out = (plugin.transform as (c: string, id: string) => { code: string })(code, file).code;
    expect(out).not.toContain("createElement('style')");
    expect(out).toContain("data-ui-prevent-scroll");
  });
  it("fails the build when React Aria changes that code", () => {
    const plugin = reactAriaCsp();
    expect(() => (plugin.transform as (c: string, id: string) => unknown)("export {}", file)).toThrow(/changed/);
  });
  it("has the rules React Aria would have written inline in ui.css", () => {
    const css = readFileSync(new URL("../ui/ui.css", import.meta.url), "utf8");
    expect(css).toContain("[data-react-aria-pressable] { touch-action: pan-x pan-y pinch-zoom; }");
    expect(css).toContain("html[data-ui-prevent-scroll] * { overscroll-behavior: contain; }");
  });
});
