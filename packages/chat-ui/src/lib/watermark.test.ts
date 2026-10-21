import { describe, expect, it } from "vitest";
import en from "../i18n/en";
import nl from "../i18n/nl";
import { watermark, withWatermark } from "./watermark";

const at = new Date(2026, 9, 21, 14, 32);

describe("the strictly confidential watermark", () => {
  it("names the case, the person and the time, the Belgian way", () => {
    expect(watermark({ reference: "125", confidential: true }, "Test Beheerder", nl, "nl-BE", at))
      .toEqual({ label: "STRIKT VERTROUWELIJK", line: "STRIKT VERTROUWELIJK · dossier 125 · Test Beheerder · 21/10/2026 14:32" });
    expect(watermark({ reference: "125", confidential: true }, "Test Admin", en, "en-GB", at)?.line)
      .toBe("STRICTLY CONFIDENTIAL · case 125 · Test Admin · 21/10/2026 14:32");
  });

  it("is there only for a strictly confidential case", () => {
    expect(watermark({ reference: "125" }, "x", en, "en-GB", at)).toBeUndefined();
    expect(watermark(null, "x", en, "en-GB", at)).toBeUndefined();
  });

  it("is a text file's first line", () => {
    const w = watermark({ reference: "125", confidential: true }, "A", en, "en-GB", at);
    expect(withWatermark("body", w).split("\n")).toEqual([w!.line, "", "body"]);
    expect(withWatermark("body", undefined)).toBe("body");
  });
});
