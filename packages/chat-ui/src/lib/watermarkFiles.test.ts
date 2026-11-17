import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import { toBlocks, type Table } from "./answer";
import type { AnswerExport } from "./export";
import { headerFooterText, pictureLine } from "./excelWatermark";
import { answerToWord, intakeToWord, tableToExcel, type IntakeExport, type OfficeText } from "./office";
import { answerToMarkdown, tableToCsv } from "./textfiles";

const text: OfficeText = {
  answeredOn: (d) => `Answered on ${d}`, checkHeading: "To check", sourcesHeading: "Sources", sourceRemoved: "Removed",
  sourceColumn: "Source", sheetTable: "Table", sheetSources: "Sources", sheetChecks: "To check",
  columns: { n: "No.", document: "Document", where: "Where", passage: "Passage" }, disclaimer: "Check it.",
};
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]).buffer;
const W = { label: "STRICTLY CONFIDENTIAL", line: "STRICTLY CONFIDENTIAL · case 125 · Test Admin · 21/10/2026 14:32" };
const blocks = toBlocks("The parties:\n\n| Name | Role |\n| --- | --- |\n| A | Seller |", 0);
const answer = (watermark?: typeof W): AnswerExport => ({ question: "Who?", answeredOn: new Date(2026, 9, 21), blocks, checks: [], sources: [],
                                                         mark: "Made by sūveryn · sūveryn-ref A-1", watermark });
const unzip = async (b: Blob) => JSZip.loadAsync(await b.arrayBuffer());

describe("exports from a strictly confidential case", () => {
  it("Word: the label across every page, as Word's own watermark, and the line in the header", async () => {
    const zip = await unzip(await answerToWord(answer(W), text, "en-GB"));
    const headers = Object.keys(zip.files).filter((f) => /word\/header\d*\.xml$/.test(f));
    const xml = (await Promise.all(headers.map((f) => zip.file(f)!.async("string")))).join("");
    expect(xml).toContain('string="STRICTLY CONFIDENTIAL"');  // the WordArt text path
    expect(xml).toContain(W.line);
    const plain = await unzip(await answerToWord(answer(), text, "en-GB"));
    expect(Object.keys(plain.files).some((f) => /word\/header\d*\.xml$/.test(f))).toBe(false);
  });

  it("Word: with a picture, the picture behind the text, as Word's own picture watermark, and the line", async () => {
    const zip = await unzip(await answerToWord(answer(W), text, "en-GB", async () => PNG));
    const headers = Object.keys(zip.files).filter((f) => /word\/header\d*\.xml$/.test(f));
    const xml = (await Promise.all(headers.map((f) => zip.file(f)!.async("string")))).join("");
    expect(xml).toContain("<v:imagedata");
    expect(xml).not.toContain('string="STRICTLY CONFIDENTIAL"');  // the picture replaces the text watermark
    expect(xml).toContain(W.line);
    const media = Object.keys(zip.files).filter((f) => f.startsWith("word/media/") && !f.endsWith("/"));
    expect(media).toHaveLength(1);
    expect(new Uint8Array(await zip.file(media[0])!.async("arraybuffer"))).toEqual(new Uint8Array(PNG));
  });

  it("Word: the playbook result carries the picture too; a picture that fails leaves the text watermark", async () => {
    const intake = (watermark?: typeof W): IntakeExport => ({ title: "Deed intake", caseName: "Case 125", version: "1.7", confirmedOn: "21 October 2026",
      facts: [{ label: "Price", value: "EUR 412.500,00", sources: ["agreement.pdf, p. 2"] }], sourcesHeading: "Sources", emptyValue: "-",
      disclaimer: "Check it.", mark: "Made by sūveryn", watermark });
    const headerXml = async (b: Blob) => {
      const zip = await unzip(b);
      return (await Promise.all(Object.keys(zip.files).filter((f) => /word\/header\d*\.xml$/.test(f)).map((f) => zip.file(f)!.async("string")))).join("");
    };
    const withPicture = await headerXml(await intakeToWord(intake(W), async () => PNG));
    expect(withPicture).toContain("<v:imagedata");
    expect(withPicture).toContain(W.line);
    const failed = await headerXml(await intakeToWord(intake(W), async () => { throw new Error("no canvas"); }));
    expect(failed).toContain('string="STRICTLY CONFIDENTIAL"');
    expect(await headerXml(await intakeToWord(intake(), async () => PNG))).toBe("");
  });

  it("Excel: the line first and last on every sheet", async () => {
    const zip = await unzip(await tableToExcel(blocks[1] as Table, answer(W), text));
    const strings = await zip.file("xl/sharedStrings.xml")?.async("string") ?? "";
    const sheets = await Promise.all(Object.keys(zip.files).filter((f) => /xl\/worksheets\/sheet\d+\.xml$/.test(f)).map((f) => zip.file(f)!.async("string")));
    expect(strings + sheets.join("")).toContain(W.line);
  });

  // suveryn-tracker#183: rows alone are deleted with two clicks; the header and footer show on paper, the
  // picture behind the cells on screen.
  const sheetFiles = (zip: JSZip) => Object.keys(zip.files).filter((f) => /xl\/worksheets\/sheet\d+\.xml$/.test(f));

  it("Excel: the line in every sheet's header and footer, and the picture behind every sheet's cells", async () => {
    const zip = await unzip(await tableToExcel(blocks[1] as Table, answer(W), text, async () => PNG));
    const names = sheetFiles(zip);
    expect(names.length).toBeGreaterThan(1);
    for (const name of names) {
      const xml = await zip.file(name)!.async("string");
      expect(xml).toContain(`<oddHeader>&amp;C&amp;B${W.line}</oddHeader>`);
      expect(xml).toContain(`<oddFooter>&amp;C${W.line}</oddFooter>`);
      expect(xml).toMatch(/<\/sheetData>[\s\S]*<headerFooter>[\s\S]*<picture r:id="rId-suveryn-watermark"\/>/);  // the order the format requires
      const rels = await zip.file(name.replace("worksheets/", "worksheets/_rels/") + ".rels")!.async("string");
      expect(rels).toContain('Id="rId-suveryn-watermark"');
      expect(rels).toContain('Target="../media/suveryn-watermark.png"');
    }
    expect(new Uint8Array(await zip.file("xl/media/suveryn-watermark.png")!.async("arraybuffer"))).toEqual(new Uint8Array(PNG));
    expect(await zip.file("[Content_Types].xml")!.async("string")).toContain('<Default Extension="png" ContentType="image/png"/>');
  });

  it("Excel: without a picture (no canvas) the header and footer still; outside such a case, none of it", async () => {
    const zip = await unzip(await tableToExcel(blocks[1] as Table, answer(W), text, async () => undefined));
    const xml = await zip.file(sheetFiles(zip)[0])!.async("string");
    expect(xml).toContain("<headerFooter>");
    expect(xml).not.toContain("<picture");
    expect(zip.file("xl/media/suveryn-watermark.png")).toBeNull();
    const plain = await unzip(await tableToExcel(blocks[1] as Table, answer(), text, async () => PNG));
    expect(await plain.file(sheetFiles(plain)[0])!.async("string")).not.toContain("<headerFooter>");
    expect(plain.file("xl/media/suveryn-watermark.png")).toBeNull();
  });

  it("Excel: an & in the line is text, not a header code, and the XML stays valid", async () => {
    expect(headerFooterText("Van Damme & Peeters")).toBe("Van Damme && Peeters");
    expect(headerFooterText("x".repeat(239) + "&&")).toBe("x".repeat(239));  // never a lone & at the end
    expect(headerFooterText("x".repeat(200))).toHaveLength(200);  // a long reference and name are kept whole
    expect(pictureLine(W)).toBe("case 125 · Test Admin · 21/10/2026 14:32");
    const zip = await unzip(await tableToExcel(blocks[1] as Table, answer({ ...W, line: "case 7 · Van Damme & <Peeters>" }), text, async () => undefined));
    const xml = await zip.file(sheetFiles(zip)[0])!.async("string");
    expect(xml).toContain("<oddHeader>&amp;C&amp;Bcase 7 · Van Damme &amp;&amp; &lt;Peeters&gt;</oddHeader>");
  });

  it("Markdown and CSV: the line first", () => {
    expect(answerToMarkdown(answer(W), text, "en-GB").split("\n")[0]).toBe(`**${W.line}**`);
    expect(tableToCsv(blocks[1] as Table, text, W).replace("﻿", "").split("\r\n")[0]).toBe(W.line);
    expect(tableToCsv(blocks[1] as Table, text).replace("﻿", "").split("\r\n")[0]).toBe("Name;Role;Source");
  });
});
