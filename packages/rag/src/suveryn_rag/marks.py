"""sūveryn's mark on its own exports (docs/design/chat-ui.md §6, a document's origin).

Every Word and Excel file sūveryn makes, and the Markdown it exports, carries one plain line such as
"Made by sūveryn: answer from case 2026/0611, 19/10/2026 · sūveryn-ref A-3f9c2e1b". The
words are in the interface's language; ``sūveryn-ref`` and the code after it are not, so the line is
found in any language. When an upload contains it, the file is probably sūveryn's own output coming
back: it is stored, but is not a source until a person says so (never blocked; cases.md decision 7).

The line is ordinary text (light and small in a Word footer, not hidden), so it survives "Save as
PDF" and is read from the PDF's text layer, footers included. A scan of a printout may lose it; that
case is not caught, by design: this is a hint, not a guarantee.
"""
import re
import unicodedata

# A for an answer, P for a playbook result; eight hex digits tie the line to what was exported.
REF = re.compile(r"suveryn-ref[\s:]*([AP])-([0-9a-f]{8})\b", re.IGNORECASE)


def _plain(text: str) -> str:
    """Without accents (ū as u, also when the PDF splits it into u and a combining macron)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def find_mark(texts: list[str]) -> dict | None:
    """The first mark in these texts: ``{"ref": "A-3f9c2e1b", "kind": "answer", "line": …}``, the
    line as it stands in the file (at most 200 characters), or None."""
    for text in texts:
        for line in (text or "").splitlines():
            match = REF.search(_plain(line))
            if match:
                kind = {"A": "answer", "P": "playbook"}[match.group(1).upper()]
                return {"ref": f"{match.group(1).upper()}-{match.group(2).lower()}", "kind": kind,
                        "line": unicodedata.normalize("NFC", " ".join(line.split()))[:200]}
    return None
