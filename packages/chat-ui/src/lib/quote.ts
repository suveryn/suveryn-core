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
