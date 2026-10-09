/**
 * Turns an answer's text into blocks (paragraphs, list items) of inline segments: plain text,
 * bold text, and citation markers. Marker [n] refers to citations[n - 1] (the backend's
 * positional citation contract). Rendering goes through React, so model output is never
 * injected as HTML.
 */
export type Segment =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "cite"; n: number };

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

function inline(text: string, available: number): Segment[] {
  const out: Segment[] = [];
  // Split on **bold** first, then on [n] markers inside each piece.
  text.split(/(\*\*[^*]+\*\*)/g).forEach((piece) => {
    if (!piece) return;
    if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
      out.push({ kind: "bold", text: piece.slice(2, -2) });
      return;
    }
    let last = 0;
    for (const m of piece.matchAll(MARKER)) {
      const n = Number(m[1]);
      if (n < 1 || n > available) continue; // not a valid marker: leave it as text
      if (m.index! > last) out.push({ kind: "text", text: piece.slice(last, m.index) });
      out.push({ kind: "cite", n });
      last = m.index! + m[0].length;
    }
    if (last < piece.length) out.push({ kind: "text", text: piece.slice(last) });
  });
  return out;
}

export function toBlocks(text: string, available: number): Block[] {
  const blocks: Block[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const item = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (item) blocks.push({ kind: "li", segments: inline(item[1], available) });
    else blocks.push({ kind: "p", segments: inline(heading ? `**${heading[1]}**` : line, available) });
  }
  return blocks;
}

/** Marker-free text, for sending earlier turns back as conversation history. */
export function stripMarkers(text: string): string {
  return text.replace(MARKER, "").replace(/[ \t]+([.,;:])/g, "$1");
}
