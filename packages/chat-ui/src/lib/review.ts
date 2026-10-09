/** Wording for documents in needs_review: usable, but text on some pages may be missing. */

/** "p. 1" or "pp. 1, 3" */
export const pageList = (pages: number[]) => `${pages.length > 1 ? "pp." : "p."} ${pages.join(", ")}`;

export function reviewHint(pages: number[] | undefined): string {
  const where = !pages?.length ? "on some pages" : pages.length > 1 ? `on pages ${pages.join(", ")}` : `on page ${pages[0]}`;
  return `Ready to use. Some text ${where} may not have been read correctly, so check answers that rely on it against the original.`;
}
