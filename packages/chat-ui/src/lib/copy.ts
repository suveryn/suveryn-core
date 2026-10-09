import type { Citation } from "../api";

/** One source as plain text: "[n] file.pdf, p. 3 · Artikel 4" and the passage on the next lines. */
export function formatSource(n: number, citation: Citation, filename: string): string {
  const where = citation.source?.location ?? (citation.source?.page ? `p. ${citation.source.page}` : "");
  return `[${n}] ${filename}${where ? `, ${where}` : ""}\n${citation.text.trim()}`;
}

/** Several sources, in the order given, separated by a blank line. */
export function formatSources(items: { n: number; citation: Citation; filename: string }[]): string {
  return items.map((i) => formatSource(i.n, i.citation, i.filename)).join("\n\n");
}

/**
 * Copies text to the clipboard. The Clipboard API only exists on secure pages (HTTPS or
 * localhost); an appliance reached over plain HTTP on the office network falls back to a
 * temporary text field and the older copy command. Must be called from a click handler.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the fallback */
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
  }
}
