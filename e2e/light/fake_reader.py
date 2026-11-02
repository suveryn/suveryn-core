"""A light stand-in for the document reader, for a development machine that can't reach Hugging Face
(e2e/README.md, "Light mode"). CI runs the real reader (Docling, OCR); this one reads a PDF's text layer with
pypdfium2 and builds a DoclingDocument of plain paragraphs with page provenance. No OCR, no layout, no tables:
enough for the end-to-end scenarios to upload, cite and run a playbook on a born-digital fixture.

Started by ``reader-wrapper.sh`` in place of ``python -I -m suveryn_rag.isolation``, speaking the same protocol
(``suveryn_rag.isolation.serve``). Nothing is logged: the file is a confidential document in real use.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from docling_core.types.doc import BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size
from suveryn_rag.extract import Extraction
from suveryn_rag.isolation import protocol_streams, serve
from suveryn_rag.reading import Unreadable, Watch

_HEADING = re.compile(r"^(AKTE VAN LEVERING|Artikel \d+ - .+|Bijlage \d+ - .+|Voor eensluidend afschrift)\s*$")


def paragraphs(page_text: str) -> list[tuple[str, str]]:
    """(label, text) per block: headings on their own, consecutive lines joined into paragraphs."""
    blocks: list[tuple[str, str]] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            blocks.append(("text", " ".join(current).strip()))
            current.clear()

    for raw in page_text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif _HEADING.match(line):
            flush()
            blocks.append(("heading", line))
        else:
            current.append(line)
    flush()
    return [b for b in blocks if b[1]]


def light_extract(pdf: Path, watch: Watch | None = None) -> Extraction:
    import pypdfium2 as pdfium

    if pdf.suffix.lower() != ".pdf":
        raise Unreadable("light mode reads PDF files only", "format")
    started = time.time()
    doc = DoclingDocument(name=pdf.stem)
    page_texts: list[str] = []
    reader = pdfium.PdfDocument(str(pdf))
    try:
        for i in range(len(reader)):
            page = reader[i]
            width, height = page.get_size()
            doc.add_page(page_no=i + 1, size=Size(width=width, height=height))
            text = page.get_textpage().get_text_range()
            page_texts.append(text)
            for label, block in paragraphs(text):
                prov = ProvenanceItem(page_no=i + 1, bbox=BoundingBox(l=0, t=0, r=width, b=height), charspan=(0, len(block)))
                if label == "heading":
                    doc.add_heading(text=block, level=1, prov=prov)
                else:
                    doc.add_text(label=DocItemLabel.PARAGRAPH, text=block, prov=prov)
    finally:
        reader.close()
    return Extraction(document=doc, pages=len(page_texts), ocr_pages=0, mixed_pages=0, page_texts=page_texts,
                      timings={"layout": time.time() - started})


if __name__ == "__main__":
    requests, answers = protocol_streams()
    serve(light_extract, requests, answers)
