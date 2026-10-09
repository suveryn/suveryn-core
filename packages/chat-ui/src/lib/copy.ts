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

/** A file name made of safe characters only: letters, digits, dot, dash, underscore. */
export function safeFileName(name: string): string {
  return name.normalize("NFKD").replace(/[^\w.-]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "").slice(0, 80) || "source";
}

/** File name for one source, e.g. "source-1_akte_p3.txt". */
export function sourceFileName(n: number, filename: string, page: number | null | undefined): string {
  const base = safeFileName(filename.replace(/\.pdf$/i, ""));
  return `source-${n}_${base}${page ? `_p${page}` : ""}.txt`;
}

/** The text of an "all sources" download: question, date, then the sources. */
export function sourcesDocument(question: string, sources: string, when: Date): string {
  const stamp = when.toLocaleString("en-GB", { dateStyle: "long", timeStyle: "short" });
  return `Sources cited by Sūveryn\nQuestion: ${question}\nDate: ${stamp}\n\n${sources}\n`;
}

/** Saves text as a UTF-8 .txt file through the browser. Nothing is sent to the server. */
export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
