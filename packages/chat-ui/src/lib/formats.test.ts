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
    expect(httpErrorText(415, "only PDF ... files can be added")).toBe("this file type isn't read: use PDF, Word, Excel, Markdown, CSV or .zip");
    setLang("fr", false);
    expect(httpErrorText(415, "the file is not a valid Word file")).toMatch(/^ce type de fichier n'est pas lu/);
    setLang("en", false);
  });

  it("says why a .zip couldn't be added, and why a file in it was left out", async () => {
    const { TABLES_FOR_TESTS: TEXT } = await import("../i18n");
    setLang("nl", false);
    expect(httpErrorText(413, "the file is larger than 100 MB")).toBe(TEXT.nl.fileTooLarge);
    expect(httpErrorText(415, "the archive is empty")).toBe(TEXT.nl.archiveEmpty);
    expect(httpErrorText(413, "the archive unpacks to more than 300 MB")).toBe(TEXT.nl.archiveTooBig);
    expect(httpErrorText(415, "the file is not a valid ZIP archive")).toBe(TEXT.nl.archiveInvalid);
    expect(httpErrorText(429, "too many documents are waiting to be read; try again when some are done")).toBe(TEXT.nl.tooManyWaiting);
    expect(httpErrorText(429, "slow down", "30")).toMatch(/30 seconden/);
    expect(httpErrorText(429, "too many playbook runs are reading; start this one when one has finished")).toBe(TEXT.nl.playbooksBusy);
    setLang("en", false);
    for (const t of Object.values(TEXT)) {
      for (const reason of ["unsupported", "archive", "encrypted", "too_large", "empty", "invalid", "damaged"]) {
        expect(t.archiveSkipped("Prospectus.zip", reason)).toContain("Prospectus.zip");
        expect(t.archiveSkipped("a.zip", reason)).not.toBe(t.archiveSkipped("a.zip", "something else"));
      }
    }
  });
});
