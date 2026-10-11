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

export type Block = { kind: "p" | "li"; segments: Segment[] };

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
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
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
