/**
 * Copying and downloading cited passages. Everything happens in the browser; nothing is sent to
 * the server. Review note: once copied or downloaded, confidential passages are on the user's
 * clipboard or in their Downloads folder, outside Sūveryn's control (docs/architecture.md §3).
 */
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

export type Format = "txt" | "md";

/** File name for one source, e.g. "source-1_akte_p3.txt". */
export function sourceFileName(n: number, filename: string, page: number | null | undefined, format: Format = "txt"): string {
  const base = safeFileName(filename.replace(/\.pdf$/i, ""));
  return `source-${n}_${base}${page ? `_p${page}` : ""}.${format}`;
}

/**
 * One source as Markdown: the reference as a heading, the passage as a block quote. The passage
 * text itself is not altered (no escaping), so notarial wording stays exactly as stored.
 */
export function formatSourceMarkdown(n: number, citation: Citation, filename: string): string {
  const where = citation.source?.location ?? (citation.source?.page ? `p. ${citation.source.page}` : "");
  const quote = citation.text.trim().split("\n").map((l) => `> ${l}`.trimEnd()).join("\n");
  return `### [${n}] ${filename}${where ? ` — ${where}` : ""}\n\n${quote}`;
}

const stamp = (when: Date) => when.toLocaleString("en-GB", { dateStyle: "long", timeStyle: "short" });

/** The text of an "all sources" download: question, date, then the sources. */
export function sourcesDocument(question: string, sources: string, when: Date): string {
  return `Sources cited by sūveryn\nQuestion: ${question}\nDate: ${stamp(when)}\n\n${sources}\n`;
}

/** The Markdown version of an "all sources" download. */
export function sourcesMarkdown(question: string, items: { n: number; citation: Citation; filename: string }[], when: Date): string {
  const body = items.map((i) => formatSourceMarkdown(i.n, i.citation, i.filename)).join("\n\n");
  return `# Sources cited by sūveryn\n\n**Question:** ${question}  \n**Date:** ${stamp(when)}\n\n${body}\n`;
}

/** Saves text as a UTF-8 .txt or .md file through the browser. Nothing is sent to the server. */
export function downloadText(filename: string, text: string): void {
  const type = filename.endsWith(".md") ? "text/markdown;charset=utf-8" : "text/plain;charset=utf-8";
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
