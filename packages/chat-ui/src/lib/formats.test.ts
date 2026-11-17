import { describe, expect, it } from "vitest";
import { httpErrorText } from "../api";
import { setLang } from "../i18n";
import { sourceFileName } from "./copy";
import { ACCEPTED_FILES, DOCUMENT_EXTENSION, DOCUMENT_FILES, formatName } from "./formats";
import { messageText } from "./messages";

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
    expect(httpErrorText(415, { kind: "refused", code: "upload.unsupported" })).toBe("This file type isn't read: use PDF, Word, Excel, Markdown, CSV or .zip.");
    setLang("fr", false);
    expect(httpErrorText(415, { kind: "refused", code: "upload.content_mismatch" })).toMatch(/^Le contenu de ce fichier ne correspond pas à son type/);
    setLang("en", false);
  });

  it("says why a .zip couldn't be added, and why a file in it was left out", async () => {
    const { TABLES_FOR_TESTS: TEXT } = await import("../i18n");
    setLang("nl", false);
    // by the server's code, never by its English words (decision of 12 November 2026, Messages are codes)
    const refused = (code: string, params = {}) => ({ kind: "refused", code, params, detail: "English, for developers" });
    expect(httpErrorText(413, refused("upload.too_large"))).toBe("Het bestand is groter dan de server aanvaardt.");
    expect(httpErrorText(415, refused("upload.archive_empty"))).toBe(TEXT.nl.messages["upload.archive_empty"]);
    expect(httpErrorText(413, refused("upload.archive_too_large"))).toBe(TEXT.nl.messages["upload.archive_too_large"]);
    expect(httpErrorText(415, refused("upload.not_a_zip"))).toBe(TEXT.nl.messages["upload.not_a_zip"]);
    expect(httpErrorText(429, refused("upload.too_many"))).toBe(TEXT.nl.messages["upload.too_many"]);
    expect(httpErrorText(429, refused("request.too_many", { seconds: 30 }))).toMatch(/30 seconden/);
    expect(httpErrorText(429, refused("run.too_many"))).toBe(TEXT.nl.messages["run.too_many"]);
    expect(httpErrorText(415, "the archive is empty")).toBe(TEXT.nl.messages["request.unsupported"]);  // the words alone mean nothing here
    setLang("en", false);
    // a file left out of a .zip says it was, from which archive, and why in a sentence of its own (suveryn-tracker#158)
    for (const t of Object.values(TEXT)) {
      expect(t.cardNotAddedFrom({ file: "akte.pdf", archive: "Prospectus.zip" })).toMatch(/akte\.pdf.*Prospectus\.zip/);
      for (const code of ["upload.unsupported", "upload.archive_inside_unsupported", "document.password_protected", "upload.empty",
                          "upload.content_mismatch", "document.damaged"] as const) expect(t.messages[code]).toMatch(/\.$/);
      expect(messageText({ code: "upload.too_large", params: { max_mb: 200 } }, t)).toContain("200");
    }
  });
});
