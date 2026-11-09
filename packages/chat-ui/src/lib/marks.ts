/**
 * sūveryn's mark on its own exports (docs/design/chat-ui.md §6, a document's origin). Every Word and
 * Excel file it makes carries one plain line, for example "Made by sūveryn: answer from case
 * 2026/0611, 19/10/2026 · sūveryn-ref A-3f9c2e1b". When such a file is uploaded again, the server finds
 * "sūveryn-ref" (suveryn_rag.marks) and asks the person before it becomes a source. The words follow
 * the interface language; the reference doesn't, so the line is found in any language. Not hidden:
 * hidden text is dropped when Word saves as PDF, and a screen reader reads the line either way.
 */

/** A short reference for one export: A (answer) or P (playbook result) and eight hex digits of an
 *  FNV-1a hash of what it was made from (an answer's turn id, a run's id). */
export function exportRef(kind: "A" | "P", seed: string): string {
  let h = 0x811c9dc5;
  for (const ch of seed) {
    h ^= ch.codePointAt(0)!;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `${kind}-${h.toString(16).padStart(8, "0")}`;
}


/** Where an export came from, read from its mark's line in any of the interface's languages ("…: answer from case
 *  2026/0611, 19/10/2026 · sūveryn-ref …", "… uit dossier 124, 17-10-2026 · …"): the case's reference and the date,
 *  day first as every language here writes it. Null when the line doesn't say (an export from a personal chat). */
export function markOrigin(line: string): { caseRef: string; date: Date | null } | null {
  const m = /\b(?:case|dossier)\s+(\S+?),\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/i.exec(line);
  if (!m) return null;
  const [, caseRef, d, mo, y] = m;
  const year = Number(y) < 100 ? 2000 + Number(y) : Number(y);
  const date = new Date(year, Number(mo) - 1, Number(d));
  return { caseRef, date: date.getMonth() === Number(mo) - 1 ? date : null };
}
