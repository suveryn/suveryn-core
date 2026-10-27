import { describe, expect, it } from "vitest";
import { citedNumbers, stripMarkers, tableCells, toBlocks, type Block, type Segment, type Table } from "./answer";
import { cellValue, checkLines, segmentText, tableRows } from "./export";

import {
  formatSource, formatSourceMarkdown, formatSources, safeFileName, sourceFileName, sourcesDocument, sourcesMarkdown,
} from "./copy";
import { conversationHistory, HISTORY_CHARS } from "./history";
import { modelName } from "./model";
import { pageList, reviewHint } from "./review";
import { statusText } from "./status";
import { conversationTitle, dayLabel, fromSaved, newConversationId, toSaved, usesDocument, withoutDocument } from "./conversations";
import { rangeFor, today } from "./usage";
import { claimRedirect, LOOP_WINDOW_MS, shouldRedirect } from "./signin";
import { httpErrorText, reviewPages } from "../api";
import { setLang } from "../i18n";
import type { AssistantTurn, Turn, UserTurn } from "../types";
import { createSSEParser, type SSEEvent } from "./sse";

/** The segments of a text block (paragraph or list item). */
const segs = (b: Block): Segment[] => (b.kind === "table" ? [] : b.segments);

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
    expect(segs(p)).toEqual([
      { kind: "text", text: "De koopprijs is EUR 412.500,00 " },
      { kind: "cite", n: 1, occ: 0 },
      { kind: "text", text: ", zie ook [9]." },
    ]);
  });

  it("renders a heading the model already made bold without stray asterisks", () => {
    const [p] = toBlocks("### 📝 **Writing & Editing**", 0);
    expect(segs(p)).toEqual([{ kind: "bold", text: "📝 Writing & Editing" }]);
  });

  it("renders list items, bold text and headings without HTML", () => {
    const blocks = toBlocks("## Partijen\n- **Verkoper**: A [2]\n- Koper <b>x</b>", 2);
    expect(blocks.map((b) => b.kind)).toEqual(["p", "li", "li"]);
    expect(segs(blocks[0])).toEqual([{ kind: "bold", text: "Partijen" }]);
    expect(segs(blocks[1])[0]).toEqual({ kind: "bold", text: "Verkoper" });
    expect(segs(blocks[2])).toEqual([{ kind: "text", text: "Koper <b>x</b>" }]); // stays literal text
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
    // router-mode ids (suveryn-tracker#4)
    expect(modelName("qwen3.8-27b")).toEqual({ full: "Qwen3.8-27B", family: "Qwen" });
    expect(modelName("mistral-small-3.2-24b")).toEqual({ full: "Mistral Small 3.2", family: "Mistral" });
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
    expect(safeFileName("A table of the parties, with their role.")).toBe("A_table_of_the_parties_with_their_role");  // no "..md"
    expect(safeFileName("...hidden")).toBe("hidden");
  });

  it("puts the question and date above the sources", () => {
    const doc = sourcesDocument("Wat is de koopprijs?", "[1] akte.pdf, p. 2\nTekst", new Date(2026, 9, 9, 15, 30));
    expect(doc.split("\n").slice(0, 3)).toEqual(["Sources cited by sūveryn", "Question: Wat is de koopprijs?", "Date: 9 October 2026 at 15:30"]);
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
    expect(md.startsWith("# Sources cited by sūveryn\n\n**Question:** Wat is de koopprijs?  \n**Date:** 9 October 2026 at 15:30\n\n### [1]")).toBe(true);
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

describe("conversation history", () => {
  it("leaves out a question whose answer failed, so roles alternate", () => {
    const turns = [
      { id: "1", role: "user", text: "Vraag 1", attachments: [] },
      { id: "2", role: "assistant", text: "Antwoord [1].", citations: [], status: "done", grounded: true },
      { id: "3", role: "user", text: "Vraag 2", attachments: [] },
      { id: "4", role: "assistant", text: "", citations: [], status: "error", grounded: true, error: "x" },
    ] as Turn[];
    expect(conversationHistory(turns)).toEqual([
      { role: "user", content: "Vraag 1" },
      { role: "assistant", content: "Antwoord [1]." },  // with its marker: the server makes it [*]
    ]);
  });
});

describe("product name", () => {
  it("is lower case mid-sentence: sūveryn, not Sūveryn", async () => {
    const { readFileSync, readdirSync } = await import("node:fs");
    const files = ["src/App.tsx", "src/lib/copy.ts", ...readdirSync("src/components").map((f) => `src/components/${f}`)];
    for (const f of files) {
      const code = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, ""); // comments are not copy
      for (const m of code.matchAll(/Sūveryn/g)) {
        const before = code.slice(Math.max(0, m.index! - 2), m.index);
        expect(`${f}: ${before}Sūveryn`).toMatch(/(["'`>]\s*|[.!?:]\s)Sūveryn$/);
      }
    }
  });
});

describe("model picker", () => {
  const models = [
    { id: "mistral-small-3.2-24b", loaded: false, default: false },
    { id: "qwen3.8-27b", loaded: true, default: true },
  ];
  it("answers with the default until another model is chosen", async () => {
    const { defaultModel } = await import("../components/ModelPicker");
    expect(defaultModel(models)?.id).toBe("qwen3.8-27b");
  });
  it("says when the chosen model has to load first, and that others wait too", async () => {
    const { loadingNote } = await import("../components/ModelPicker");
    expect(loadingNote(models, null)).toBeNull();
    expect(loadingNote(models, "mistral-small-3.2-24b")).toMatch(/^Mistral Small 3\.2 isn't loaded yet: .*other people's questions wait/);
  });
});

describe("waiting status (suveryn-tracker#6)", () => {
  const st = (o: object) => ({ step: "writing", passages: null, complete: null, model: null, ...o }) as never;
  it("names the real pipeline step", () => {
    expect(statusText(st({ step: "searching" }))).toBe("Searching your documents…");
    expect(statusText(st({ step: "reading", passages: 6, complete: false }))).toBe("Reading the 6 passages that best match your question…");
    expect(statusText(st({ step: "reading", passages: 1, complete: true }))).toBe("Reading your documents (1 passage)…");
    expect(statusText(st({ step: "loading_model", model: "mistral-small-3.2-24b" })))
      .toBe("Loading Mistral Small 3.2, which can take up to half a minute…");
    expect(statusText(st({ step: "writing" }))).toBe("Writing the answer…");
  });
  it("never says something vague", () => {
    expect(statusText(undefined)).toBeNull();
    for (const step of ["searching", "reading", "loading_model", "writing"])
      expect(statusText(st({ step }))).not.toMatch(/thinking/i);
  });
});

describe("saved conversations (suveryn-tracker#5)", () => {
  const turns: Turn[] = [
    { id: "a", role: "user", text: "  Wat is\n de koopprijs?  ", attachments: [{ key: "k", filename: "akte.pdf", status: "ready", documentId: "d", progress: 1 }] },
    { id: "b", role: "assistant", text: "€ 345.000 [1]", citations: [], status: "done", grounded: true,
      step: { step: "writing", passages: null, complete: null, model: null } },
  ];
  it("makes random v4 UUIDs", () => {
    const id = newConversationId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newConversationId()).not.toBe(id);
  });
  it("names a conversation after its first question", () => {
    expect(conversationTitle(turns)).toBe("Wat is de koopprijs?");
    expect(conversationTitle([{ ...turns[0], text: "x".repeat(120) } as Turn])).toHaveLength(80);
    expect(conversationTitle([])).toBe("Conversation");
  });
  it("saves without streaming and upload state, and restores interrupted answers as errors", () => {
    const saved = toSaved(turns);
    expect(saved[0].role === "user" && saved[0].attachments[0]).not.toHaveProperty("progress");
    expect(saved[1]).not.toHaveProperty("step");
    const back = fromSaved([turns[0], { ...turns[1], status: "streaming" } as Turn]);
    expect(back[1]).toMatchObject({ status: "error", text: "", error: "This answer was interrupted." });
  });
  it("dates conversations in UK style", () => {
    const now = new Date(2026, 9, 10, 14, 0);
    expect(dayLabel(new Date(2026, 9, 10, 9, 0).toISOString(), now)).toBe("Today");
    expect(dayLabel(new Date(2026, 9, 9, 23, 0).toISOString(), now)).toBe("Yesterday");
    expect(dayLabel(new Date(2026, 9, 3).toISOString(), now)).toBe("3 Oct");
    expect(dayLabel(new Date(2025, 11, 24).toISOString(), now)).toBe("24 Dec 2025");
  });
});

describe("figures to check (unverified_figures)", () => {
  it("marks each flagged figure, also in bold, and only as a whole number", () => {
    const [b] = toBlocks("Samen 350.000,00 EUR, of **350.000,00 EUR**; niet 1.350.000,00 [1].", 1, ["350.000,00"]);
    expect(segs(b)).toEqual([
      { kind: "text", text: "Samen " },
      { kind: "flag", text: "350.000,00", bold: false },
      { kind: "text", text: " EUR, of " },
      { kind: "flag", text: "350.000,00", bold: true },
      { kind: "bold", text: " EUR" },
      { kind: "text", text: "; niet 1.350.000,00 " },
      { kind: "cite", n: 1, occ: 0 },
      { kind: "text", text: "." },
    ]);
  });
  it("leaves text alone without flags", () => {
    expect(segs(toBlocks("Samen 350.000,00 EUR.", 0)[0])).toEqual([{ kind: "text", text: "Samen 350.000,00 EUR." }]);
  });
});

describe("usage periods (suveryn-tracker#7)", () => {
  const now = new Date(2026, 9, 10, 14, 30);
  it("presets are rolling windows ending now", () => {
    expect(rangeFor("hour", now)).toEqual({ start: new Date(2026, 9, 10, 13, 30) }); // ends at the server's "now"
    expect(rangeFor("week", now)!.start).toEqual(new Date(now.getTime() - 7 * 24 * 3_600_000));
  });
  it("a custom period covers whole local days, both ends included", () => {
    expect(rangeFor("custom", now, "2026-10-01", "2026-10-03")).toEqual({ start: new Date(2026, 9, 1), end: new Date(2026, 9, 4) });
    expect(rangeFor("custom", now, "2026-10-03", "2026-10-01")).toBeNull();
    expect(rangeFor("custom", now, "", "2026-10-01")).toBeNull();
  });
  it("today starts at local midnight", () => {
    expect(today(now)).toEqual({ start: new Date(2026, 9, 10) });
  });
});

describe("straight to the login page", () => {
  it("redirects, but not again within a minute (a sign-in that didn't complete would loop)", () => {
    expect(shouldRedirect(1_000_000, null)).toBe(true);
    expect(shouldRedirect(1_000_000, 1_000_000 - 5_000)).toBe(false);
    expect(shouldRedirect(1_000_000, 1_000_000 - LOOP_WINDOW_MS - 1)).toBe(true);
  });
});

describe("one redirect per page load", () => {
  it("a second call in the same page (React StrictMode runs effects twice) is not a loop", () => {
    expect(claimRedirect(2_000_000)).toBe("go");
    expect(claimRedirect(2_000_001)).toBe("started"); // not "stuck": no sign-in screen flash
  });
});

describe("citations checked against their source (suveryn-tracker#11)", () => {
  it("numbers valid markers across the answer as the server does, also in bold and list items", () => {
    const blocks = toBlocks("- **Verkoper** [1]: Jan Peeters [9]\n- **Prijs [2]**: 410.000,00 EUR [2]", 2);
    const cites = blocks.flatMap((b) => segs(b)).filter((s) => s.kind === "cite");
    expect(cites).toEqual([{ kind: "cite", n: 1, occ: 0 }, { kind: "cite", n: 2, occ: 1 }, { kind: "cite", n: 2, occ: 2 }]);
    expect(segs(blocks[1])[0]).toEqual({ kind: "bold", text: "Prijs " });  // the marker in bold is a marker now
  });
});

describe("deleted documents (suveryn-tracker#12)", () => {
  const DOC = "11111111-1111-4111-8111-111111111111";
  const turns: Turn[] = [
    { id: "u", role: "user", text: "Prijs?", attachments: [{ key: "a", filename: "akte-peeters.pdf", status: "ready", documentId: DOC }] },
    { id: "a", role: "assistant", text: "€ 345.000 [1] [2]", status: "done", grounded: true, citations: [
      { text: "De koopprijs bedraagt € 345.000.", source: { document_id: DOC, page: 3, location: "p. 3 · Artikel 2" } },
      { text: "Verkoper: Jan Peeters.", source: { document_id: "other", page: 1, location: "p. 1" } }] },
  ];

  it("takes the document's passages and file name out, as the server does, and keeps the rest", () => {
    expect(usesDocument(turns, DOC)).toBe(true);
    const cleaned = withoutDocument(turns, DOC);
    expect(usesDocument(cleaned, "missing")).toBe(false);
    const [user, answer] = cleaned as [UserTurn, AssistantTurn];
    expect(user.attachments[0]).toMatchObject({ filename: "", removed: true });
    expect(answer.citations[0]).toEqual({ text: "", source: { document_id: DOC, page: 3, location: null }, removed: true });
    expect(answer.citations[1].text).toBe("Verkoper: Jan Peeters.");
    expect(answer.text).toBe("€ 345.000 [1] [2]");
  });
});

describe("tables in answers (Word and Excel)", () => {
  const answer = "Hier zijn de partijen:\n\n| Nr | Naam | Rol | Bedrag |\n| :--- | :--- | :---: | ---: |\n" +
    "| 1 | Jan Peeters [1] | Verkoper | EUR 1.275.000,00 [2] |\n| 2 | Marie A \\| B [3] | Koper |\n\nAlles is gecontroleerd [1].";

  it("reads a Markdown table, with alignment, escaped pipes, short rows and markers counted in order", () => {
    const blocks = toBlocks(answer, 3);
    expect(blocks.map((b) => b.kind)).toEqual(["p", "table", "p"]);
    const t = blocks[1] as Table;
    expect(t.align).toEqual(["left", "left", "center", "right"]);
    expect(t.header.map((c) => segmentText(c))).toEqual(["Nr", "Naam", "Rol", "Bedrag"]);
    expect(t.rows[1].map((c) => segmentText(c))).toEqual(["2", "Marie A | B [3]", "Koper", ""]);  // padded to the header
    const occ = blocks.flatMap((b) => (b.kind === "table" ? [...b.header, ...b.rows.flat()].flat() : b.segments))
      .filter((x) => x.kind === "cite").map((x) => (x.kind === "cite" ? [x.n, x.occ] : []));
    expect(occ).toEqual([[1, 0], [2, 1], [3, 2], [1, 3]]);  // as the server counts for citation_issues
    expect(tableCells("| a | b |")).toEqual(["a", "b"]);
  });

  it("gives each row its sources, in a last column", () => {
    const t = toBlocks(answer, 3)[1] as Table;
    expect(tableRows(t, "Bron")).toEqual({
      header: ["Nr", "Naam", "Rol", "Bedrag", "Bron"],
      rows: [{ cells: ["1", "Jan Peeters", "Verkoper", "EUR 1.275.000,00"], sources: [1, 2] },
             { cells: ["2", "Marie A | B", "Koper", ""], sources: [3] }],
    });
  });

  it("leaves out the model's own column of source markers: the sources column has them", () => {
    const t = toBlocks("| Bedrag | Omschrijving | Bron |\n| --- | --- | --- |\n| EUR 48.200,00 | Achterstand | [2] |\n| EUR 25.000,00 | Boete | [2][3] |", 3)[0] as Table;
    expect(tableRows(t, "Bron")).toEqual({ header: ["Bedrag", "Omschrijving", "Bron"],
      rows: [{ cells: ["EUR 48.200,00", "Achterstand"], sources: [2] }, { cells: ["EUR 25.000,00", "Boete"], sources: [2, 3] }] });
  });

  it.each([
    ["EUR 1.275.000,00", 1275000, '"€" #,##0.00'],
    ["€ 48.200", 48200, '"€" #,##0.00'],
    ["1.275.000", 1275000, "#,##0"],
    ["12,5", 12.5, "#,##0.0"],
    ["1,275,000.00", 1275000, "#,##0.00"],
    ["25 %", 0.25, "0%"],
    ["4182", 4182, "0"],
    ["-3.500,75", -3500.75, "#,##0.00"],
  ])("makes %s a number", (text, value, format) => {
    expect(cellValue(text)).toEqual({ value, format });
  });

  it.each(["1.275", "1,275", "0123", "12/03/2021", "15 januari 2027", "sectie K nummer 4182", "BE 0123.456.789", ""])(
    "keeps %s as text: ambiguous or not one number", (text) => {
      expect(cellValue(text)).toEqual({ value: text.trim() });
    });

  it("lists what to check: calculations, figures and citations, each once", () => {
    const m = { calcFailed: (e: string) => `fail ${e}`, calculatedBy: "Calc:", calcMissing: (f: string[]) => ` missing ${f}`,
                unverified: (f: string[]) => `check ${f}`, citationIssue: (n: number, item: string) => `source ${n} lacks ${item}` };
    const issue = { marker: 0, n: 2, item: "X", found_in: [3], written_as: null };
    expect(checkLines([{ expression: "1 + 1", result: "2", figures_not_in_sources: [], error: null }], ["9"], [issue, { ...issue, marker: 4 }], m))
      .toEqual(["Calc: 1 + 1 = 2.", "check 9", "source 2 lacks X"]);
  });
});

describe("server errors and long conversations", () => {
  it("says what went wrong in the interface's language, not as HTTP codes", () => {
    setLang("nl", false);
    expect(httpErrorText(429, "Too many requests. Try again in 12 seconds.", "12")).toBe("te veel verzoeken; probeer het over 12 seconden opnieuw");
    expect(httpErrorText(422, [{ loc: ["body", "messages"], msg: "too long" }])).toBe("de server kon dit verzoek niet aanvaarden");  // was "HTTP 422"
    expect(httpErrorText(413, "This conversation is too long to save.")).toMatch(/^dit gesprek is te lang/);
    expect(httpErrorText(413, "The file is larger than 100 MB.")).toMatch(/^het bestand is groter/);
    expect(httpErrorText(418, "I'm a teapot")).toBe("I'm a teapot");  // others keep the server's text
    // Which part is down, when the gateway says (Pod check of cbccd38)
    expect(httpErrorText(503, "The database can't be reached right now.", null, "database")).toMatch(/^de database op deze server is nu niet bereikbaar/);
    expect(httpErrorText(503, "Sign-in is not available: …", null, "signin")).toMatch(/^de inlogdienst op deze server antwoordt nu niet/);
    expect(httpErrorText(503, "Document search is unavailable.")).toBe("dit deel van de server is nu niet beschikbaar; probeer het later opnieuw");
    setLang("en", false);
  });

  it("sends at most the last 40 messages of a long conversation, starting with a question", () => {
    const turns = Array.from({ length: 150 }, (_, i) => [
      { id: `q${i}`, role: "user", text: `vraag ${i}`, attachments: [] },
      { id: `a${i}`, role: "assistant", text: `antwoord ${i}`, citations: [], status: "done" },
    ]).flat() as never[];
    const sent = conversationHistory(turns);
    expect(sent).toHaveLength(40);
    expect(sent[0]).toEqual({ role: "user", content: "vraag 130" });
    expect(sent.at(-1)).toEqual({ role: "assistant", content: "antwoord 149" });
  });

  it("drops the oldest pairs when the earlier turns are too long to send (audit of 21 October, finding 6)", () => {
    const long = "x".repeat(25_000);
    const turns = Array.from({ length: 4 }, (_, i) => [
      { id: `q${i}`, role: "user", text: `question ${i}`, attachments: [] },
      { id: `a${i}`, role: "assistant", text: `${i}${long}`, citations: [], status: "done" },
    ]).flat() as never[];
    const sent = conversationHistory(turns);
    expect(sent.map((x) => x.content.slice(0, 10))).toEqual(["question 2", `2${"x".repeat(9)}`, "question 3", `3${"x".repeat(9)}`]);
    expect(sent.reduce((n, x) => n + x.content.length, 0)).toBeLessThanOrEqual(HISTORY_CHARS);
  });
});

// ---------------------------------------------------------------- origin: source or made (docs/design/sidebar.md §6)
import { exportRef } from "./marks";
import { originKind, originText } from "./origin";
import { TABLES_FOR_TESTS } from "../i18n";

describe("sūveryn's own output (docs/design/sidebar.md §6)", () => {
  it("an export reference is stable, short and of its kind", () => {
    expect(exportRef("A", "t1-2")).toMatch(/^A-[0-9a-f]{8}$/);
    expect(exportRef("A", "t1-2")).toBe(exportRef("A", "t1-2"));
    expect(exportRef("A", "t1-2")).not.toBe(exportRef("A", "t1-3"));
    expect(exportRef("P", "run")).toMatch(/^P-[0-9a-f]{8}$/);
  });

  it("the mark line carries the reference the server looks for, in every language", () => {
    // the same expression as suveryn_rag.marks.REF, after accents are removed
    const REF = /suveryn-ref[\s:]*([AP])-([0-9a-f]{8})\b/i;
    for (const m of Object.values(TABLES_FOR_TESTS)) {
      const line = m.exportMark("answer", "2026/0611", "19-10-2026", "A-3f9c2e1b").normalize("NFKD").replace(/\p{M}/gu, "");
      expect(line.match(REF)?.slice(1)).toEqual(["A", "3f9c2e1b"]);
    }
  });

  it("origin: uploads are sources, sūveryn's output is made, a noticed upload waits for a person", () => {
    const m = TABLES_FOR_TESTS.en;
    const noticed = { ref: "A-3f9c2e1b", kind: "answer" as const, line: "…" };
    expect(originText({ origin: "uploaded", source: true }, m)).toEqual({ word: "Source", detail: "uploaded" });
    expect(originText({ origin: "playbook", source: false, provenance: { version: "1.0" } }, m)).toEqual({ word: "Made", detail: "playbook v1.0" });
    expect(originKind({ origin: "uploaded", source: false, provenance: { noticed } })).toBe("pending");
    expect(originText({ origin: "uploaded", source: true, provenance: { noticed, confirmed: { by: "a", at: "" } } }, m))
      .toEqual({ word: "Source", detail: "uploaded, was an answer" });
  });
});

describe("attachment cards (docs/design/sidebar.md §5)", () => {
  it("says why an upload failed without the exception's name", async () => {
    const { failureReason } = await import("./review");
    expect(failureReason("ValueError: the file is not a valid Word file")).toBe("The file is not a valid Word file.");
    expect(failureReason("the file is too large.")).toBe("The file is too large.");
    expect(failureReason(undefined)).toBe("");
  });

  it("keeps a document still being read, or one that failed, in the composer when a question is sent", async () => {
    const { staysInComposer } = await import("../types");
    const card = (status: string) => ({ key: status, filename: "a.pdf", status }) as Parameters<typeof staysInComposer>[0];
    expect(["uploading", "queued", "processing", "failed"].map((s) => staysInComposer(card(s)))).toEqual([true, true, true, true]);
    expect(["ready", "needs_review", "noticed"].map((s) => staysInComposer(card(s)))).toEqual([false, false, false]);
  });
});

describe("why an upload couldn't be read, in the interface's language (suveryn_rag.reading)", () => {
  it("says the reader's code in words, with its numbers", async () => {
    const { failureText } = await import("./review");
    const { setLang, t } = await import("../i18n");
    setLang("nl", false);
    expect(failureText(t(), "password")).toBe("Het is beveiligd met een wachtwoord.");
    expect(failureText(t(), "too_many_pages", { pages: 900, max: 500 })).toBe("Het heeft 900 pagina's; er kunnen er hoogstens 500 gelezen worden.");
    expect(failureText(t(), "timeout", { minutes: 30 })).toBe("Lezen duurde langer dan 30 minuten.");
    setLang("en", false);
    expect(failureText(t(), undefined, {}, "ValueError: the file is not a valid Word file")).toBe("The file is not a valid Word file.");  // no code: the server's words
    expect(failureText(t(), "something-new", {}, "boom")).toBe("Boom.");
  });
});
