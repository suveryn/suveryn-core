/**
 * Turns an answer's text into blocks (paragraphs, list items) of inline segments: plain text,
 * bold text, and citation markers. Marker [n] refers to citations[n - 1] (the backend's
 * positional citation contract). Rendering goes through React, so model output is never
 * injected as HTML.
 */

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "cite"; n: number; occ: number } // occ: the marker's place among the answer's valid markers (0-based)
  | { kind: "flag"; text: string; bold: boolean }; // a figure to check (ChatResponse.unverified_figures)

type Align = "left" | "center" | "right" | null;
/** A Markdown table: header cells, rows of cells, column alignment. Cells are segments like any text. */
export type Table = { kind: "table"; header: Segment[][]; rows: Segment[][][]; align: Align[] };
export type Block = { kind: "p" | "li"; segments: Segment[] } | Table;

const TABLE_SEPARATOR = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/;

/** The cells of a Markdown table row: outer pipes dropped, split on pipes not escaped as \|. */
export function tableCells(line: string): string[] {
  const inner = line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "");
  return inner.split(/(?<!\\)\|/).map((c) => c.trim().replaceAll("\\|", "|"));
}

function alignOf(cell: string): Align {
  const c = cell.trim();
  return c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : c.startsWith(":") ? "left" : null;
}

const MARKER = /\[(\d{1,2})\]/g;

/** Marker numbers used in the text that point at an existing citation, in order of first use. */
export function citedNumbers(text: string, available: number): number[] {
  const seen: number[] = [];
  for (const m of text.matchAll(MARKER)) {
    const n = Number(m[1]);
    if (n >= 1 && n <= available && !seen.includes(n)) seen.push(n);
  }
  return seen;
}

/** The warning about text aimed at an AI, as the answer can show it: the flagged passages this answer cites, by
 *  their numbers, or, when it cites none of them, the warning without a number (pod round of aebf5bc, finding 3:
 *  "Source 13 contains…" under an answer whose sources were 2 and 6). Null when nothing was flagged. */
export function instructionLikeWarning(flagged: number[] | undefined, text: string, available: number,
                                       m: { instructionLike: (s: number[]) => string; instructionLikeUncited: string }): string | null {
  if (!flagged?.length) return null;
  const cited = citedNumbers(text, available).filter((n) => flagged.includes(n)).sort((a, b) => a - b);
  return cited.length ? m.instructionLike(cited) : m.instructionLikeUncited;
}

/**
 * Splits on **bold** first, then on [n] markers in every piece, bold ones included (they used to stay
 * as text). ``counter`` numbers the valid markers across the whole answer, as the server does for
 * ``citation_issues`` (suveryn-tracker#11), so a flag lands on the right marker.
 */
function inline(text: string, available: number, counter: { occ: number }): Segment[] {
  const out: Segment[] = [];
  text.split(/(\*\*[^*]+\*\*)/g).forEach((piece) => {
    if (!piece) return;
    const bold = piece.startsWith("**") && piece.endsWith("**") && piece.length > 4;
    const body = bold ? piece.slice(2, -2) : piece;
    const kind = bold ? "bold" : "text";
    let last = 0;
    for (const m of body.matchAll(MARKER)) {
      const n = Number(m[1]);
      if (n < 1 || n > available) continue; // not a valid marker: leave it as text
      if (m.index! > last) out.push({ kind, text: body.slice(last, m.index) });
      out.push({ kind: "cite", n, occ: counter.occ++ });
      last = m.index! + m[0].length;
    }
    if (last < body.length) out.push({ kind, text: body.slice(last) });
  });
  return out;
}

/** Splits text and bold segments around the flagged figures, matched as whole numbers. */
function flagFigures(segments: Segment[], flagged: string[]): Segment[] {
  if (flagged.length === 0) return segments;
  const escaped = flagged.map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(?<![\\d.,])(?:${escaped.join("|")})(?![\\d]|[.,]\\d)`, "g");
  return segments.flatMap((s): Segment[] => {
    if (s.kind !== "text" && s.kind !== "bold") return [s];
    const bold = s.kind === "bold";
    const out: Segment[] = [];
    let last = 0;
    for (const m of s.text.matchAll(pattern)) {
      if (m.index! > last) out.push({ kind: s.kind, text: s.text.slice(last, m.index) });
      out.push({ kind: "flag", text: m[0], bold });
      last = m.index! + m[0].length;
    }
    if (last < s.text.length) out.push({ kind: s.kind, text: s.text.slice(last) });
    return out;
  });
}

export function toBlocks(text: string, available: number, flagged: string[] = []): Block[] {
  const blocks: Block[] = [];
  const counter = { occ: 0 };
  const lines = text.split("\n");
  const cells = (l: string) => tableCells(l).map((c) => flagFigures(inline(c, available, counter), flagged));
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    // A table: a row with pipes followed by a separator row (| --- | :--: |), then rows with pipes.
    if (line.includes("|") && TABLE_SEPARATOR.test(lines[i + 1]?.trim() ?? "")) {
      const width = tableCells(line).length;
      const table: Table = { kind: "table", header: cells(line), rows: [], align: tableCells(lines[i + 1]).map(alignOf) };
      i += 1;
      while (i + 1 < lines.length && lines[i + 1].trim().includes("|")) {
        i += 1;
        const row = cells(lines[i]);
        while (row.length < width) row.push([]);
        table.rows.push(row.slice(0, width));
      }
      blocks.push(table);
      continue;
    }
    const item = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (item) blocks.push({ kind: "li", segments: flagFigures(inline(item[1], available, counter), flagged) });
    else blocks.push({ kind: "p", segments: flagFigures(inline(heading ? `**${heading[1].replaceAll("**", "")}**` : line, available, counter), flagged) });
  }
  return blocks;
}

/** Marker-free text, for sending earlier turns back as conversation history. */
export function stripMarkers(text: string): string {
  return text.replace(MARKER, "").replace(/[ \t]+([.,;:])/g, "$1");
}

/**
 * Per valid marker, in the order ``toBlocks`` numbers them (``Segment.occ``): its source and the claim before it.
 * A click on one marker shows what that claim rests on, not every claim citing the source (reported: a table of
 * 11 rows citing one source marked most of it, where the clicked row's sentence was expected).
 */
export function markerClaims(text: string, available: number): { n: number; claim: string }[] {
  const out: { n: number; claim: string }[] = [];
  for (const sentence of answerSentences(text)) {
    let start = 0;
    for (const group of sentence.matchAll(/(?:\[\d{1,2}\])+/g)) {
      const claim = cleanClaim(sentence.slice(start, group.index));
      start = group.index! + group[0].length;
      for (const n of group[0].match(/\d{1,2}/g)!.map(Number)) if (n >= 1 && n <= available) out.push({ n, claim });
    }
  }
  return out;
}

// Abbreviations whose full stop doesn't end a sentence (legal and everyday Dutch, French and English; language data,
// like the translation tables). A single capital is an initial ("J. Peeters").
const ABBREVIATIONS = new Set(("art artt nr nrs no nos n° bv b.v vb zgn enz e.a e.g i.e cf vgl al par hfst hfdst afd blz p pp ca resp " +
  "dhr mevr mr mme mlle me dr prof st ste ir ing lic jr sr vs viz approx fig tab vol " +
  "jan feb febr mrt apr jun jul aug sep sept okt oct nov dec").split(" "));

/** Whether the full stop just before ``at`` closes an abbreviation or an initial rather than a sentence. */
function abbreviated(text: string, at: number): boolean {
  if (text[at - 1] !== ".") return false;
  const word = /(?<![\p{L}°.])([\p{L}°][\p{L}°.]*)\.$/u.exec(text.slice(Math.max(0, at - 40), at))?.[1];
  return !!word && (ABBREVIATIONS.has(word.toLowerCase()) || /^\p{Lu}$/u.test(word));
}

/** An answer's sentences: split after . ! ? (not after an abbreviation: "art. 3") and at line ends. */
export function answerSentences(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  for (const b of text.matchAll(/(?<=[.!?])\s+|\n+/g)) {
    if (!b[0].includes("\n") && abbreviated(text, b.index!)) continue;
    out.push(text.slice(start, b.index));
    start = b.index! + b[0].length;
  }
  out.push(text.slice(start));
  return out;
}

const cleanClaim = (claim: string) => claim.replace(/\*\*/g, "").replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").trim();

export type PassagePart = { text: string; mark: "sentence" | "term" | null };

/** A passage with the server's marking (``SupportSpan``): its sentences, and its facts marked strongly. Offsets out of
 *  the passage's bounds are clipped. */
export function spanParts(passage: string, spans: { ranges: [number, number][]; facts: [number, number][] }[]): PassagePart[] {
  const mark: PassagePart["mark"][] = new Array(passage.length).fill(null);
  const fill = (kind: "sentence" | "term", [a, z]: [number, number]) => mark.fill(kind, Math.max(0, a), Math.min(passage.length, z));
  for (const s of spans) s.ranges.forEach((r) => fill("sentence", r));
  for (const s of spans) s.facts.forEach((r) => fill("term", r));
  return partsOf(passage, mark);
}

function partsOf(passage: string, mark: PassagePart["mark"][]): PassagePart[] {
  const out: PassagePart[] = [];
  for (let i = 0; i < passage.length; i++) {
    if (out.length && out[out.length - 1].mark === mark[i]) out[out.length - 1].text += passage[i];
    else out.push({ text: passage[i], mark: mark[i] });
  }
  return out;
}
