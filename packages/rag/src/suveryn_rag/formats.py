"""Reading uploads other than PDFs: Word (.docx), Excel (.xlsx), PowerPoint (.pptx), OpenDocument (.odt, .ods,
.odp), Markdown (.md), CSV and TSV, plain text (.txt), JSON, XML, HTML and an email's message (.eml).

PDFs go through OCR and Docling's layout model (``extract``). These formats carry their text and
structure in the file itself, so they are read directly, in the same sandboxed reader process
(``isolation``): an Office file is a zip of XML, an email or a web page is text, all untrusted input like
any PDF.

What comes out is a list of passages, each with where it sits:

- **Word, OpenDocument text, Markdown and HTML**: the section, as the chain of headings above the passage ("Article 2 ›
  The price"). A Word heading is a paragraph in a Heading or Title style, or one with an outline
  level; an HTML heading is h1 to h6. Tables are kept as rows of cells; a long table is split by rows,
  its first row repeated.
- **Excel, OpenDocument spreadsheets, CSV and TSV**: the cells, as a range in Excel's own notation ("Prices!A2:D31", "A2:D31" in a
  CSV): language-neutral, and what a spreadsheet user types to find them. Values are read as
  last calculated (never formulas). The first non-empty row of a sheet is repeated at the top
  of every later passage of that sheet, so each passage says what its columns are.
- **JSON and XML**: one line per value, "where: value", the where as the standard writes it: a JSON
  Pointer (RFC 6901, "/parties/0/name") or an XPath of local names ("/deed/party[2]/name", "/deed/@id";
  namespaces left out). A passage's place is the deepest path its lines share.
- **Plain text**: by paragraph (a blank line between them).
- **A deck (PowerPoint, OpenDocument presentation)**: slide by slide, under the slide's title: its text, then
  its tables by rows, then its speaker notes; each slide numbered as a page (``Passage.page``): its number in
  the deck, hidden slides counted, so a source says "p. 3" for the third slide.
- **An email**: who sent it to whom, when and its subject (RFC 5322's field names), then its text: the body
  (the plain text, or else the HTML, read as HTML is) and any other text part shown with it. Its
  attachments are documents of their own, taken out by the document service (``service``).

Nothing is left out of the body: a heading with no text under it becomes a passage of its own.
Text outside the body (Word and OpenDocument headers, footers and comments, a slide's footer and number,
Markdown and HTML comments, an HTML page's title) is returned separately as ``furniture``: it is checked for sūveryn's export mark (``marks``) but not stored as
passages, as a PDF's repeating headers and footers aren't either. Tracked insertions are read, deletions
not: the document as it now reads.

Text files are read as UTF-8 (with or without a byte-order mark), UTF-16 with its byte-order mark, or
else Windows-1252 (``decode``); an HTML page may also say its encoding in a meta tag.
"""

import codecs
import csv
import email
import email.errors
import email.policy
import io
import json
import re
import zipfile
from email.message import EmailMessage
from html.parser import HTMLParser
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from pathlib import Path

from .reading import Unreadable

# File types by extension. The upload check (``looks_like``) and the reader confirm the content.
KINDS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx", ".odt": "odt", ".ods": "ods", ".odp": "odp", ".md": "md", ".markdown": "md", ".csv": "csv", ".tsv": "tsv",
         ".txt": "txt", ".json": "json", ".xml": "xml", ".html": "html", ".htm": "html", ".eml": "eml"}
SUFFIX = {"pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx", "odt": ".odt", "ods": ".ods", "odp": ".odp", "md": ".md", "csv": ".csv", "tsv": ".tsv", "txt": ".txt",
          "json": ".json", "xml": ".xml", "html": ".html", "eml": ".eml"}
TEXT_KINDS = {"md", "csv", "tsv", "txt", "json", "xml", "html", "eml"}
# An OpenDocument package's type, as its own ``mimetype`` entry says it.
ODF_TYPES = {"odt": "application/vnd.oasis.opendocument.text", "ods": "application/vnd.oasis.opendocument.spreadsheet",
             "odp": "application/vnd.oasis.opendocument.presentation"}
# The type the gateway serves a kept file as (board G11, "Open document"): a PDF opens in the browser, Word and
# Excel are downloaded, text files are shown as plain text (an HTML page too: never as HTML, so nothing in it
# runs; in the character set it was read in: ``content_type``), an email is downloaded for the mail program.
CONTENT_TYPE = {"pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                **ODF_TYPES,
                "eml": "message/rfc822",
                **{kind: "text/plain; charset=utf-8" for kind in ("md", "csv", "tsv", "txt", "json", "xml", "html")}}

# Limits for one file, checked before and while reading, so one upload can't exhaust the reader.
MAX_UNPACKED_BYTES = 300 * 1024 * 1024   # an Office file's content once unzipped
MAX_ZIP_ENTRIES = 10_000
MAX_CELLS = 250_000                      # non-empty cells in a workbook or CSV, values in a JSON or XML file
MAX_CHARS = 5_000_000                    # text in one document (a 60-page deed is ~150,000)
MAX_DEPTH = 100                          # JSON or XML nested deeper: no document is, and each place holds its path


@dataclass(frozen=True)
class Passage:
    """A stored passage: its text, the headings above it, for a spreadsheet the cell range (or a path), and for a
    deck the slide, numbered as a page."""

    text: str
    headings: list[str] = field(default_factory=list)
    place: str | None = None
    page: int | None = None


@dataclass
class Reading:
    """What was read from one file: the passages in reading order, and the text outside the body."""

    passages: list[Passage]
    furniture: list[str] = field(default_factory=list)
    pages: int = 0  # a deck's slides; 0 for a file without pages


def kind_of(filename: str) -> str | None:
    """The file's kind by its extension ("pdf", "docx", "txt", ...: ``KINDS``); None for anything else."""
    return KINDS.get(Path(filename).suffix.lower())


OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # a compound file: an old Office file, or an encrypted new one
BOMS = (codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


def looks_like(kind: str, head: bytes) -> bool:
    """Whether the file's first bytes fit its kind: a PDF header, a zip for Office files (or the compound file a
    password-protected one is, which the reader refuses as such), and for text
    files no NUL byte (a binary file renamed to .txt or .csv) unless it starts with a UTF-16 byte-order mark."""
    if kind == "pdf":
        return head.startswith(b"%PDF-")
    if kind in ("docx", "xlsx", "pptx"):  # a zip, or a password-protected one (the reader says so)
        return head.startswith((b"PK\x03\x04", OLE))
    if kind in ("odt", "ods", "odp"):
        return head.startswith(b"PK\x03\x04")
    return head.startswith(BOMS[1:]) or b"\x00" not in head


def read(path: Path, kind: str, limit: int) -> Reading:
    """Read one non-PDF file of ``kind``; passages of at most ``limit`` characters where they can be split.
    Raises ``Unreadable`` with a code when the file can't be read."""
    reader = {"docx": read_docx, "xlsx": read_xlsx, "pptx": read_pptx, "odt": read_odt, "ods": read_ods, "odp": read_odp,
              "md": read_markdown, "csv": read_csv, "tsv": read_tsv,
              "txt": read_text, "json": read_json, "xml": read_xml, "html": read_html, "eml": read_email}.get(kind)
    if reader is None:
        raise Unreadable(f"no reader for {kind} files", "document.unsupported")
    reading = reader(Path(path), limit)
    if sum(len(p.text) for p in reading.passages) > MAX_CHARS:
        raise Unreadable("the document has too much text to be read", "document.too_large")
    return reading


# ---------------------------------------------------------------------- packing text into passages
def split_text(text: str, limit: int) -> list[str]:
    """``text`` in pieces of at most ``limit`` characters, cut at a line end or a sentence end when possible."""
    pieces = []
    text = text.strip()
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("; "))
        cut = cut + 1 if cut > limit // 3 else (window.rfind(" ") if window.rfind(" ") > limit // 3 else limit)
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    return [*pieces, text] if text else pieces


def pack(items: list[tuple[list[str], str]], limit: int) -> list[Passage]:
    """Consecutive pieces of text under the same headings joined into passages of up to ``limit`` characters."""
    out: list[Passage] = []
    current: list[str] = []
    headings: list[str] | None = None

    def flush() -> None:
        if current:
            out.append(Passage("\n\n".join(current), list(headings or [])))
            current.clear()

    for heads, text in items:
        for piece in split_text(text, limit):
            if heads != headings or (current and sum(len(c) + 2 for c in current) + len(piece) > limit):
                flush()
                headings = heads
            current.append(piece)
    flush()
    return out


def row_line(cells: list[str]) -> str:
    """One table row as a line: the cells between pipes, as in a Markdown table."""
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def rows_in_passages(rows: list[tuple[int, list[str]]], limit: int, headings: list[str] | None = None,
                     sheet: str | None = None, cells: bool = False) -> list[Passage]:
    """Rows (number, cells) as passages of up to ``limit`` characters, the first row repeated at the top
    of every later passage. With ``cells``, each passage's place is its cell range (``sheet``! A1:D9)."""
    if not rows:
        return []
    header = row_line(rows[0][1])
    out: list[Passage] = []
    group: list[tuple[int, list[str]]] = []

    def flush() -> None:
        if not group:
            return
        lines = [row_line(c) for _, c in group]
        if group[0][0] != rows[0][0]:
            lines.insert(0, header)
        place = None
        if cells:
            last_col = max(len(c) for _, c in group)
            place = (f"{sheet_ref(sheet)}!" if sheet is not None else "") + f"A{group[0][0]}:{column_letter(last_col)}{group[-1][0]}"
        out.append(Passage("\n".join(lines), list(headings or []), place))
        group.clear()

    size = 0
    for number, values in rows:
        line = len(row_line(values)) + 1
        if group and size + line > limit:
            flush()
            size = len(header) + 1
        group.append((number, values))
        size += line
    flush()
    return out


class Outline:
    """A document's body as it is read: text and tables in reading order, each under the chain of headings above
    it (Word, Markdown, HTML). A heading with nothing under it before the next heading of its level or higher is
    kept as text, so nothing is left out."""

    def __init__(self) -> None:
        self._stack: list[list] = []  # [level, heading, has something under it]
        self._items: list[tuple[str, list[str], object]] = []  # ("text", headings, text) or ("table", headings, rows)
        self._chars = 0  # counted as it is read: a small file that unfolds into too much text stops early

    def headings(self) -> list[str]:
        return [h for _, h, _ in self._stack]

    def close_to(self, level: int) -> None:
        """End the sections of ``level`` and deeper."""
        while self._stack and self._stack[-1][0] >= level:
            _, text, used = self._stack.pop()
            if not used:
                self._items.append(("text", self.headings(), text))

    def heading(self, level: int, text: str) -> None:
        """A heading of ``level`` (0 a title, 1 to 9): it ends the sections of its level and deeper."""
        self.close_to(level)
        self._stack.append([level, text, False])

    def add(self, kind: str, content) -> None:
        """Text (a string) or a table (rows of cells) under the current headings."""
        for entry in self._stack:
            entry[2] = True
        self._chars += len(content) if kind == "text" else sum(len(c) + 3 for row in content for c in row)
        if self._chars > MAX_CHARS:
            raise Unreadable("the document has too much text to be read", "document.too_large")
        self._items.append((kind, self.headings(), content))

    def passages(self, limit: int) -> list[Passage]:
        """Everything read, as passages of up to ``limit`` characters; a table's rows apart from the text."""
        self.close_to(0)
        passages: list[Passage] = []
        texts: list[tuple[list[str], str]] = []
        for kind, heads, content in self._items:
            if kind == "text":
                texts.append((heads, content))
            else:
                passages += pack(texts, limit) + rows_in_passages(list(enumerate(content, 1)), limit, heads)
                texts = []
        return passages + pack(texts, limit)


def column_letter(n: int) -> str:
    """Excel's column name for column ``n`` (1 = A, 27 = AA)."""
    letters = ""
    n = max(n, 1)
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def sheet_ref(name: str) -> str:
    """A sheet name as Excel writes it in a reference: quoted when it holds anything but letters, digits and _."""
    return name if re.fullmatch(r"[^\W\d]\w*", name) else "'" + name.replace("'", "''") + "'"


def cell_text(value) -> str:
    """A cell's value as text: whole numbers without ".0", dates as ISO dates, line breaks as spaces."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return " ".join(str(value).split())


def trimmed(cells: list[str]) -> list[str]:
    """The row without its empty cells at the end."""
    while cells and not cells[-1]:
        cells = cells[:-1]
    return cells


# ---------------------------------------------------------------------- Word
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


def check_zip(path: Path, member: str, what: str) -> None:
    """An Office file is a zip; refuse one that isn't (one protected with a password as such: Office encrypts it
    into a compound file with an EncryptionInfo stream, MS-OFFCRYPTO, read with olefile), lacks its main part, or
    unpacks to too much."""
    with open(path, "rb") as f:
        head = f.read(8)
    if head == OLE:
        import olefile

        try:
            with olefile.OleFileIO(str(path)) as ole:
                protected = ole.exists("EncryptionInfo")
        except Exception:  # noqa: BLE001 - olefile raises many kinds for a broken compound file
            protected = False
        if protected:
            raise Unreadable("the file is protected with a password", "document.password_protected")
        raise Unreadable(f"the file is not a valid {what} file", "document.damaged")
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        raise Unreadable(f"the file is not a valid {what} file", "document.damaged") from None
    if member not in {i.filename for i in infos}:
        raise Unreadable(f"the file is not a valid {what} file", "document.damaged")
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
        raise Unreadable(f"the {what} file is too large once unpacked", "document.too_large")


def _text_of(element) -> str:
    """The visible text inside a Word element: text runs (also in hyperlinks, fields' results, content
    controls and text boxes), tabs and breaks; deleted text and field codes are other elements."""
    parts = []
    for el in element.iter(f"{W}t", f"{W}tab", f"{W}br", f"{W}cr"):
        parts.append(el.text or "" if el.tag == f"{W}t" else ("\t" if el.tag == f"{W}tab" else "\n"))
    return "".join(parts).strip()


def _heading_level(paragraph, styles: dict[str, int]) -> int | None:
    """0 (Title) to 9 for a heading paragraph, None for body text."""
    ppr = paragraph.find(f"{W}pPr")
    if ppr is not None:
        outline = ppr.find(f"{W}outlineLvl")
        if outline is not None and (v := outline.get(f"{W}val", "")).isdigit() and int(v) < 9:
            return int(v) + 1
        style = ppr.find(f"{W}pStyle")
        if style is not None:
            return styles.get(style.get(f"{W}val", ""))
    return None


def _heading_styles(document) -> dict[str, int]:
    """Style id -> heading level: the built-in Title (0) and Heading 1-9 styles (Word stores their names in
    English whatever the interface language), and any style with an outline level."""
    levels: dict[str, int] = {}
    for style in document.styles.element.iter(f"{W}style"):
        sid = style.get(f"{W}styleId", "")
        name = style.find(f"{W}name")
        name = (name.get(f"{W}val", "") if name is not None else "").strip()
        outline = style.find(f"{W}pPr/{W}outlineLvl")
        if name.lower() == "title":  # above every heading: Heading 1 sections sit under it
            levels[sid] = 0
        elif (m := HEADING_STYLE.match(name)) and m.group(1) != "0":
            levels[sid] = int(m.group(1))
        elif outline is not None and (v := outline.get(f"{W}val", "")).isdigit() and int(v) < 9:
            levels[sid] = int(v) + 1
    return levels


def _table_rows(table) -> list[list[str]]:
    """A Word table's rows as cell texts; a cell merged across columns counts once."""
    rows = []
    for tr in table.iter(f"{W}tr"):
        if tr.getparent() is not table:
            continue  # a row of a table nested in a cell: part of that cell's text
        cells = [_text_of(tc).replace("\n", " ") for tc in tr.findall(f"{W}tc")]
        if any(cells):
            rows.append(trimmed(cells))
    return rows


def read_docx(path: Path, limit: int) -> Reading:
    """A Word document's body by section, its tables by rows; headers and footers as furniture."""
    import docx

    check_zip(path, "word/document.xml", "Word")
    try:
        document = docx.Document(str(path))
    except Exception:  # noqa: BLE001 - python-docx raises many kinds for a broken file
        raise Unreadable("the file is not a valid Word file", "document.damaged") from None
    styles = _heading_styles(document)
    outline = Outline()

    def walk(container) -> None:
        for el in container:
            if el.tag == f"{W}p":
                if not (text := _text_of(el)):
                    continue
                level = _heading_level(el, styles)
                if level is None:
                    outline.add("text", text)
                else:
                    outline.heading(level, " ".join(text.split()))
            elif el.tag == f"{W}tbl":
                if rows := _table_rows(el):
                    outline.add("table", rows)
            elif el.tag == f"{W}sdt":  # a content control around paragraphs or tables
                if (content := el.find(f"{W}sdtContent")) is not None:
                    walk(content)

    walk(document.element.body)
    passages = outline.passages(limit)

    furniture = []
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            try:
                if not part.is_linked_to_previous and (text := _text_of(part._element)):
                    furniture.append(text)
            except Exception:  # noqa: BLE001, S112 - a header or footer that can't be read only loses the mark check
                continue
    return Reading(passages, list(dict.fromkeys(furniture)))


# ---------------------------------------------------------------------- Excel
def read_xlsx(path: Path, limit: int) -> Reading:
    """Every worksheet's non-empty rows, as cell ranges; hidden sheets too (their text is in the file)."""
    import openpyxl

    check_zip(path, "xl/workbook.xml", "Excel")
    try:
        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - openpyxl raises many kinds for a broken file
        raise Unreadable("the file is not a valid Excel file", "document.damaged") from None
    passages: list[Passage] = []
    cells = 0
    try:
        for sheet in workbook.worksheets:
            sheet.reset_dimensions()  # some writers store wrong dimensions; read the rows as they are
            rows = []
            for number, values in enumerate(sheet.iter_rows(values_only=True), 1):
                row = trimmed([cell_text(v) for v in values])
                if row:
                    cells += sum(1 for c in row if c)
                    if cells > MAX_CELLS:
                        raise Unreadable(f"the workbook has more than {MAX_CELLS:,} filled cells".replace(",", " "), "document.too_large")
                    rows.append((number, row))
            passages += rows_in_passages(rows, limit, sheet=sheet.title, cells=True)
    finally:
        workbook.close()
    return Reading(passages)


# ---------------------------------------------------------------------- PowerPoint and slides
def _slide_passages(number: int, title: str, texts: list[str], tables: list[list[list[str]]], limit: int) -> list[Passage]:
    """One slide's passages, under its title, each numbered as the slide's page; a slide with only a title is its
    title."""
    heads = [title] if title else []
    passages = pack([(heads, t) for t in texts if t.strip()], limit)
    for rows in tables:
        passages += rows_in_passages(list(enumerate(rows, 1)), limit, heads)
    if not passages and title:
        passages = [Passage(title)]
    return [replace(p, page=number) for p in passages]


def read_pptx(path: Path, limit: int) -> Reading:
    """A PowerPoint deck slide by slide: its title as the heading, the text of its shapes (in groups too), its
    tables by rows, and its speaker notes; each slide numbered as a page, its number in the deck. Hidden slides
    too (their text is in the file, and they keep their number; a PDF export leaves them out). The footer, date and
    slide-number placeholders are furniture. Charts, SmartArt and embedded objects are not read, as in Word."""
    import pptx
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

    check_zip(path, "ppt/presentation.xml", "PowerPoint")
    try:
        deck = pptx.Presentation(str(path))
    except Exception:  # noqa: BLE001 - python-pptx raises many kinds for a broken file
        raise Unreadable("the file is not a valid PowerPoint file", "document.damaged") from None
    furniture_kinds = {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.SLIDE_NUMBER}
    passages: list[Passage] = []
    furniture: list[str] = []
    slides = 0
    for number, slide in enumerate(deck.slides, 1):
        slides = number
        title_shape = slide.shapes.title
        title = " ".join(title_shape.text_frame.text.split()) if title_shape is not None and title_shape.has_text_frame else ""
        texts: list[str] = []
        tables: list[list[list[str]]] = []
        stack = list(reversed(list(slide.shapes)))
        while stack:  # in the slide's order, groups opened in place, without recursion
            shape = stack.pop()
            try:
                group = shape.shape_type == MSO_SHAPE_TYPE.GROUP
            except NotImplementedError:  # a shape python-pptx has no type for (no geometry): read as any other
                group = False
            if group:
                stack += reversed(list(shape.shapes))
                continue
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [trimmed([" ".join(c.text.split()) for c in row.cells]) for row in shape.table.rows]
                if rows := [r for r in rows if r]:
                    tables.append(rows)
            elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                text = "\n".join(t for t in (par.text.replace("\v", "\n").strip() for par in shape.text_frame.paragraphs) if t)
                if not text:
                    continue
                if shape.is_placeholder and shape.placeholder_format.type in furniture_kinds:
                    furniture.append(" ".join(text.split()))
                else:
                    texts.append(text)
        if slide.has_notes_slide and (notes := slide.notes_slide.notes_text_frame) is not None and notes.text.strip():
            texts.append(notes.text.strip())
        passages += _slide_passages(number, title, texts, tables, limit)
    return Reading(passages, list(dict.fromkeys(furniture)), pages=slides)


# ---------------------------------------------------------------------- OpenDocument (.odt, .ods, .odp)
ODF = {name: "{urn:oasis:names:tc:opendocument:xmlns:%s}" % urn for name, urn in [
    ("office", "office:1.0"), ("text", "text:1.0"), ("table", "table:1.0"), ("draw", "drawing:1.0"),
    ("presentation", "presentation:1.0"), ("style", "style:1.0"), ("manifest", "manifest:1.0")]}
O, T, TB, D, P, S = (ODF[k] for k in ("office", "text", "table", "draw", "presentation", "style"))
ODF_NAMES = {"odt": "OpenDocument text", "ods": "OpenDocument spreadsheet", "odp": "OpenDocument presentation"}


def _odf_part(path: Path, kind: str, member: str):
    """A part of an OpenDocument file (``content.xml``, ``styles.xml``) as XML, after checking the package: a zip
    of the right type (its ``mimetype``), not encrypted, not too large unpacked. None if an optional part is
    missing. Parsed with defusedxml."""
    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import ParseError, fromstring

    what = ODF_NAMES[kind]
    check_zip(path, "content.xml", what)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "mimetype" not in names or z.read("mimetype").strip() != ODF_TYPES[kind].encode():
            raise Unreadable(f"the file is not a valid {what} file", "document.damaged")
        if "META-INF/manifest.xml" in names and b"encryption-data" in z.read("META-INF/manifest.xml"):
            raise Unreadable("the file is protected with a password", "document.password_protected")
        if member not in names:
            return None
        data = z.read(member)
    try:
        return fromstring(data)
    except DefusedXmlException:
        raise Unreadable(f"the {what} file declares entities, which aren't read", "document.unreadable") from None
    except (ParseError, RecursionError):
        raise Unreadable(f"the file is not a valid {what} file", "document.damaged") from None


OOO = "{http://openoffice.org/2009/office}"  # LibreOffice's own annotations on a slide
ANNOTATIONS = (f"{O}annotation", f"{OOO}annotation")
MAX_COLUMNS, MAX_ROWS = 16_384, 1_048_576  # a sheet's size, as Excel's and LibreOffice's


def _int(value: str | None, default: int) -> int:
    """A whole number from an attribute; ``default`` for one that isn't (the file is read, not refused, for it)."""
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _odf_text(element, notes: list[tuple[str, str]] | None = None, depth: int = 0) -> str:
    """The text of an OpenDocument paragraph or heading as it reads: spaces (text:s), tabs and line breaks kept;
    a footnote's or a comment's text goes to ``notes`` as ("note", text) or ("comment", text), never into the
    sentence it is anchored in. A shape anchored in it (a text box, a drawing) is read apart (``_anchored``)."""
    if depth > MAX_DEPTH:
        raise Unreadable(f"the file is nested more than {MAX_DEPTH} levels deep", "document.too_large")
    parts = [element.text or ""]
    for child in element:
        tag = child.tag
        if tag == f"{T}s":
            parts.append(" " * min(max(_int(child.get(f"{T}c"), 1), 1), 100))
        elif tag == f"{T}tab":
            parts.append("\t")
        elif tag == f"{T}line-break":
            parts.append("\n")
        elif tag == f"{T}note" or tag in ANNOTATIONS:
            if notes is not None:
                body = child.find(f"{T}note-body") if tag == f"{T}note" else child
                if body is not None and (note := " ".join(_odf_text(p, None, depth + 1) for p in body.iter(f"{T}p")).strip()):
                    notes.append(("note" if tag == f"{T}note" else "comment", note))
        elif tag.startswith(D) or tag in (f"{O}annotation-end", f"{T}bookmark", f"{T}bookmark-start", f"{T}bookmark-end"):
            pass
        else:
            parts.append(_odf_text(child, notes, depth + 1))
        parts.append(child.tail or "")
    return "".join(parts)


def _anchored(element) -> list:
    """The shapes anchored in a paragraph (a text box's frame, a drawing with text, a group), each once: the
    outermost ones only; what is inside a shape is read with it."""
    found, stack = [], list(reversed(list(element)))
    while stack:
        el = stack.pop()
        if el.tag.startswith(D):
            found.append(el)
        elif el.tag != f"{T}note" and el.tag not in ANNOTATIONS:
            stack += reversed(list(el))
    return found


def _odf_paragraphs(element, notes: list[tuple[str, str]], tables: bool = False, depth: int = 0) -> list[str]:
    """The text of every paragraph and heading in ``element`` (a cell, a slide's shape), in order; footnotes and
    comments to ``notes``, never into the sentence. With ``tables`` a table inside is read too, paragraph by
    paragraph (a table in a cell); without, it is left to be read by rows."""
    if depth > MAX_DEPTH:
        raise Unreadable(f"the file is nested more than {MAX_DEPTH} levels deep", "document.too_large")
    out = []
    for el in element:
        if el.tag in (f"{T}p", f"{T}h"):
            if text := _odf_text(el, notes).strip():
                out.append(text)
            for shape in _anchored(el):
                out += _odf_paragraphs(shape, notes, tables, depth + 1)
        elif el.tag in ANNOTATIONS:
            if text := " ".join(_odf_paragraphs(el, [], True, depth + 1)).strip():
                notes.append(("comment", text))
        elif tables or el.tag != f"{TB}table":
            out += _odf_paragraphs(el, notes, tables, depth + 1)
    return out


def _odf_cell(cell, values: bool, notes: list[tuple[str, str]]) -> str:
    """A table cell's text: in a spreadsheet its value as last calculated (a number, a date, true or false),
    else the text it shows, a table inside it and its footnotes included. A comment on it goes to ``notes``."""
    own: list[tuple[str, str]] = []
    shown = " ".join(" ".join([*_odf_paragraphs(cell, own, tables=True), *(n for k, n in own if k == "note")]).split())
    notes += [(k, n) for k, n in own if k == "comment"]
    if values:
        kind = cell.get(f"{O}value-type")
        try:
            if kind in ("float", "percentage", "currency") and cell.get(f"{O}value") is not None:
                return cell_text(float(cell.get(f"{O}value")))
            if kind == "date" and cell.get(f"{O}date-value"):
                return cell_text(datetime.fromisoformat(cell.get(f"{O}date-value")))
            if kind == "boolean" and cell.get(f"{O}boolean-value") is not None:
                return cell_text(cell.get(f"{O}boolean-value") == "true")
        except ValueError:
            pass  # a value that isn't what its type says: the text shown
    return shown


class Budget:
    """What one file may unfold into, counted across all its tables: filled cells and characters. OpenDocument
    writes a run of equal rows or cells once with a count, so a few bytes can stand for millions."""

    def __init__(self) -> None:
        self.cells = self.chars = 0

    def spend(self, cells: int, chars: int) -> None:
        self.cells += cells
        self.chars += chars
        if self.cells > MAX_CELLS:
            raise Unreadable(f"the file has more than {MAX_CELLS:,} filled cells".replace(",", " "), "document.too_large")
        if self.chars > MAX_CHARS:
            raise Unreadable("the document has too much text to be read", "document.too_large")


def _odf_rows(table, values: bool, budget: Budget, notes: list[tuple[str, str]]) -> list[tuple[int, list[str]]]:
    """A table's non-empty rows, numbered as a spreadsheet numbers them. Repeated rows and cells (how
    OpenDocument writes a run of equal ones, often a million empty rows) are counted, and only filled ones written
    out, within the sheet's size and ``budget``. A cell covered by a merged one is an empty cell, so the columns
    stay where they are, as in Excel."""
    rows: list[tuple[int, list[str]]] = []
    number = 0
    stack = list(reversed(list(table)))
    while stack and number < MAX_ROWS:  # rows also sit in header rows, row groups and rows elements
        el = stack.pop()
        if el.tag in (f"{TB}table-header-rows", f"{TB}table-row-group", f"{TB}table-rows"):
            stack += reversed(list(el))
            continue
        if el.tag != f"{TB}table-row":
            continue
        cells: list[str] = []
        column, empty_run = 0, 0
        for cell in el:
            if cell.tag not in (f"{TB}table-cell", f"{TB}covered-table-cell"):
                continue
            repeat = min(max(_int(cell.get(f"{TB}number-columns-repeated"), 1), 1), MAX_COLUMNS - column)
            if repeat <= 0:
                break
            column += repeat
            text = _odf_cell(cell, values, notes) if cell.tag == f"{TB}table-cell" else ""
            if not text:
                empty_run += repeat
                continue
            cells += [""] * empty_run + [text] * repeat
            empty_run = 0
        repeat = min(max(_int(el.get(f"{TB}number-rows-repeated"), 1), 1), MAX_ROWS - number)
        if cells:
            filled = sum(1 for c in cells if c)
            budget.spend(filled * repeat, sum(len(c) + 3 for c in cells) * repeat)
            rows += [(number + i + 1, cells) for i in range(repeat)]
        number += repeat
    return rows


def _outer_tables(element) -> list:
    """The outermost tables in ``element``; a table inside one is read with its cell (``_odf_cell``)."""
    found, stack = [], [element]
    while stack:
        el = stack.pop()
        if el.tag == f"{TB}table":
            found.append(el)
        else:
            stack += reversed(list(el))
    return found


def _title_styles(content) -> set[str]:
    """The paragraph styles that are the Title style or derive from it (LibreOffice writes "P1", parent "Title")."""
    names = {"Title"}
    for style in content.iter(f"{S}style"):
        if style.get(f"{S}parent-style-name") in names or style.get(f"{S}name") in names:
            names.add(style.get(f"{S}name", ""))
    return names


def _odf_body(container, outline: Outline, outside: list[str], budget: Budget, titles: set[str], depth: int = 0) -> None:
    """An OpenDocument text body into ``outline``: headings (text:h by its outline level, a Title paragraph above
    them), paragraphs, lists, sections, tables by rows, the shapes anchored in a paragraph after it; a footnote
    after its paragraph, a comment to ``outside``. Tracked deletions (text:tracked-changes) are not read: the
    document as it now reads."""
    if depth > MAX_DEPTH:
        raise Unreadable(f"the file is nested more than {MAX_DEPTH} levels deep", "document.too_large")
    for el in container:
        tag = el.tag
        if tag in (f"{T}p", f"{T}h"):
            notes: list[tuple[str, str]] = []
            text = _odf_text(el, notes).strip()
            if text and tag == f"{T}h":
                outline.heading(min(max(_int(el.get(f"{T}outline-level"), 1), 1), 10), " ".join(text.split()))
            elif text and el.get(f"{T}style-name") in titles:
                outline.heading(0, " ".join(text.split()))
            elif text:
                outline.add("text", text)
            for kind, note in notes:  # a footnote is the document's text, after its paragraph; a comment isn't
                if kind == "note":
                    outline.add("text", note)
                else:
                    outside.append(note)
            for shape in _anchored(el):
                _odf_body([shape], outline, outside, budget, titles, depth + 1)
        elif tag == f"{TB}table":
            notes = []
            if rows := [r for _, r in _odf_rows(el, False, budget, notes)]:
                outline.add("table", [trimmed(r) for r in rows])
            outside += [n for _, n in notes]
        elif tag in ANNOTATIONS:
            if text := " ".join(_odf_paragraphs(el, [])).strip():
                outside.append(text)
        elif tag == f"{T}tracked-changes" or tag == f"{O}forms" or tag.endswith("-decls"):
            continue
        else:  # lists, list items, sections, indexes, shapes and their text boxes: what holds paragraphs
            _odf_body(el, outline, outside, budget, titles, depth + 1)


def read_odt(path: Path, limit: int) -> Reading:
    """An OpenDocument text by section, as Word is read: headings (text:h, and the Title) as the chain above each
    passage, tables by rows; headers and footers (styles.xml) and comments only checked for the export mark."""
    content = _odf_part(path, "odt", "content.xml")
    body = content.find(f"{O}body/{O}text")
    if body is None:
        raise Unreadable(f"the file is not a valid {ODF_NAMES['odt']} file", "document.damaged")
    outline, outside = Outline(), []
    _odf_body(body, outline, outside, Budget(), _title_styles(content))
    styles = _odf_part(path, "odt", "styles.xml")
    if styles is not None:
        for page in styles.iter(f"{S}master-page"):
            for part in page:
                if text := " ".join(_odf_paragraphs(part, [])).strip():
                    outside.append(" ".join(text.split()))
    return Reading(outline.passages(limit), list(dict.fromkeys(outside)))


def read_ods(path: Path, limit: int) -> Reading:
    """An OpenDocument spreadsheet's sheets, their non-empty rows as cell ranges, as Excel is read: values as last
    calculated; hidden sheets too; comments on cells only checked for the export mark."""
    content = _odf_part(path, "ods", "content.xml")
    body = content.find(f"{O}body/{O}spreadsheet")
    if body is None:
        raise Unreadable(f"the file is not a valid {ODF_NAMES['ods']} file", "document.damaged")
    passages: list[Passage] = []
    budget, notes = Budget(), []
    for sheet in body.findall(f"{TB}table"):
        rows = _odf_rows(sheet, True, budget, notes)
        passages += rows_in_passages([(n, trimmed(r)) for n, r in rows], limit, sheet=sheet.get(f"{TB}name", "Sheet"), cells=True)
    return Reading(passages, list(dict.fromkeys(n for _, n in notes)))


def read_odp(path: Path, limit: int) -> Reading:
    """An OpenDocument presentation slide by slide, as PowerPoint is read: the title frame as the heading, the
    other shapes' text (groups opened), their tables by rows, the speaker notes; each slide numbered as a page.
    Footer, date and page-number frames and comments are furniture."""
    content = _odf_part(path, "odp", "content.xml")
    body = content.find(f"{O}body/{O}presentation")
    if body is None:
        raise Unreadable(f"the file is not a valid {ODF_NAMES['odp']} file", "document.damaged")
    passages: list[Passage] = []
    furniture: list[str] = []
    budget = Budget()
    slides = 0
    for number, page in enumerate(body.findall(f"{D}page"), 1):
        slides = number
        title, texts, tables = "", [], []
        notes: list[tuple[str, str]] = []
        stack = list(reversed(list(page)))
        while stack:
            el = stack.pop()
            if el.tag in (f"{P}notes", f"{D}g"):
                stack += reversed(list(el))
                continue
            if el.tag in ANNOTATIONS:
                if text := " ".join(_odf_paragraphs(el, [])).strip():
                    furniture.append(" ".join(text.split()))
                continue
            kind = el.get(f"{P}class", "")
            text = "\n".join(_odf_paragraphs(el, notes))
            for table in _outer_tables(el):
                if rows := [trimmed(r) for _, r in _odf_rows(table, False, budget, notes)]:
                    tables.append(rows)
            if not text:
                continue
            budget.spend(0, len(text))
            if kind == "title" and not title:
                title = " ".join(text.split())
            elif kind in ("footer", "date-time", "page-number", "header"):
                furniture.append(" ".join(text.split()))
            else:
                texts.append(text)
        furniture += [n for _, n in notes]
        passages += _slide_passages(number, title, texts, tables, limit)
    return Reading(passages, list(dict.fromkeys(furniture)), pages=slides)


# ---------------------------------------------------------------------- text files
def encoding(data: bytes) -> str:
    """The encoding a text file is read in: UTF-16 by its byte-order mark (what Windows calls "Unicode"), UTF-8
    (with or without a byte-order mark), else Windows-1252, the code page Excel and older tools use for "CSV" and
    text in Belgium."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "windows-1252"
    return "utf-8"


def decode(data: bytes) -> str:
    """A text file's content, in its ``encoding``."""
    name = encoding(data)
    return data.decode("utf-8-sig" if name == "utf-8" else name, errors="replace")


def content_type(data: bytes, kind: str) -> str:
    """The type a kept file is served as (``CONTENT_TYPE``), a text file's with the character set it was read in,
    so "Open document" shows its accents as they are."""
    if kind not in TEXT_KINDS or kind == "eml":
        return CONTENT_TYPE.get(kind, "application/octet-stream")
    name = html_encoding(data) if kind == "html" else encoding(data)
    return f"text/plain; charset={name}"


class Semicolons(csv.excel):
    delimiter = ";"


def _rows(text: str, dialect) -> list[tuple[int, list[str]]]:
    """A delimited file's non-empty rows, numbered as a spreadsheet numbers them."""
    rows = []
    cells = 0
    for number, values in enumerate(csv.reader(io.StringIO(text), dialect), 1):
        row = trimmed([" ".join(v.split()) for v in values])
        if row:
            cells += sum(1 for c in row if c)
            if cells > MAX_CELLS:
                raise Unreadable(f"the file has more than {MAX_CELLS:,} filled cells".replace(",", " "), "document.too_large")
            rows.append((number, row))
    return rows


def read_csv(path: Path, limit: int) -> Reading:
    """A CSV file's rows, as cell ranges. Semicolons, commas or tabs, whichever the file uses."""
    text = decode(path.read_bytes())
    sample = "\n".join(text.splitlines()[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:  # one column, or too irregular to tell: semicolons, as Belgian Excel writes them
        dialect = Semicolons if sample.count(";") >= sample.count(",") else csv.excel
    return Reading(rows_in_passages(_rows(text, dialect), limit, cells=True))


def read_tsv(path: Path, limit: int) -> Reading:
    """A TSV file's rows (tab-separated values, as IANA's text/tab-separated-values), as cell ranges."""
    return Reading(rows_in_passages(_rows(decode(path.read_bytes()), csv.excel_tab), limit, cells=True))


def read_text(path: Path, limit: int) -> Reading:
    """A plain text file by paragraph: the text between blank lines."""
    text = decode(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    return Reading(pack([([], p.strip()) for p in re.split(r"\n[ \t]*\n", text) if p.strip()], limit))


ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
FENCE = re.compile(r"^ {0,3}(```|~~~)")
COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)


def read_markdown(path: Path, limit: int) -> Reading:
    """A Markdown file by section (# headings and underlined ones); comments as furniture."""
    text = decode(path.read_bytes()).replace("\r\n", "\n")
    furniture = [" ".join(c.split()) for c in COMMENT.findall(text) if c.strip()]
    text = COMMENT.sub("", text)
    outline = Outline()
    paragraph: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(paragraph).strip()
        paragraph.clear()
        if body:
            outline.add("text", body)

    for line in text.split("\n"):
        if FENCE.match(line):
            in_fence = not in_fence
            paragraph.append(line)
        elif in_fence:
            paragraph.append(line)
        elif m := ATX.match(line):
            flush()
            outline.heading(len(m.group(1)), m.group(2).strip())
        elif (m := SETEXT.match(line)) and len(paragraph) == 1 and paragraph[0].strip():
            title = paragraph.pop().strip()
            outline.heading(1 if m.group(1)[0] == "=" else 2, title)
        elif not line.strip():
            flush()
        else:
            paragraph.append(line)
    flush()
    return Reading(outline.passages(limit), furniture)


# ---------------------------------------------------------------------- JSON and XML: one line per value
def _paths_in_passages(lines: list[tuple[tuple, str]], limit: int, where) -> list[Passage]:
    """Lines (path, "where: value") as passages of up to ``limit`` characters, each placed at the deepest path
    its lines share (``where`` writes a path as the standard does; None for the whole document). A line longer
    than ``limit`` is cut, each piece placed at its own path."""
    out: list[Passage] = []
    group: list[tuple[tuple, str]] = []

    def flush() -> None:
        if group:
            shared = group[0][0]
            for path, _ in group[1:]:
                n = 0
                while n < min(len(shared), len(path)) and shared[n] == path[n]:
                    n += 1
                shared = shared[:n]
            out.append(Passage("\n".join(line for _, line in group), [], where(shared)))
            group.clear()

    size = 0
    for path, line in lines:
        if len(line) > limit:
            flush()
            size = 0
            out += [Passage(piece, [], where(path)) for piece in split_text(line, limit)]
            continue
        if group and size + len(line) + 1 > limit:
            flush()
            size = 0
        group.append((path, line))
        size += len(line) + 1
    flush()
    return out


def json_pointer(path: tuple) -> str | None:
    """A path of keys and indexes as a JSON Pointer (RFC 6901: "/parties/0/name", "~" and "/" escaped)."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in path) or None


def read_json(path: Path, limit: int) -> Reading:
    """A JSON file's values, one line each ("/parties/0/name: Lotte Verbeke"), in the file's order; empty
    objects and arrays hold nothing to read."""
    try:
        document = json.loads(decode(path.read_bytes()))
    except (ValueError, RecursionError):
        raise Unreadable("the file is not valid JSON", "document.damaged") from None
    lines: list[tuple[tuple, str]] = []
    stack: list[tuple[tuple, object]] = [((), document)]
    while stack:  # depth first, in the file's order, without recursion (a deeply nested file can't exhaust it)
        where, value = stack.pop()
        if len(where) > MAX_DEPTH:
            raise Unreadable(f"the file is nested more than {MAX_DEPTH} levels deep", "document.too_large")
        if isinstance(value, dict):
            stack += [((*where, k), v) for k, v in reversed(list(value.items()))]
        elif isinstance(value, list):
            stack += [((*where, i), v) for i, v in reversed(list(enumerate(value)))]
        else:
            text = " ".join(value.split()) if isinstance(value, str) else json.dumps(value)
            lines.append((where, f"{json_pointer(where)}: {text}" if where else text))
            if len(lines) > MAX_CELLS:
                raise Unreadable(f"the file has more than {MAX_CELLS:,} values".replace(",", " "), "document.too_large")
    return Reading(_paths_in_passages(lines, limit, json_pointer))


def _local(name: str) -> str:
    """An XML name without its namespace ("{urn:x}deed" -> "deed")."""
    return name.rsplit("}", 1)[-1]


def xpath(path: tuple) -> str | None:
    """A path of steps as an XPath of local names ("/deed/party[2]/name"; a namespace is left out, as people
    read the file); None for the whole document."""
    return "".join("/" + step for step in path) or None


def read_xml(path: Path, limit: int) -> Reading:
    """An XML file's attributes and text, one line each ("/deed/party[2]/name: Lotte Verbeke", "/deed/@id: 7"),
    in document order. Read with defusedxml: a file that declares entities or points outside itself isn't read."""
    import defusedxml
    from defusedxml.ElementTree import ParseError
    from defusedxml.ElementTree import parse as parse_xml

    try:
        root = parse_xml(str(path)).getroot()
    except defusedxml.DefusedXmlException:
        raise Unreadable("the XML file declares entities or refers to other files, which aren't read", "document.unreadable") from None
    except (ParseError, RecursionError):
        raise Unreadable("the file is not valid XML", "document.damaged") from None
    lines: list[tuple[tuple, str]] = []
    stack: list[tuple[tuple, object]] = [((_local(root.tag),), root)]
    while stack:
        if len(lines) > MAX_CELLS:
            raise Unreadable(f"the file has more than {MAX_CELLS:,} values".replace(",", " "), "document.too_large")
        where, el = stack.pop()
        if len(where) > MAX_DEPTH:
            raise Unreadable(f"the file is nested more than {MAX_DEPTH} levels deep", "document.too_large")
        for name, value in el.attrib.items():
            if value.strip():
                lines.append((where, f"{xpath(where)}/@{_local(name)}: {' '.join(value.split())}"))
        own = " ".join(" ".join([el.text or "", *(child.tail or "" for child in el)]).split())
        if own and len(el):  # mixed content, prose with markup ("Some <b>bold</b> text"): its whole text, as it reads
            lines.append((where, f"{xpath(where)}: {' '.join(''.join(el.itertext()).split())}"))
            continue
        if own:
            lines.append((where, f"{xpath(where)}: {own}"))
        children = [c for c in el if isinstance(c.tag, str)]
        named: dict[str, int] = {}
        for c in children:
            named[_local(c.tag)] = named.get(_local(c.tag), 0) + 1
        seen: dict[str, int] = {}
        steps = []
        for c in children:  # as XPath counts: a position only where siblings share the name
            name = _local(c.tag)
            seen[name] = seen.get(name, 0) + 1
            steps.append(((*where, f"{name}[{seen[name]}]" if named[name] > 1 else name), c))
        stack += reversed(steps)
    return Reading(_paths_in_passages(lines, limit, xpath))


# ---------------------------------------------------------------------- HTML
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_:.-]+)""", re.IGNORECASE)


def html_encoding(data: bytes) -> str:
    """An HTML page's encoding: by its byte-order mark, else the one a meta tag says (in its first 1,024 bytes, as
    browsers look), else as any text file's (``encoding``). Latin-1 and ASCII are read as Windows-1252, as browsers
    read them."""
    if not data.startswith(BOMS) and (m := META_CHARSET.search(data[:1024])):
        try:
            name = codecs.lookup(m.group(1).decode("ascii")).name
        except LookupError:
            name = None
        if name:
            return "windows-1252" if name in ("latin-1", "iso8859-1", "ascii", "cp1252") else name
    return encoding(data)


def decode_html(data: bytes) -> str:
    """An HTML page's text, in its ``html_encoding``."""
    name = html_encoding(data)
    return data.decode("utf-8-sig" if name == "utf-8" else name, errors="replace")


BREAK = "\u2028"  # a <br> while a block's text is gathered (Unicode's line separator)


class _Page(HTMLParser):
    """An HTML page into an ``Outline``: h1 to h6 as headings, tables by row, the rest by block; scripts, styles
    and the head (but for its title, kept as furniture) left out. A head ends at its end tag or at the first tag a
    head can't hold, as browsers read a page that leaves it out."""

    SKIP = {"script", "style"}  # never shown; the parser reads them as raw text up to their end tag
    # What a head may hold (HTML's metadata content): any other tag ends a head whose end tag was left out, as
    # browsers do; only a page's title is kept from it, as furniture.
    HEAD = {"head", "title", "meta", "link", "base", "style", "script", "noscript", "template"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "dl", "dt", "dd", "blockquote", "pre", "section", "article", "header",
             "footer", "nav", "aside", "main", "figure", "figcaption", "address", "hr", "form", "fieldset", "details",
             "summary", "caption", "body", "html"}
    HEADINGS = {f"h{n}": n for n in range(1, 7)}

    def __init__(self, outline: Outline) -> None:
        super().__init__(convert_charrefs=True)
        self.outline = outline
        self.furniture: list[str] = []
        self.skip = 0           # inside a tag whose content isn't read
        self.head = False       # inside the head
        self.pre = 0
        self.title: list[str] | None = None
        self.text: list[str] = []
        self.heading: tuple[int, list[str]] | None = None
        self.tables = 0         # how deep in tables: only the outermost is kept as rows
        self.rows: list[list[str]] = []
        self.cell: list[str] | None = None

    def flush(self) -> None:
        joined = "".join(self.text)
        self.text = []
        if self.pre:
            text = "\n".join(line.strip() for line in joined.replace(BREAK, "\n").strip("\n").split("\n"))
        else:  # whitespace as a browser shows it: runs collapsed, a line only where <br> breaks it
            text = "\n".join(line for line in (" ".join(part.split()) for part in joined.split(BREAK)) if line)
        if text.strip():
            self.outline.add("text", text.strip())

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.head = True
            return
        if self.head and tag not in self.HEAD:
            self.head = False
        if tag == "title" and self.head and self.title is None:
            self.title = []
            return
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            self.tables += 1
            if self.tables == 1:
                self.flush()
                self.rows = []
            return
        if self.tables == 1 and tag == "tr":
            self.rows.append([])
        elif self.tables == 1 and tag in ("td", "th"):
            self.cell = []
        elif self.tables > 1 and tag in ("td", "th", "tr") and self.cell is not None:
            self.cell.append(" ")
        elif tag in self.HEADINGS and self.tables == 0:
            self.flush()
            self.heading = (self.HEADINGS[tag], [])
        elif tag == "br":
            (self.cell if self.cell is not None else self.text).append(BREAK if self.cell is None else " ")
        elif tag in self.BLOCK and self.tables == 0:
            if tag == "pre":
                self.flush()
                self.pre += 1
            elif not self.pre:
                self.flush()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "hr") and tag in self.SKIP | self.BLOCK | set(self.HEADINGS):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "head":
            self.head = False
            return
        if tag == "title" and self.title:
            if title := " ".join("".join(self.title).split()):
                self.furniture.append(title)
            self.title = None
            return
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "table" and self.tables:
            self.tables -= 1
            if self.tables == 0:
                self.end_cell()
                self.flush()
                if rows := [trimmed(r) for r in self.rows if any(r)]:
                    self.outline.add("table", rows)
                self.rows = []
            return
        if self.tables == 1 and tag in ("td", "th"):
            self.end_cell()
        elif tag in self.HEADINGS and self.heading is not None and self.tables == 0:
            level, parts = self.heading
            self.heading = None
            if text := " ".join("".join(parts).split()):
                self.outline.heading(level, text)
        elif tag in self.BLOCK and self.tables == 0:
            if tag == "pre":
                self.flush()
                self.pre = max(0, self.pre - 1)
            elif not self.pre:
                self.flush()

    def end_cell(self) -> None:
        if self.cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(" ".join("".join(self.cell).split()))
            self.cell = None

    def handle_data(self, data):
        if self.title is not None:
            self.title.append(data)
            return
        if self.head and not self.skip and data.strip():
            self.head = False  # text the head can't hold: the body has begun, as browsers read it
        if self.skip or self.head:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.heading is not None:
            self.heading[1].append(data)
        else:
            self.text.append(data)

    def handle_comment(self, data):
        if data.strip():
            self.furniture.append(" ".join(data.split()))

    def finish(self) -> list[str]:
        self.close()
        if self.title:  # a title never closed: what followed it is the page
            self.handle_data("")
            self.text.append("".join(self.title))
            self.title = None
        self.end_cell()
        if self.tables and (rows := [trimmed(r) for r in self.rows if any(r)]):  # a table never closed
            self.outline.add("table", rows)
        if self.heading is not None and (text := " ".join("".join(self.heading[1]).split())):
            self.outline.heading(self.heading[0], text)
        self.flush()
        return self.furniture


def read_html(path: Path, limit: int) -> Reading:
    """An HTML page by section (h1 to h6), its tables by rows; its title and comments as furniture."""
    outline = Outline()
    page = _Page(outline)
    page.feed(decode_html(path.read_bytes()))
    furniture = page.finish()
    return Reading(outline.passages(limit), furniture)


# ---------------------------------------------------------------------- email
EMAIL_FIELDS = ("From", "To", "Cc", "Date", "Subject")  # RFC 5322's own field names, the same in every language
MAX_EMAIL_DEPTH = 20  # parts inside parts: deeper than any mail program writes


MAX_EMAIL_PARTS = 5_000  # parts in one email: far beyond a real one's, and bounds the parsing
BOUNDARY_LINE = re.compile(rb"^--", re.MULTILINE)  # every part starts at one (RFC 2046); a signature's "-- " counts too


def parse_email(data: bytes) -> EmailMessage:
    """An .eml file (RFC 5322 with MIME) as Python's email package reads it, with today's rules. Raises
    ``Unreadable`` for one it can't take apart (nested past Python's recursion limit, say), or with more parts
    than any real email has (counted before parsing, which costs time and memory for each)."""
    if len(BOUNDARY_LINE.findall(data)) > MAX_EMAIL_PARTS:
        raise Unreadable(f"the email has more than {MAX_EMAIL_PARTS} parts", "document.too_large")
    try:
        message = email.message_from_bytes(data, policy=email.policy.default)
    except (RecursionError, email.errors.MessageError, ValueError, TypeError, IndexError, LookupError):
        raise Unreadable("the email can't be taken apart", "document.damaged") from None
    return message


@dataclass
class EmailParts:
    """What an email holds: the text people read (the body, and any other text part shown with it, as a mailing
    list's footer), and everything else as attachments with their file names."""

    texts: list[EmailMessage]
    attachments: list[tuple[str, EmailMessage]]


def email_parts(message: EmailMessage) -> EmailParts:
    """Every part of the email, once: the body (the plain text, or else the HTML: RFC 2046's alternatives, as a
    mail program picks), other text parts shown inline, and the rest as attachments, a picture shown in the HTML
    too. Only the body's other renderings are left out (the text of its alternatives; a file among them is
    listed, a calendar invitation too), and the parts of an email forwarded inside it ("message/rfc822"), which is an attachment of its own. A part without a file name is
    "attachment-N" with the extension of its type. Raises ``Unreadable`` when it can't be taken apart."""
    import mimetypes

    try:
        try:
            body = message.get_body(preferencelist=("plain", "html"))
        except (KeyError, LookupError, ValueError):
            body = None
        others: set[int] = set()  # the body's other renderings: text in its alternatives
        texts: list[EmailMessage] = []
        attachments: list[tuple[str, EmailMessage]] = []
        stack: list[tuple[EmailMessage, int, list[EmailMessage]]] = [(message, 0, [])]
        found: list[tuple[EmailMessage, list[EmailMessage]]] = []
        while stack:  # depth first, in the email's order, without recursion
            part, depth, parents = stack.pop()
            if part is not message and part.get_content_type() == "message/rfc822":
                found.append((part, parents))
            elif part.is_multipart():
                if depth >= MAX_EMAIL_DEPTH:
                    raise Unreadable("the email has parts nested too deep", "document.damaged")
                stack += [(p, depth + 1, [*parents, part]) for p in reversed(list(part.iter_parts()))]
            else:
                found.append((part, parents))
        if body is not None:
            parents = next((ps for p, ps in found if p is body), [])
            for ancestor, child in zip(parents, [*parents[1:], body]):
                if ancestor.get_content_type() == "multipart/alternative":  # only the other text: a file in them is listed
                    others |= {id(p) for p, ps in found if ancestor in ps and child not in ps and p is not child
                               and p.get_content_type() in ("text/plain", "text/html") and not p.get_filename()
                               and p.get_content_disposition() != "attachment"}
        for part, _ in found:
            if part is body:
                texts.append(part)
                continue
            if id(part) in others:
                continue
            name = part.get_filename()
            if (part.get_content_type() in ("text/plain", "text/html") and not name
                    and part.get_content_disposition() != "attachment"):
                texts.append(part)  # shown with the body
                continue
            extension = ".eml" if part.get_content_type() == "message/rfc822" else mimetypes.guess_extension(part.get_content_type()) or ""
            attachments.append((name or f"attachment-{len(attachments) + 1}{extension}", part))
    except (RecursionError, email.errors.MessageError, ValueError, TypeError, IndexError, LookupError):
        raise Unreadable("the email can't be taken apart", "document.damaged") from None
    return EmailParts(texts, attachments)


def email_text(part: EmailMessage) -> str:
    """A text part's content, in the character set it says (else as a text file is read)."""
    try:
        content = part.get_content()
    except (LookupError, ValueError, AttributeError):
        content = part.get_payload(decode=True) or b""
    return decode(content) if isinstance(content, bytes) else content


def read_email(path: Path, limit: int) -> Reading:
    """An email: who sent it to whom, when and its subject (RFC 5322's field names), then its text; all under its
    subject. Its attachments are documents of their own (``service``)."""
    message = parse_email(path.read_bytes())
    parts = email_parts(message)
    outline = Outline()
    fields = []
    for name in EMAIL_FIELDS:
        try:
            value = message.get(name)
            value = " ".join(str(value).split()) if value is not None else ""
        except (ValueError, TypeError, IndexError, LookupError, RecursionError):  # a header that can't be made sense of:
            raw = next((v for k, v in message.raw_items() if k.lower() == name.lower()), "")  # as written
            value = " ".join(str(raw).split())
        if value:
            fields.append((name, value))
    if subject := dict(fields).get("Subject"):
        outline.heading(0, subject)
    if fields:
        outline.add("text", "\n".join(f"{n}: {v}" for n, v in fields))
    furniture: list[str] = []
    for part in parts.texts:
        content = email_text(part)
        if part.get_content_subtype() == "html":
            page = _Page(outline)
            page.feed(content)
            furniture += page.finish()
        else:
            for paragraph in re.split(r"\n[ \t]*\n", content.replace("\r\n", "\n")):
                if paragraph.strip():
                    outline.add("text", paragraph.strip())
    return Reading(outline.passages(limit), furniture)
