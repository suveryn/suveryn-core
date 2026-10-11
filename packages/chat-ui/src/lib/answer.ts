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

export type Align = "left" | "center" | "right" | null;
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

// A name: capitalised words with lower-case particles between them (van, de, der, ter, du, le, d', ...).
const PARTICLE = "(?:van|von|de|der|den|het|ter|ten|te|op|in|'t|du|des|le|la|les|di|da|del|della|d'|l')";
// d' and l' can be attached ("Charlotte d'Hondt").
const NAME_WORD = "(?:[dDlL]['’])?[A-ZÀ-Þ][\\p{L}'’-]+";
const NAME = new RegExp(`${NAME_WORD}(?:\\s+(?:${PARTICLE}\\s+)*${NAME_WORD})*`, "gu");

/**
 * What to look for in each cited source: per source number, the figures, years, dates and names of the
 * claims that cite it (the text before each marker group, back to the previous group or the start of the
 * sentence, as the server's citation check reads claims). The source card marks them and scrolls to the
 * first, so a fact can be found in a long passage (a year near the end of a 3,000-character passage was
 * out of view and seemed to be missing).
 */
export function claimTerms(text: string, available: number): Map<number, string[]> {
  const out = new Map<number, string[]>();
  for (const sentence of text.split(/(?<=[.!?])\s+|\n+/)) {
    let start = 0;
    for (const group of sentence.matchAll(/(?:\[\d{1,2}\])+/g)) {
      const claim = sentence.slice(start, group.index).replace(/\*\*/g, "");
      start = group.index! + group[0].length;
      const terms = [
        ...claim.matchAll(/\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d+(?:[.,  ]\d+)+|\b(?:1[89]|20)\d\d\b|\d{5,}/g),
      ].map((m) => m[0]);
      // Whole names ("Eric Van de Plas": "Van" and "de" were left unmarked), also at the start of a claim,
      // only for a claim without figures, years or dates: those are what it says, and a capitalised word
      // ("Europese") isn't always a name. A single capitalised word only when it isn't the claim's first
      // word (capitalised anyway) and has 4+ letters.
      const names = terms.length ? [] : [...claim.matchAll(NAME)].map((m) => ({ text: m[0], at: m.index! }));
      for (const n of names) {
        const several = /\s/.test(n.text);
        if ((several || (n.at > 0 && n.text.length >= 4)) && !terms.includes(n.text)) terms.push(n.text);
        // At the start of a claim the first word may be a title ("Notaris Charlotte d'Hondt"), which the source
        // may write elsewhere: the name without it too. Marking tries the longest first.
        const rest = n.text.replace(/^\S+\s+/, "");
        if (several && n.at === 0 && /\s/.test(rest) && !terms.includes(rest)) terms.push(rest);
      }
      for (const n of group[0].match(/\d{1,2}/g)!.map(Number)) {
        if (n < 1 || n > available) continue;
        const known = out.get(n) ?? [];
        out.set(n, [...known, ...terms.filter((t) => !known.includes(t))]);
      }
    }
  }
  return out;
}

/** Per source number, the claims (sentence parts before a marker group) that cite it. */
export function claimTexts(text: string, available: number): Map<number, string[]> {
  const out = new Map<number, string[]>();
  for (const sentence of text.split(/(?<=[.!?])\s+|\n+/)) {
    let start = 0;
    for (const group of sentence.matchAll(/(?:\[\d{1,2}\])+/g)) {
      const claim = sentence.slice(start, group.index).replace(/\*\*/g, "").replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").trim();
      start = group.index! + group[0].length;
      if (!claim) continue;
      for (const n of group[0].match(/\d{1,2}/g)!.map(Number)) {
        if (n >= 1 && n <= available && !(out.get(n) ?? []).includes(claim)) out.set(n, [...(out.get(n) ?? []), claim]);
      }
    }
  }
  return out;
}

// Words that say nothing about which sentence a claim comes from (Dutch, French, English).
const STOP = new Set(("de het een en van in op te voor met aan is zijn was werd wordt worden door bij als dat die dit deze om tot " +
  "uit naar ook niet maar of er over na hij zij ze we wij u uw hun haar zijn heeft hebben had kan zal zou moet " +
  "le la les un une des du et en au aux est sont par pour sur dans que qui avec ce cette ces il elle " +
  "the a an and of in on to for with is are was were by as that this these from at it be has have").split(" "));

/** The comparable words and numbers of a text: numbers without separators (1.275.000,00 = 1 275 000). */
function tokens(text: string): { words: Set<string>; numbers: Set<string> } {
  const numbers = new Set([...text.matchAll(/\d+(?:[.,  ]\d+)*/g)].map((m) => m[0].replace(/[.,]0{1,2}$/, "").replace(/\D/g, "")));
  const words = new Set([...text.toLowerCase().matchAll(/[\p{L}]{3,}/gu)].map((m) => m[0]).filter((w) => !STOP.has(w)));
  return { words, numbers };
}

/** The passage's sentences as [start, end) ranges: split after . ! ? ; before a capital, digit or quote, and at line breaks. */
function sentenceRanges(passage: string): [number, number][] {
  const out: [number, number][] = [];
  let start = 0;
  for (const b of passage.matchAll(/(?<=[.!?;:])\s+(?=[\p{Lu}\d“"'(])|\n\s*\n|\n(?=\s*(?:[-*•▪]|\d+[.)])\s)/gu)) {
    out.push([start, b.index!]);
    start = b.index! + b[0].length;
  }
  out.push([start, passage.length]);
  return out.filter(([a, z]) => passage.slice(a, z).trim());
}

/**
 * Where in a passage each claim comes from: the sentences sharing most of the claim's words and numbers
 * (a number counts double). A sentence is taken when it holds at least a third of the claim and close to the
 * best sentence's share, so a claim drawn from two sentences shows both.
 */
export function supportingRanges(passage: string, claims: string[]): [number, number][] {
  const sentences = sentenceRanges(passage).map(([a, z]) => ({ a, z, t: tokens(passage.slice(a, z)) }));
  const picked = new Set<number>();
  for (const claim of claims) {
    const c = tokens(claim);
    const total = c.words.size + 2 * c.numbers.size;
    if (total < 2) continue;
    const scores = sentences.map(({ t }) =>
      ([...c.words].filter((w) => t.words.has(w)).length + 2 * [...c.numbers].filter((x) => t.numbers.has(x)).length) / total);
    const best = Math.max(0, ...scores);
    if (best < 1 / 3) continue;
    scores.forEach((s, i) => { if (s >= Math.max(1 / 3, 0.6 * best)) picked.add(i); });
  }
  return [...picked].sort((x, y) => x - y).map((i) => [sentences[i].a, sentences[i].z]);
}

export type PassagePart = { text: string; mark: "sentence" | "term" | null };

/**
 * A passage with what its citing claims rest on marked: the supporting sentences (``supportingRanges``), and in
 * them every number of the claims, plus the claims' figures, dates and names (``terms``) anywhere.
 */
export function markPassage(passage: string, claims: string[], terms: string[]): PassagePart[] {
  const numbers = claims.flatMap((c) => [...c.matchAll(/\d+(?:[.,  ]\d+)*/g)].map((m) => m[0]));
  const out: PassagePart[] = [];
  const termParts = (text: string, extra: string[]) =>
    markTerms(text, [...terms, ...extra]).map((p) => ({ text: p.text, mark: p.mark ? ("term" as const) : null }));
  let last = 0;
  for (const [a, z] of supportingRanges(passage, claims)) {
    if (a > last) out.push(...termParts(passage.slice(last, a), []));
    out.push(...termParts(passage.slice(a, z), numbers).map((p) => (p.mark ? p : { ...p, mark: "sentence" as const })));
    last = z;
  }
  if (last < passage.length) out.push(...termParts(passage.slice(last), []));
  return out.filter((p) => p.text);
}

/** A passage split into plain parts and the parts to mark (``terms``, case-insensitive, longest first). */
export function markTerms(passage: string, terms: string[]): { text: string; mark: boolean }[] {
  const usable = [...new Set(terms.filter((t) => t.trim().length >= 2))].sort((a, b) => b.length - a.length);
  if (usable.length === 0) return [{ text: passage, mark: false }];
  // A space in a term matches any whitespace: a name can be split over two lines in the passage.
  const escape = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  const pattern = new RegExp(`(?<![\\p{L}\\d])(?:${usable.map(escape).join("|")})(?![\\p{L}]|\\d)`, "giu");
  const out: { text: string; mark: boolean }[] = [];
  let last = 0;
  for (const m of passage.matchAll(pattern)) {
    if (m.index! > last) out.push({ text: passage.slice(last, m.index), mark: false });
    out.push({ text: m[0], mark: true });
    last = m.index! + m[0].length;
  }
  if (last < passage.length) out.push({ text: passage.slice(last), mark: false });
  return out;
}
