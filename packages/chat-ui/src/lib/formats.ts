/**
 * The files sūveryn reads (suveryn_rag.formats on the server): PDF, Word (.docx), Excel (.xlsx), Markdown (.md),
 * CSV, TSV, text (.txt), JSON, XML and HTML. The server checks every upload; these lists only steer the file picker.
 * ``ACCEPTED_FILES`` adds a .zip of them and an email (.eml): each file inside, and each attachment, becomes a
 * document; ``DOCUMENT_FILES`` is the documents alone.
 */
export const DOCUMENT_FILES = [
  ".pdf", "application/pdf",
  ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".md", ".markdown", "text/markdown",
  ".csv", "text/csv",
  ".tsv", "text/tab-separated-values",
  ".txt", "text/plain",
  ".json", "application/json",
  ".xml", "application/xml", "text/xml",
  ".html", ".htm", "text/html",
];
export const ACCEPTED_FILES = [...DOCUMENT_FILES, ".zip", "application/zip", "application/x-zip-compressed", ".eml", "message/rfc822"];

/** A document's file extension, to drop from names made from it ("deed.docx" -> "deed"). */
export const DOCUMENT_EXTENSION = /\.(pdf|docx|xlsx|md|markdown|csv|tsv|txt|json|xml|html?|eml)$/i;

const NAMES: Record<string, string> = { docx: "Word", xlsx: "Excel", md: "Markdown", markdown: "Markdown", csv: "CSV", tsv: "TSV",
                                         txt: "TXT", json: "JSON", xml: "XML", html: "HTML", htm: "HTML", eml: "EML" };

/** The format's name for a file without pages ("Word", "Excel"); the same word in every language. */
export function formatName(filename: string): string {
  return NAMES[filename.split(".").pop()?.toLowerCase() ?? ""] ?? "";
}
