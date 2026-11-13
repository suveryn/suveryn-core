import { afterEach, describe, expect, it } from "vitest";
import { dayLabel } from "../lib/conversations";
import { statusText } from "../lib/status";
import { LANGS, pickLang, setLang, t, TABLES_FOR_TESTS as TABLES, type Lang } from ".";
import { copyProblems, strings } from "./rules";
import { signInLang } from "./languages";

const texts = (l: Lang) => strings(TABLES[l]);

afterEach(() => setLang("en"));

describe("interface languages (suveryn-tracker#8)", () => {
  it("every language has every string, and keeps the copy rules (docs/translations.md)", () => {
    const keys = Object.keys(TABLES.en).sort();
    for (const l of LANGS) expect(Object.keys(TABLES[l]).sort(), l).toEqual(keys);
    for (const l of LANGS) expect(copyProblems(l, texts(l)), l).toEqual([]);
  });

  it("a reason shown inside answerFailed is a sentence of its own, ended once (Pod check of dbe0431: \"opnieuw.. \")", () => {
    for (const l of LANGS) {
      const whole = TABLES[l].answerFailed({ why: TABLES[l].chosenDeletedMeanwhile });
      expect(whole, l).not.toMatch(/\.\.|: /);
      expect(whole.split(/(?<=\.) /).length, l).toBeGreaterThanOrEqual(3);
    }
  });

  it("the copy rules catch what they are for", () => {
    expect(copyProblems("nl", [["a", "Heeft u dit?"], ["b", "Heb je dit?"], ["c", ""]]).map(([k, w]) => `${k}: ${w}`))
      .toEqual(["b: informal Dutch", "c: empty"]);
    expect(copyProblems("fr", [["a", "Vous avez"], ["b", "Tu as"], ["c", "l'acte"]]).map(([k]) => k)).toEqual(["b"]);
    // the fixed terms (docs/translations.md): Dutch says "gedeelde map" and "ondersteuning"
    expect(copyProblems("nl", [["a", "Het adres van de share"], ["b", "Bij support"], ["c", "zoals \\\\server\\share (SMB)"],
                               ["d", "De gedeelde map"], ["e", "Supportovereenkomst"]]).map(([k]) => k)).toEqual(["a", "b", "e"]);
    expect(copyProblems("en", [["a", "Made by sūveryn."], ["b", "Ask Sūveryn"], ["c", "Done. sūveryn knows"], ["d", "Sūveryn Labs"],
                               ["e", "a — b"], ["f", "suveryn"]]).map(([k]) => k)).toEqual(["b", "c", "e", "f"]);
  });

  it("takes the language picked on the sign-in page from the gateway's cookie, and only a supported one", () => {
    expect(signInLang("a=1; suveryn_sign_in_lang=nl; b=2")).toBe("nl");
    expect(signInLang("suveryn_sign_in_lang=fr")).toBe("fr");
    expect(signInLang("suveryn_sign_in_lang=de")).toBeNull();
    expect(signInLang("other_suveryn_sign_in_lang=nl")).toBeNull();
    expect(signInLang("")).toBeNull();
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
