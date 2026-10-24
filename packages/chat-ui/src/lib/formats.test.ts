import { describe, expect, it } from "vitest";
import { httpErrorText } from "../api";
import { setLang } from "../i18n";
import { sourceFileName } from "./copy";
import { ACCEPTED_FILES, DOCUMENT_EXTENSION, DOCUMENT_FILES, formatName } from "./formats";

describe("the files sūveryn reads", () => {
  it("offers every format the server reads, and only those", () => {
    const extensions = DOCUMENT_FILES.filter((a) => a.startsWith("."));
    expect(extensions).toEqual([".pdf", ".docx", ".xlsx", ".md", ".markdown", ".csv"]);
    expect(ACCEPTED_FILES.filter((a) => a.startsWith("."))).toEqual([...extensions, ".zip"]);  // and archives of them
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

  it("says why a .zip couldn't be added, and why a file in it was left out", async () => {
    const { TABLES_FOR_TESTS: TEXT } = await import("../i18n");
    setLang("nl", false);
    expect(httpErrorText(413, "the archive holds 25 documents and at most 20 can wait to be read at once; split it")).toMatch(/25 documenten.*hoogstens 20/);
    expect(httpErrorText(413, "the file is larger than 100 MB")).toBe(TEXT.nl.fileTooLarge);
    expect(httpErrorText(415, "the archive holds no PDF, Word ...")).toBe(TEXT.nl.archiveNothing);
    expect(httpErrorText(415, "the file is not a valid ZIP archive")).toBe(TEXT.nl.archiveInvalid);
    expect(httpErrorText(429, "too many documents are waiting to be read; try again when some are done")).toBe(TEXT.nl.tooManyWaiting);
    expect(httpErrorText(429, "slow down", "30")).toMatch(/30 seconden/);
    setLang("en", false);
    for (const t of Object.values(TEXT)) {
      for (const reason of ["unsupported", "archive", "encrypted", "too_large", "empty", "invalid", "damaged"]) {
        expect(t.archiveSkipped("Prospectus.zip", reason)).toContain("Prospectus.zip");
        expect(t.archiveSkipped("a.zip", reason)).not.toBe(t.archiveSkipped("a.zip", "something else"));
      }
    }
  });
});
