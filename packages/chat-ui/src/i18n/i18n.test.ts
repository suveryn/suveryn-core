import { afterEach, describe, expect, it } from "vitest";
import { dayLabel } from "../lib/conversations";
import { statusText } from "../lib/status";
import { LANGS, pickLang, setLang, t, TABLES_FOR_TESTS as TABLES, type Lang } from ".";
import { copyProblems, strings } from "./rules";

const ARRAYS: Record<string, unknown[]> = { pageList: [[1, 3]], reviewHint: [[1, 3]], calcMissing: [["1.000,00"]], unverified: [["1.000,00", "2,5"]] };
/** Sample arguments for functions whose arguments the defaults don't fit: two or more each, covering their branches. */
const SAMPLES: Record<string, unknown[][]> = {
  ...Object.fromEntries(Object.entries(ARRAYS).map(([k, a]) => [k, [a, [[1]]]])),
  citationIssue: [[2, "410.000", [3], null], [1, "Peters", [1], "Peeters"], [2, "12/03/2021", [], null], [2, "X", [1, 3], null]],
  deleteDocumentDialogBody: [[1], [3]], deleteDocumentAndConversations: [[1], [3]],
  instructionLike: [[[2]], [[1, 3]]],
  exportMark: [["answer", "2026/0611", "19-10-2026", "A-3f9c2e1b"], ["playbook", null, "19-10-2026", "P-0a1b2c3d"]],
  originPlaybook: [["1.0"], [null]], originWasOutput: [["answer"], ["playbook"]], noticedTitle: [["answer"], ["playbook"]],
};
const texts = (l: Lang) => strings(TABLES[l], SAMPLES);

afterEach(() => setLang("en"));

describe("interface languages (suveryn-tracker#8)", () => {
  it("every language has every string, and keeps the copy rules (docs/translations.md)", () => {
    const keys = Object.keys(TABLES.en).sort();
    for (const l of LANGS) expect(Object.keys(TABLES[l]).sort(), l).toEqual(keys);
    for (const l of LANGS) expect(copyProblems(l, texts(l)), l).toEqual([]);
  });

  it("a reason shown inside answerFailed reads as one sentence (Pod check of f8f4be9: \"opnieuw.. \")", () => {
    for (const l of LANGS) {
      const whole = TABLES[l].answerFailed(TABLES[l].chosenDeletedMeanwhile);
      expect(whole, l).not.toMatch(/\.\.|: [A-Z]/);
    }
  });

  it("the copy rules catch what they are for", () => {
    expect(copyProblems("nl", [["a", "Heeft u dit?"], ["b", "Heb je dit?"], ["c", ""]]).map(([k, w]) => `${k}: ${w}`))
      .toEqual(["b: informal Dutch", "c: empty"]);
    expect(copyProblems("fr", [["a", "Vous avez"], ["b", "Tu as"], ["c", "l'acte"]]).map(([k]) => k)).toEqual(["b"]);
    expect(copyProblems("en", [["a", "Made by sūveryn."], ["b", "Ask Sūveryn"], ["c", "Done. sūveryn knows"], ["d", "Sūveryn Labs"],
                               ["e", "a — b"], ["f", "suveryn"]]).map(([k]) => k)).toEqual(["b", "c", "e", "f"]);
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
