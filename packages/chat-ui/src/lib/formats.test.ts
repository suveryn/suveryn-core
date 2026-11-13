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
    expect(httpErrorText(415, { kind: "refused", code: "upload.unsupported_type" })).toBe("This file type isn't read: use PDF, Word, Excel, Markdown, CSV or .zip.");
    setLang("fr", false);
    expect(httpErrorText(415, { kind: "refused", code: "upload.invalid" })).toMatch(/^Le contenu de ce fichier ne correspond pas à son type/);
    setLang("en", false);
  });

  it("says why a .zip couldn't be added, and why a file in it was left out", async () => {
    const { TABLES_FOR_TESTS: TEXT } = await import("../i18n");
    setLang("nl", false);
    // by the server's code, never by its English words (decision of 12 November 2026, Messages are codes)
    const refused = (code: string, params = {}) => ({ kind: "refused", code, params, detail: "English, for developers" });
    expect(httpErrorText(413, refused("upload.too_large"))).toBe("Het bestand is groter dan de server aanvaardt.");
    expect(httpErrorText(415, refused("upload.archive_empty"))).toBe(TEXT.nl.messages["upload.archive_empty"]);
    expect(httpErrorText(413, refused("upload.archive_too_big"))).toBe(TEXT.nl.messages["upload.archive_too_big"]);
    expect(httpErrorText(415, refused("upload.not_zip"))).toBe(TEXT.nl.messages["upload.not_zip"]);
    expect(httpErrorText(429, refused("upload.queue_full"))).toBe(TEXT.nl.messages["upload.queue_full"]);
    expect(httpErrorText(429, refused("request.too_many", { seconds: 30 }))).toMatch(/30 seconden/);
    expect(httpErrorText(429, refused("run.busy"))).toBe(TEXT.nl.messages["run.busy"]);
    expect(httpErrorText(415, "the archive is empty")).toBe(TEXT.nl.messages["request.unsupported"]);  // the words alone mean nothing here
    setLang("en", false);
    for (const t of Object.values(TEXT)) {
      for (const reason of ["unsupported", "archive", "encrypted", "too_large", "empty", "invalid", "damaged"]) {
        expect(t.archiveSkipped({ archive: "Prospectus.zip", reason })).toContain("Prospectus.zip");
        expect(t.archiveSkipped({ archive: "a.zip", reason })).not.toBe(t.archiveSkipped({ archive: "a.zip", reason: "something else" }));
      }
    }
  });
});
