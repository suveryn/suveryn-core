/**
 * The files sūveryn reads (suveryn_rag.formats on the server): PDF, Word (.docx), Excel (.xlsx),
 * Markdown (.md) and CSV. The server checks every upload; this list only steers the file picker.
 */
export const ACCEPTED_FILES = [
  ".pdf", "application/pdf",
  ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".md", ".markdown", "text/markdown",
  ".csv", "text/csv",
];

/** A document's file extension, to drop from names made from it ("deed.docx" -> "deed"). */
export const DOCUMENT_EXTENSION = /\.(pdf|docx|xlsx|md|markdown|csv)$/i;

const NAMES: Record<string, string> = { docx: "Word", xlsx: "Excel", md: "Markdown", markdown: "Markdown", csv: "CSV" };

/** The format's name for a file without pages ("Word", "Excel"); the same word in every language. */
export function formatName(filename: string): string {
  return NAMES[filename.split(".").pop()?.toLowerCase() ?? ""] ?? "";
}
