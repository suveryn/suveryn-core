"""Text extraction with the `ocr_fast` approach from the October 2026 benchmark.

Which pages get OCR'd (``plan_ocr``):
- **scans**: fewer than MIN_TEXT_CHARS characters of text, including "thin" scans that carry a
  few words of digital text such as a copier label or a digital stamp. OCRmyPDF's own
  ``skip_text`` would skip those because they have *some* text, and the scan would be lost;
- **mixed pages**: a usable digital text layer *and* raster images covering at least
  MIN_IMAGE_SHARE of the page, typically a born-digital page with a pasted-in scan;
- every other page (born-digital text, small logos/signatures/stamps) is passed through.

How: one OCRmyPDF run in ``redo_ocr`` mode, limited to the selected pages and spread over CPU
cores (one Tesseract process per page). ``redo_ocr`` keeps visible digital text exactly as it
is and OCRs only what is drawn as images: OCRmyPDF hides the existing text before rendering
the page for Tesseract, so nothing is read twice. Docling then reads the resulting text layer
(do_ocr=False) and runs only its GPU layout/table models.

This was 3.7-8x faster than letting Docling call Tesseract page by page (38-page scanned
report: 90 s -> 25 s on 8 cores).
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .config import RagSettings
from .workspace import private_workdir

MIN_TEXT_CHARS = 50     # fewer extractable characters than this: treat the page as a scan
# Raster images covering at least this share of a page that has digital text: OCR the images.
# Logos, signatures and stamps typically cover 1-5% of an A4 page; a pasted-in scanned
# paragraph or annex covers far more. A full-page background image also triggers OCR, which
# costs a few seconds but is harmless (it yields no text if the image has none).
MIN_IMAGE_SHARE = 0.10


@dataclass(frozen=True)
class PageProfile:
    """What a page is made of, as far as the OCR decision is concerned."""

    chars: int          # characters in the page's own text layer
    image_share: float  # share of the page area covered by raster images (0-1, capped at 1)

    @property
    def is_scan(self) -> bool:
        return self.chars < MIN_TEXT_CHARS

    @property
    def is_mixed(self) -> bool:
        return not self.is_scan and self.image_share >= MIN_IMAGE_SHARE


@dataclass
class Extraction:
    """Output of ``Extractor.extract``. Holds document text in memory; nothing here is on disk."""

    document: object  # docling_core DoclingDocument
    pages: int
    ocr_pages: int    # scans + mixed pages that went through OCR
    mixed_pages: int  # of which: pages with digital text plus large images
    # Per-page text of the PDF text layer Docling read (OCR output included), kept in memory
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


def page_profiles(pdf: Path) -> list[PageProfile]:
    """Text length and image coverage per page (images inside form XObjects included)."""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        out = []
        for i in range(len(doc)):
            page = doc[i]
            width, height = page.get_size()
            area = 0.0
            for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=4):
                left, bottom, right, top = obj.get_bounds()
                # clip to the page; overlapping images may double-count, hence the cap below
                w = max(0.0, min(right, width) - max(left, 0.0))
                h = max(0.0, min(top, height) - max(bottom, 0.0))
                area += w * h
            share = min(1.0, area / (width * height)) if width and height else 0.0
            out.append(PageProfile(chars=len(page.get_textpage().get_text_range().strip()), image_share=share))
        return out
    finally:
        doc.close()


def plan_ocr(profiles: list[PageProfile]) -> list[int]:
    """1-based numbers of the pages to OCR (scans and mixed pages), as OCRmyPDF expects."""
    return [i + 1 for i, p in enumerate(profiles) if p.is_scan or p.is_mixed]


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
        profiles = page_profiles(pdf)
        to_ocr = plan_ocr(profiles)
        timings = {"classify": time.perf_counter() - t0}
        with private_workdir(self.settings.work_dir) as work:
            source = pdf
            if to_ocr:
                t = time.perf_counter()
                source = work / "searchable.pdf"
                # redo_ocr + pages: OCR the image content of exactly the selected pages, keep their
                # visible digital text, and pass all other pages through untouched (see the module
                # docstring). output_type="pdf" and optimize=0 skip slow PDF/A conversion and
                # image recompression, which the pipeline doesn't need.
                ocrmypdf.ocr(pdf, source, language=self.settings.ocr_languages.split("+"), jobs=self.settings.ocr_jobs,
                             pages=",".join(map(str, to_ocr)), redo_ocr=True, output_type="pdf", optimize=0,
                             progress_bar=False, tesseract_timeout=180)
                timings["ocr"] = time.perf_counter() - t
            t = time.perf_counter()
            document = self._converter.convert(source).document
            timings["layout"] = time.perf_counter() - t
            page_texts = text_layer(source)
        return Extraction(document=document, pages=len(profiles), ocr_pages=len(to_ocr),
                          mixed_pages=sum(p.is_mixed for p in profiles), page_texts=page_texts, timings=timings)
