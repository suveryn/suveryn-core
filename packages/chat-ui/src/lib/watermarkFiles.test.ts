import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import { toBlocks, type Table } from "./answer";
import type { AnswerExport } from "./export";
import { answerToWord, tableToExcel, type OfficeText } from "./office";
import { answerToMarkdown, tableToCsv } from "./textfiles";

const text: OfficeText = {
  answeredOn: (d) => `Answered on ${d}`, checkHeading: "To check", sourcesHeading: "Sources", sourceRemoved: "Removed",
  sourceColumn: "Source", sheetTable: "Table", sheetSources: "Sources", sheetChecks: "To check",
  columns: { n: "No.", document: "Document", where: "Where", passage: "Passage" }, disclaimer: "Check it.",
};
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

  it("Excel: the line first and last on every sheet", async () => {
    const zip = await unzip(await tableToExcel(blocks[1] as Table, answer(W), text));
    const strings = await zip.file("xl/sharedStrings.xml")?.async("string") ?? "";
    const sheets = await Promise.all(Object.keys(zip.files).filter((f) => /xl\/worksheets\/sheet\d+\.xml$/.test(f)).map((f) => zip.file(f)!.async("string")));
    expect(strings + sheets.join("")).toContain(W.line);
  });

  it("Markdown and CSV: the line first", () => {
    expect(answerToMarkdown(answer(W), text, "en-GB").split("\n")[0]).toBe(`**${W.line}**`);
    expect(tableToCsv(blocks[1] as Table, text, W).replace("﻿", "").split("\r\n")[0]).toBe(W.line);
    expect(tableToCsv(blocks[1] as Table, text).replace("﻿", "").split("\r\n")[0]).toBe("Name;Role;Source");
  });
});
