import { describe, expect, it } from "vitest";
import { httpErrorText } from "../api";
import { setLang } from "../i18n";
import { sourceFileName } from "./copy";
import { ACCEPTED_FILES, DOCUMENT_EXTENSION, formatName } from "./formats";

describe("the files sūveryn reads", () => {
  it("offers every format the server reads, and only those", () => {
    const extensions = ACCEPTED_FILES.filter((a) => a.startsWith("."));
    expect(extensions).toEqual([".pdf", ".docx", ".xlsx", ".md", ".markdown", ".csv"]);
    for (const ext of extensions) expect(`deed${ext}`).toMatch(DOCUMENT_EXTENSION);
    expect("deed.doc").not.toMatch(DOCUMENT_EXTENSION);
  });

  it("names a format without pages the same way in every language", () => {
    expect(["a.docx", "b.XLSX", "c.md", "d.csv", "e.pdf", "f"].map(formatName)).toEqual(["Word", "Excel", "Markdown", "CSV", "", ""]);
  });

  it("drops any document extension from a source's file name", () => {
    expect(sourceFileName(2, "price list.xlsx", null)).toBe("source-2_price_list.txt");
    expect(sourceFileName(1, "deed.docx", null, "md")).toBe("source-1_deed.md");
  });

  it("says which files can be added when one can't, in the interface's language", () => {
    setLang("en", false);
    expect(httpErrorText(415, "only PDF ... files can be added")).toMatch(/PDF, Word \(\.docx\), Excel \(\.xlsx\), Markdown \(\.md\) and CSV/);
    setLang("fr", false);
    expect(httpErrorText(415, "the file is not a valid Word file")).toMatch(/^ce fichier ne peut pas être ajouté/);
    setLang("en", false);
  });
});
