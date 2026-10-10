import { afterEach, describe, expect, it } from "vitest";
import { dayLabel } from "../lib/conversations";
import { statusText } from "../lib/status";
import { LANGS, pickLang, setLang, t, TABLES_FOR_TESTS as TABLES, type Lang } from ".";

const ARRAYS: Record<string, unknown[]> = { pageList: [[1, 3]], reviewHint: [[1, 3]], calcMissing: [["1.000,00"]], unverified: [["1.000,00", "2,5"]] };

/** Every string of a table, with functions called on sample arguments. */
function texts(l: Lang): [string, string][] {
  return Object.entries(TABLES[l]).flatMap(([k, v]) => {
    if (typeof v === "string") return [[k, v] as [string, string]];
    const fn = v as (...a: unknown[]) => string;
    const samples = ARRAYS[k] ? [ARRAYS[k], [[1]].concat()] : [["X", "Y", 3], [1, "Y", null]];
    return samples.map((args) => [k, fn(...(args as unknown[]))] as [string, string]);
  });
}

afterEach(() => setLang("en"));

describe("interface languages (suveryn-tracker#8)", () => {
  it("every language has every string", () => {
    const keys = Object.keys(TABLES.en).sort();
    for (const l of LANGS) expect(Object.keys(TABLES[l]).sort()).toEqual(keys);
    for (const l of LANGS) for (const [k, v] of texts(l)) expect(v.trim(), `${l}.${k}`).not.toBe("");
  });

  it("Dutch is formal: u/uw, never je/jij/jouw", () => {
    const informal = texts("nl").filter(([, v]) => /(^|[^\p{L}])(je|jij|jouw|jullie)(?![\p{L}])/iu.test(v));
    expect(informal).toEqual([]);
  });

  it("sūveryn is lower case except at the start of a sentence", () => {
    for (const l of LANGS) {
      const wrong = texts(l).filter(([, v]) => /(?<![.!?:]\s|^)Sūveryn/u.test(v) || /suveryn/i.test(v.replaceAll("sūveryn", "").replaceAll("Sūveryn", "")));
      expect(wrong, l).toEqual([]);
    }
  });

  it("picks the browser's language when supported, else English", () => {
    expect(pickLang(["nl-BE", "en"])).toBe("nl");
    expect(pickLang(["fr-FR"])).toBe("fr");
    expect(pickLang(["de-DE", "fr"])).toBe("fr");
    expect(pickLang(["de-DE"])).toBe("en");
    expect(pickLang([])).toBe("en");
  });

  it("switching changes what the helpers say", () => {
    const status = { step: "writing", passages: null, complete: null, model: null } as const;
    const now = new Date(2026, 9, 10, 14);
    expect([statusText(status), dayLabel(new Date(2026, 9, 3).toISOString(), now)]).toEqual(["Writing the answer…", "3 Oct"]);
    setLang("nl");
    expect([t().signIn, statusText(status), dayLabel(new Date(2026, 9, 3).toISOString(), now)])
      .toEqual(["Inloggen", "Het antwoord wordt geschreven…", "3 okt"]);
    setLang("fr");
    expect([t().signIn, dayLabel(new Date(2026, 9, 9).toISOString(), now)]).toEqual(["Se connecter", "Hier"]);
  });
});
