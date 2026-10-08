"""Generates a FICTITIOUS Dutch deed with the traps that broke extraction or retrieval before.

All names and numbers are invented. Traps:
- a running header and page numbers on every page (must be dropped);
- a one-off line in the footer area of page 3 that is real content (must be kept);
- a closing heading with no text after it, "Voor eensluidend afschrift" (must be kept);
- a cadastral reference "sectie K, nummer 4182" (must not be garbled);
- a tenant in arrears buried in a long block of boilerplate (must be found by retrieval).
"""

import random
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

RUNNING_HEADER = "AKTE VAN LEVERING - Kenmerk TST/2026/0042"
FOOTER_CONTENT = "Bijzondere last: recht van opstal ten gunste van Stroomnet Oost B.V. tot 31 december 2041."
CLOSING_HEADING = "Voor eensluidend afschrift"
CADASTRE = "sectie K, nummer 4182"
ARREARS = "De huurder Rivierdal Logistiek B.V. heeft per heden een huurachterstand van EUR 48.200,00."

QUESTIONS = [
    {"q": "Wat is de koopprijs?", "expect": "1.275.000"},
    {"q": "Welke huurder heeft een huurachterstand?", "expect": "48.200"},
    {"q": "Hoe is het verkochte kadastraal bekend?", "expect": "4182"},
    {"q": "Welk recht van opstal rust op het verkochte?", "expect": "Stroomnet Oost"},
    {"q": "Tot wanneer loopt de ontbindende voorwaarde voor de financiering?", "expect": "15 januari 2027"},
    {"q": "Welke boete geldt bij overtreding van het kettingbeding?", "expect": "25.000"},
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
