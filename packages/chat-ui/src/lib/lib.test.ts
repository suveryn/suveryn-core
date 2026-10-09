import { describe, expect, it } from "vitest";
import { citedNumbers, stripMarkers, toBlocks } from "./answer";
import {
  formatSource, formatSourceMarkdown, formatSources, safeFileName, sourceFileName, sourcesDocument, sourcesMarkdown,
} from "./copy";
import { modelName } from "./model";
import { pageList, reviewHint } from "./review";
import { reviewPages } from "../api";
import { createSSEParser, type SSEEvent } from "./sse";

describe("SSE parser", () => {
  it("handles events split across chunks", () => {
    const got: SSEEvent[] = [];
    const p = createSSEParser((e) => got.push(e));
    p.feed('event: delta\ndata: {"text":"Een "}\n\nevent: del');
    p.feed('ta\ndata: {"text":"akte."}\n\nevent: done\ndata: {}\n\n');
    expect(got).toEqual([
      { event: "delta", data: '{"text":"Een "}' },
      { event: "delta", data: '{"text":"akte."}' },
      { event: "done", data: "{}" },
    ]);
  });
});

describe("answer rendering", () => {
  it("turns valid markers into citations and leaves invalid ones as text", () => {
    const [p] = toBlocks("De koopprijs is EUR 412.500,00 [1], zie ook [9].", 2);
    expect(p.segments).toEqual([
      { kind: "text", text: "De koopprijs is EUR 412.500,00 " },
      { kind: "cite", n: 1 },
      { kind: "text", text: ", zie ook [9]." },
    ]);
  });

  it("renders a heading the model already made bold without stray asterisks", () => {
    const [p] = toBlocks("### 📝 **Writing & Editing**", 0);
    expect(p.segments).toEqual([{ kind: "bold", text: "📝 Writing & Editing" }]);
  });

  it("renders list items, bold text and headings without HTML", () => {
    const blocks = toBlocks("## Partijen\n- **Verkoper**: A [2]\n- Koper <b>x</b>", 2);
    expect(blocks.map((b) => b.kind)).toEqual(["p", "li", "li"]);
    expect(blocks[0].segments).toEqual([{ kind: "bold", text: "Partijen" }]);
    expect(blocks[1].segments[0]).toEqual({ kind: "bold", text: "Verkoper" });
    expect(blocks[2].segments).toEqual([{ kind: "text", text: "Koper <b>x</b>" }]); // stays literal text
  });

  it("lists cited sources in order of first use", () => {
    expect(citedNumbers("a [2] b [1][2] c [5]", 3)).toEqual([2, 1]);
    expect(stripMarkers("Prijs EUR 10 [1]. Datum [2][3], ok")).toBe("Prijs EUR 10. Datum, ok");
  });
});

describe("model tag", () => {
  it("names served models without vendor logos or quantisation noise", () => {
    expect(modelName("Qwen3.8-27B-UD-Q4_K_M.gguf")).toEqual({ full: "Qwen3.8-27B", family: "Qwen" });
    expect(modelName("Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf")).toEqual({ full: "Mistral Small 3.2", family: "Mistral" });
    expect(modelName(null)).toBeNull();
  });
});

describe("copying sources", () => {
  const c = (text: string, page: number, location: string | null) =>
    ({ text, source: { document_id: "d", page, location } });

  it("puts the reference above the passage", () => {
    expect(formatSource(2, c("  De koopprijs bedraagt EUR 412.500,00.  ", 3, "p. 3 · Artikel 2"), "akte.pdf"))
      .toBe("[2] akte.pdf, p. 3 · Artikel 2\nDe koopprijs bedraagt EUR 412.500,00.");
  });

  it("falls back to the page and numbers several sources like the answer's markers", () => {
    expect(formatSources([{ n: 1, citation: c("A", 1, null), filename: "x.pdf" },
                          { n: 3, citation: c("B", 4, null), filename: "y.pdf" }]))
      .toBe("[1] x.pdf, p. 1\nA\n\n[3] y.pdf, p. 4\nB");
  });
});

describe("downloading sources", () => {
  it("makes safe, descriptive file names", () => {
    expect(sourceFileName(1, "Akte Zwaluw/straat 13.pdf", 3)).toBe("source-1_Akte_Zwaluw_straat_13_p3.txt");
    expect(safeFileName("Wat is de koopprijs?")).toBe("Wat_is_de_koopprijs");
    expect(safeFileName("???")).toBe("source");
  });

  it("puts the question and date above the sources", () => {
    const doc = sourcesDocument("Wat is de koopprijs?", "[1] akte.pdf, p. 2\nTekst", new Date(2026, 9, 9, 15, 30));
    expect(doc.split("\n").slice(0, 3)).toEqual(["Sources cited by Sūveryn", "Question: Wat is de koopprijs?", "Date: 9 October 2026 at 15:30"]);
    expect(doc).toContain("[1] akte.pdf, p. 2\nTekst");
  });
});

describe("Markdown downloads", () => {
  const cit = { text: "De koopprijs bedraagt\nEUR 412.500,00 *exclusief* kosten.", source: { document_id: "d", page: 2, location: "p. 2 · Artikel 2" } };

  it("quotes the passage under a reference heading, without altering the text", () => {
    expect(formatSourceMarkdown(1, cit, "akte.pdf"))
      .toBe("### [1] akte.pdf — p. 2 · Artikel 2\n\n> De koopprijs bedraagt\n> EUR 412.500,00 *exclusief* kosten.");
    expect(sourceFileName(1, "akte.pdf", 2, "md")).toBe("source-1_akte_p2.md");
  });

  it("heads the all-sources file with the question and date", () => {
    const md = sourcesMarkdown("Wat is de koopprijs?", [{ n: 1, citation: cit, filename: "akte.pdf" }], new Date(2026, 9, 9, 15, 30));
    expect(md.startsWith("# Sources cited by Sūveryn\n\n**Question:** Wat is de koopprijs?  \n**Date:** 9 October 2026 at 15:30\n\n### [1]")).toBe(true);
  });
});

describe("documents that need review", () => {
  it("lists the pages where text may be missing, once each and in order", () => {
    const w = (page: number | null, kind = "page_coverage_low") => ({ page, kind, detail: "" });
    expect(reviewPages([w(3), w(1), w(3), w(2, "furniture_restored"), w(null)])).toEqual([1, 3]);
    expect(reviewPages(undefined)).toEqual([]);
  });

  it("says the document is usable and where to check", () => {
    expect(pageList([1])).toBe("p. 1");
    expect(pageList([1, 3])).toBe("pp. 1, 3");
    expect(reviewHint([1])).toContain("Ready to use. Some text on page 1 may not");
    expect(reviewHint([1, 3])).toContain("on pages 1, 3");
    expect(reviewHint([])).toContain("on some pages");
  });
});
