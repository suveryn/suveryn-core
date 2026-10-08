"""Text extraction with the `ocr_fast` approach from the October 2026 benchmark.

1. Pages that already have a text layer (born-digital PDFs) are not OCR'd.
2. Scanned pages are OCR'd in parallel across CPU cores by OCRmyPDF (one Tesseract process
   per page), producing a searchable PDF in a private work directory.
3. Docling reads that text layer (do_ocr=False) and runs only its GPU layout/table models.

This was 3.7-8x faster than letting Docling call Tesseract page by page.
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
    document: object  # docling_core DoclingDocument
    pages: int
    ocr_pages: int
    # Per-page text of the PDF text layer Docling read (OCR output for scans), kept in memory
    # only, for the page coverage check.
    page_texts: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


def text_layer(pdf: Path) -> list[str]:
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


def pages_with_text(pdf: Path) -> list[bool]:
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [len(doc[i].get_textpage().get_text_range().strip()) >= MIN_TEXT_CHARS for i in range(len(doc))]
    finally:
        doc.close()


class Extractor:
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
                ocrmypdf.ocr(pdf, source, language=self.settings.ocr_languages.split("+"), jobs=self.settings.ocr_jobs,
                             skip_text=True, output_type="pdf", optimize=0, progress_bar=False, tesseract_timeout=180)
                timings["ocr"] = time.perf_counter() - t
            t = time.perf_counter()
            document = self._converter.convert(source).document
            timings["layout"] = time.perf_counter() - t
            page_texts = text_layer(source)
        return Extraction(document=document, pages=len(has_text), ocr_pages=ocr_pages, page_texts=page_texts,
                          timings=timings)
