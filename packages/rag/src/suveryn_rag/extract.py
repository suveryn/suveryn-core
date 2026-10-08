"""Text extraction with the `ocr_fast` approach from the October 2026 benchmark.

1. Pages that already have a text layer (born-digital PDFs) are not OCR'd.
2. Scanned pages are OCR'd in parallel across CPU cores by OCRmyPDF (one Tesseract process
   per page), producing a searchable PDF in a private work directory.
3. Docling reads that text layer (do_ocr=False) and runs only its GPU layout/table models.

This was 3.7-8x faster than letting Docling call Tesseract page by page (38-page scanned
report: 90 s -> 25 s on 8 cores).

Known limitation (review): the decision which pages get OCR'd is OCRmyPDF's ``skip_text``,
which skips every page that has *any* text layer. A scanned page that carries a few words of
digital text (e.g. a copier label or digital stamp) is therefore not OCR'd, and its scanned
content is missing; the page coverage check can't see this, because it compares against that
same thin text layer. ``pages_with_text`` already identifies such pages (< MIN_TEXT_CHARS);
OCR'ing them selectively is a planned fix.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from .config import RagSettings
from .workspace import private_workdir

MIN_TEXT_CHARS = 50  # fewer extractable characters than this: treat the page as a scan


@dataclass
class Extraction:
    """Output of ``Extractor.extract``. Holds document text in memory; nothing here is on disk."""

    document: object  # docling_core DoclingDocument
    pages: int
    ocr_pages: int
    # Per-page text of the PDF text layer Docling read (OCR output for scans), kept in memory
    # only, for the page coverage check.
    page_texts: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


def text_layer(pdf: Path) -> list[str]:
    """The PDF's own text per page (empty strings for pure scans)."""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


def pages_with_text(pdf: Path) -> list[bool]:
    """Per page: True if it has a usable text layer (at least MIN_TEXT_CHARS characters)."""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [len(doc[i].get_textpage().get_text_range().strip()) >= MIN_TEXT_CHARS for i in range(len(doc))]
    finally:
        doc.close()


class Extractor:
    """Loads Docling's layout and table models once (on the GPU by default) and extracts PDFs.

    Not safe to use from several threads at once: ``extract`` redirects the process-wide
    TMPDIR while it runs (see ``workspace.private_workdir``). Ingest one document at a time
    per process; this also matches the benchmark advice to queue heavy work.
    """

    def __init__(self, settings: RagSettings):
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        self.settings = settings
        device = AcceleratorDevice.CUDA if settings.device == "cuda" else AcceleratorDevice.CPU
        opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True,
                                  accelerator_options=AcceleratorOptions(device=device, num_threads=settings.ocr_jobs))
        self._converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
        self._converter.initialize_pipeline(InputFormat.PDF)

    def extract(self, pdf: Path) -> Extraction:
        """Extract one PDF. The original file is only read; every intermediate file lives in a
        private work directory that is deleted before this returns, also on errors."""
        import ocrmypdf

        t0 = time.perf_counter()
        has_text = pages_with_text(pdf)
        ocr_pages = len(has_text) - sum(has_text)
        timings = {"classify": time.perf_counter() - t0}
        with private_workdir(self.settings.work_dir) as work:
            source = pdf
            if ocr_pages:
                t = time.perf_counter()
                source = work / "searchable.pdf"
                # skip_text: leave pages with a text layer alone (see the module docstring for the
                # limitation); output_type="pdf" and optimize=0 skip slow PDF/A conversion and
                # image recompression, which the pipeline doesn't need.
                ocrmypdf.ocr(pdf, source, language=self.settings.ocr_languages.split("+"), jobs=self.settings.ocr_jobs,
                             skip_text=True, output_type="pdf", optimize=0, progress_bar=False, tesseract_timeout=180)
                timings["ocr"] = time.perf_counter() - t
            t = time.perf_counter()
            document = self._converter.convert(source).document
            timings["layout"] = time.perf_counter() - t
            page_texts = text_layer(source)
        return Extraction(document=document, pages=len(has_text), ocr_pages=ocr_pages, page_texts=page_texts,
                          timings=timings)
