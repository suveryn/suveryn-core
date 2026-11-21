/** The case types come from the server (suveryn-tracker#229); the screens word them in the interface language. */
import { describe, expect, it } from "vitest";
import type { CaseTypeInfo } from "../api";
import { setLang } from "../i18n";
import { caseTypeLabel, setCaseTypes } from "./caseTypes";

describe("a case type's word", () => {
  it("is the pack's word in the interface language, English where the pack has none, and the id for a type not offered", () => {
    const types: CaseTypeInfo[] = [{ id: "sale", pack: "pack/be-notary", text: { en: "Sale", nl: "Verkoop", fr: "Vente" } },
                   { id: "will", pack: "pack/x-test", text: { en: "Will" } }];
    setCaseTypes(types);
    setLang("nl");
    expect(caseTypeLabel("sale")).toBe("Verkoop");
    expect(caseTypeLabel("will")).toBe("Will");
    expect(caseTypeLabel("gift")).toBe("gift");  // a stored type whose pack is gone
    setLang("fr");
    expect(caseTypeLabel("sale", types)).toBe("Vente");
    setLang("en");
  });
});
