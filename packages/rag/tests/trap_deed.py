"""Generates a FICTITIOUS Dutch deed with the traps that broke extraction or retrieval before.

All names and numbers are invented. Traps:
- a running header and page numbers on every page (must be dropped);
- a one-off line in the footer area of page 3 that is real content (must be kept);
- a closing heading with no text after it, "Voor eensluidend afschrift" (must be kept);
- a cadastral reference "sectie K, nummer 4182" (must not be garbled);
- a tenant in arrears buried in a long block of boilerplate (must be found by retrieval);
- a "pasted-in scan" on a born-digital page: a soil report whose text exists only as an image
  (must be OCR'd while the page's digital text is kept).
"""

import random
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate

RUNNING_HEADER = "AKTE VAN LEVERING - Kenmerk TST/2026/0042"
FOOTER_CONTENT = "Bijzondere last: recht van opstal ten gunste van Stroomnet Oost B.V. tot 31 december 2041."
CLOSING_HEADING = "Voor eensluidend afschrift"
CADASTRE = "sectie K, nummer 4182"
ARREARS = "De huurder Rivierdal Logistiek B.V. heeft per heden een huurachterstand van EUR 48.200,00."
PASTED_SCAN_HEADING = "Bijlage 1 - Bodemrapport (scan)"
PASTED_SCAN_LINES = ["BODEMRAPPORT BR-2026-117",
                     "Ter plaatse van de voormalige olietank is",
                     "een verontreiniging met minerale olie",
                     "aangetroffen. Sanering door verkoper",
                     "uiterlijk op 1 juni 2027."]

QUESTIONS = [
    {"q": "Wat is de koopprijs?", "expect": "1.275.000"},
    {"q": "Welke huurder heeft een huurachterstand?", "expect": "48.200"},
    {"q": "Hoe is het verkochte kadastraal bekend?", "expect": "4182"},
    {"q": "Welk recht van opstal rust op het verkochte?", "expect": "Stroomnet Oost"},
    {"q": "Tot wanneer loopt de ontbindende voorwaarde voor de financiering?", "expect": "15 januari 2027"},
    {"q": "Welke boete geldt bij overtreding van het kettingbeding?", "expect": "25.000"},
    # The answer exists only inside the pasted-in scan image; its page is found via the heading.
    {"q": "Welke verontreiniging staat in het bodemrapport?", "expect": "minerale olie", "page_anchor": PASTED_SCAN_HEADING},
]

_SUBJ = ["Partijen", "Koper", "Verkoper", "De huurder", "De verhuurder", "Iedere partij"]
_VERB = ["verklaart", "erkent", "aanvaardt", "verbindt zich", "staat ervoor in"]
_OBJ = ["dat de bepalingen van dit artikel van toepassing blijven na de levering",
        "dat mededelingen schriftelijk geschieden aan het in de aanhef vermelde adres",
        "dat kosten van onderhoud naar rato van het gebruik worden omgeslagen",
        "dat de servicekosten jaarlijks binnen zes maanden worden afgerekend",
        "dat de huurprijs jaarlijks wordt geïndexeerd op basis van de consumentenprijsindex",
        "dat de huurder het gehuurde als een goed huurder zal gebruiken en onderhouden"]


def _filler(rng: random.Random, n: int) -> str:
    return " ".join(f"{rng.choice(_SUBJ)} {rng.choice(_VERB)} {rng.choice(_OBJ)}." for _ in range(n))


def _pasted_scan(width_pt: float, height_pt: float, font_path: str | None):
    """The soil report as a grey 300 dpi raster image, like a scanned page pasted into a document."""
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont

    px = lambda pt: int(pt / 72 * 300)
    img = PILImage.new("L", (px(width_pt), px(height_pt)), 248)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 54) if font_path else ImageFont.load_default(size=54)
    for n, line in enumerate(PASTED_SCAN_LINES):
        draw.text((60, 50 + n * 80), line, fill=20, font=font)
    return img


def build(path: Path) -> Path:
    rng = random.Random(42)
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
    if Path(font).exists():
        pdfmetrics.registerFont(TTFont("TD", font))
        pdfmetrics.registerFont(TTFont("TDB", bold))
        body_font, head_font = "TD", "TDB"
    else:
        body_font, head_font = "Times-Roman", "Times-Bold"
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName=body_font, fontSize=10.5, leading=15, alignment=4, spaceAfter=6)
    head = ParagraphStyle("h", parent=body, fontName=head_font, fontSize=12, spaceBefore=10, alignment=0)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(body_font, 8.5)
        canvas.drawString(70, A4[1] - 40, RUNNING_HEADER)
        canvas.drawCentredString(A4[0] / 2, 30, f"Pagina {doc.page}")
        if doc.page == 3:
            canvas.drawString(70, 45, FOOTER_CONTENT)
        canvas.restoreState()

    s = [Paragraph("AKTE VAN LEVERING", head),
         Paragraph("Heden verschijnen voor mij, mr. Testnotaris Fictief, notaris te Testdorp: Verkoper Zandvoorde "
                   "Vastgoed B.V. en Koper Duinrand Beleggingen B.V.", body),
         Paragraph("Artikel 1 - Omschrijving", head),
         Paragraph("Verkoper levert aan koper het bedrijfspand te Testdorp, Havenweg 12, kadastraal bekend gemeente "
                   f"Testdorp, {CADASTRE}, groot twaalf are. " + _filler(rng, 6), body),
         Paragraph("Artikel 2 - Koopprijs", head),
         Paragraph("De koopprijs bedraagt EUR 1.275.000,00 (een miljoen tweehonderdvijfenzeventigduizend euro). "
                   + _filler(rng, 8), body),
         Paragraph("Artikel 3 - Ontbindende voorwaarden", head),
         Paragraph("De koop is aangegaan onder de ontbindende voorwaarde dat koper uiterlijk op 15 januari 2027 geen "
                   "financiering heeft verkregen. " + _filler(rng, 10), body),
         Paragraph("Artikel 4 - Huurovereenkomsten", head),
         Paragraph(_filler(rng, 14) + " " + ARREARS + " " + _filler(rng, 14), body),
         Paragraph("Artikel 5 - Kettingbeding", head),
         Paragraph("Op het verkochte rust een kettingbeding inzake het onderhoud van de kademuur, op straffe van een "
                   "boete van EUR 25.000,00 per overtreding. " + _filler(rng, 12), body)]
    import io

    # ~18% of an A4 page: well above MIN_IMAGE_SHARE, so the page counts as "mixed".
    png = io.BytesIO()
    _pasted_scan(450, 200, font if Path(font).exists() else None).save(png, format="PNG")
    png.seek(0)
    s.append(KeepTogether([Paragraph(PASTED_SCAN_HEADING, head), Image(png, width=450, height=200)]))
    for i in range(6, 10):
        s += [Paragraph(f"Artikel {i} - Algemene bepalingen {i}", head), Paragraph(_filler(rng, 16), body)]
    s.append(Paragraph(CLOSING_HEADING, head))  # the last element: a heading with nothing after it
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=70, rightMargin=70, topMargin=70, bottomMargin=75).build(
        s, onFirstPage=on_page, onLaterPages=on_page)
    return path


def scanned(src: Path, dst: Path, dpi: int = 200) -> Path:
    """Image-only copy of a PDF (needs pdf2image + poppler), to exercise the OCR path."""
    from pdf2image import convert_from_path

    pages = convert_from_path(str(src), dpi=dpi, grayscale=True)
    pages[0].save(dst, save_all=True, append_images=pages[1:], resolution=dpi)
    return dst


def signed(src: Path, dst: Path) -> Path:
    """Copy of a PDF marked as digitally signed (AcroForm SigFlags), the way OCRmyPDF detects it.

    Trap: OCRmyPDF refuses to OCR a signed PDF, so a signed scanned deed couldn't be read. No real
    signature is needed for that check; a signature field without a value is enough.
    """
    import pikepdf

    with pikepdf.open(src) as pdf:
        field = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Sig, T=pikepdf.String("Handtekening notaris"),
                                                     Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
                                                     Rect=[0, 0, 0, 0], P=pdf.pages[0].obj))
        pdf.pages[0].obj.Annots = pdf.make_indirect(pikepdf.Array([field]))
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array([field]), SigFlags=3))
        pdf.save(dst)
    return dst


SCANNER_LABEL = "Kopie scanner 3"  # under MIN_TEXT_CHARS, like a copier's or e-stamp's text layer


def scanned_with_label(src: Path, dst: Path, dpi: int = 200) -> Path:
    """Scanned copy where every page also carries a short digital text label ("thin" pages).

    Trap: OCRmyPDF's skip_text treats such pages as already having text and skips them, so
    the scanned content would be lost.
    """
    from pdf2image import convert_from_path
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    c = Canvas(str(dst), pagesize=A4)
    for img in convert_from_path(str(src), dpi=dpi, grayscale=True):
        c.drawImage(ImageReader(img), 0, 0, width=A4[0], height=A4[1])
        c.setFont("Helvetica", 6)
        c.drawString(A4[0] - 90, 12, SCANNER_LABEL)
        c.showPage()
    c.save()
    return dst
