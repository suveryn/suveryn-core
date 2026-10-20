import { describe, expect, it } from "vitest";
import { toBlocks, type Table } from "./answer";
import type { AnswerExport } from "./export";
import type { OfficeText } from "./office";
import { answerToMarkdown, tableToCsv } from "./textfiles";

const text: OfficeText = {
  answeredOn: (date: string) => `Answered by sūveryn on ${date}`, checkHeading: "To check", sourcesHeading: "Sources",
  sourceRemoved: "Source removed", sourceColumn: "Source", sheetTable: "Table", sheetSources: "Sources", sheetChecks: "To check",
  columns: { n: "No.", document: "Document", where: "Where", passage: "Passage" }, disclaimer: "Check before relying on it.",
};

const answer = "The parties are:\n\n| Name | Role | Price |\n| --- | --- | ---: |\n| John Smith [1] | Seller | EUR 1,275,000.00 [2] |\n\n" +
  "- the buyer pays on **signing** [1]\n- costs are shared\n\nEverything is checked [2].";

const exported = (over: Partial<AnswerExport> = {}): AnswerExport => ({
  question: "Who are the parties?", answeredOn: new Date(2026, 9, 19), model: "Model A",
  blocks: toBlocks(answer, 2), checks: ["Check 1,275,000.00"],
  sources: [
    { n: 1, filename: "deed.pdf", citation: { text: "John Smith, seller,\nsells the house.", source: { page: 3 } as never } },
    { n: 2, filename: "price.docx", citation: { text: "gone", source: null, removed: true } },
  ],
  mark: "Made by sūveryn: answer, 19/10/2026 · sūveryn-ref A-3f9c2e1b",
  ...over,
});

describe("an answer as Markdown", () => {
  const md = answerToMarkdown(exported(), text, "en-GB");

  it("has the question, the date and model, the blocks, what to check, the sources and the disclaimer, in order", () => {
    const order = ["# Who are the parties?", "*Answered by sūveryn on 19 October 2026 (Model A)*", "The parties are:",
      "| Name | Role | Price |", "- the buyer pays on **signing** [1]", "Everything is checked [2].", "## To check",
      "## Sources", "**[1]** deed.pdf, p. 3", "**[2]** Source removed", "*Check before relying on it.*"];
    const at = order.map((line) => md.split("\n").indexOf(line));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });

  it("writes a table as a Markdown table with its markers, and a list as one list", () => {
    expect(md).toContain("| Name | Role | Price |\n| --- | --- | --- |\n| John Smith [1] | Seller | EUR 1,275,000.00 [2] |");
    expect(md).toContain("- the buyer pays on **signing** [1]\n- costs are shared\n\n");
  });

  it("quotes a cited passage line by line, and leaves out a removed one", () => {
    expect(md).toContain("> John Smith, seller,\n> sells the house.");
    expect(md).not.toContain("gone");
  });

  it("ends with sūveryn's mark as a comment, which the upload check reads", () => {
    expect(md.trimEnd().split("\n").pop()).toBe("<!-- Made by sūveryn: answer, 19/10/2026 · sūveryn-ref A-3f9c2e1b -->");
    expect(answerToMarkdown(exported({ mark: "a --> b" }), text, "en-GB")).toContain("<!-- a ‐‐> b -->");  // can't close early
    expect(answerToMarkdown(exported({ mark: undefined }), text, "en-GB")).not.toContain("<!--");
  });

  it("escapes what the model wrote, so it can't add headings, links or HTML", () => {
    const md2 = answerToMarkdown(exported({ question: "# A [link](x) <b>", blocks: toBlocks("Price * 2 = _x_ <script>", 0) }), text, "en-GB");
    expect(md2).toContain("# \\# A \\[link\\](x) \\<b\\>");
    expect(md2).toContain("Price \\* 2 = \\_x\\_ \\<script\\>");
  });
});

describe("a table as CSV", () => {
  const table = toBlocks(answer, 2)[1] as Table;

  it("is UTF-8 with a byte order mark, semicolons and CRLF, with a last column naming the sources", () => {
    expect(tableToCsv(table, text)).toBe("﻿Name;Role;Price;Source\r\nJohn Smith;Seller;EUR 1,275,000.00;1, 2\r\n");
  });

  it("quotes cells with a semicolon, a quote or a line break", () => {
    const t = toBlocks('| A | B |\n| --- | --- |\n| one; two | say "yes" |', 0)[0] as Table;
    expect(tableToCsv(t, text).split("\r\n")[1]).toBe('"one; two";"say ""yes""";');
  });

  it("neutralises a cell that would run as a formula, but keeps negative numbers", () => {
    const t = toBlocks("| A | B | C | D |\n| --- | --- | --- | --- |\n| =1+1 | @SUM(A1) | -3,500.75 | +32 2 123 |", 0)[0] as Table;
    expect(tableToCsv(t, text).split("\r\n")[1]).toBe("'=1+1;'@SUM(A1);-3,500.75;+32 2 123;");
    const u = toBlocks("| A |\n| --- |\n| -cmd |", 0)[0] as Table;
    expect(tableToCsv(u, text).split("\r\n")[1]).toBe("'-cmd;");
  });
});
