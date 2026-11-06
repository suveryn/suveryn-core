/**
 * The part of a passage a *Kijk na* card quotes (VM regression 9c97d76, finding 7): the card quoted the whole passage,
 * on a short document the whole deed, while the value comes from one sentence. The sentence that shares the most words
 * with the value is quoted, with "…" where the passage goes on; the whole passage stays behind the source link.
 */

const SHORT = 240; // a passage this short is quoted whole

const fold = (s: string) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
const words = (s: string) => new Set(fold(s).match(/[\p{L}\p{N}]{3,}/gu) ?? []);

export function quoteFor(passage: string, value: string): string {
  const text = passage.trim();
  if (text.length <= SHORT) return text;
  const sentences = text.split(/(?<=[\p{L})][.;!?])\s+|\n+/u).map((s) => s.trim()).filter(Boolean);
  const wanted = words(value);
  let best = -1, score = 0;
  sentences.forEach((s, i) => {
    const have = words(s);
    const n = [...wanted].filter((w) => have.has(w)).length;
    if (n > score) { best = i; score = n; }
  });
  if (best < 0) return text;
  const sentence = sentences[best];
  return `${best > 0 ? "… " : ""}${sentence}${best < sentences.length - 1 ? " …" : ""}`;
}

/**
 * A fact's passage on its card (board P02): the words the fact cites, then a few words of what follows, with "…" where
 * the passage goes on ("… uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst, en in elk geval …").
 * The cited words are shown in ink and the rest dimmed. When the passage doesn't hold them as written, its sentence that
 * comes closest (``quoteFor``), all in ink.
 */
export function citedContext(passage: string, cited: string, after = 4): { text: string; before?: string; cited?: string; after?: string } {
  const text = passage.trim().replace(/\s+/g, " ");
  const want = cited.trim().replace(/\s+/g, " ");
  const at = want ? text.toLowerCase().indexOf(want.toLowerCase()) : -1;
  if (at < 0) return { text: quoteFor(text, cited) };
  const rest = text.slice(at + want.length);
  const words = rest.match(/^\S*(\s+\S+)*/)?.[0].split(/(?=\s+\S)/) ?? [];
  // what sticks to the cited words (",") and then ``after`` words, no further than the sentence's end
  const pieces: string[] = [];
  for (const w of words) {
    if (pieces.length >= after + (/^\s/.test(rest) ? 0 : 1)) break;
    pieces.push(w);
    if (/[.;!?]$/.test(w)) break;
  }
  const tail = pieces.join("");
  return { text, before: at > 0 ? "… " : "", cited: text.slice(at, at + want.length),
           after: tail + (rest.length > tail.length ? " …" : "") };
}
