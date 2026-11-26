"""Uploads read directly (suveryn_rag.formats): Word, Excel, PowerPoint, OpenDocument, Markdown, CSV and TSV, text,
JSON, XML, HTML and an email's message: passages with their section, cells, path or slide, nothing left out, and sūveryn's export mark found
wherever the export puts it. Fictional documents only."""
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
openpyxl = pytest.importorskip("openpyxl")
from suveryn_rag import formats
from suveryn_rag.formats import (
    Passage,
    cell_text,
    column_letter,
    kind_of,
    read,
    rows_in_passages,
    sheet_ref,
    split_text,
)
from suveryn_rag.marks import find_mark
from suveryn_rag.reading import Unreadable

FIXTURES = Path(__file__).with_name("fixtures")
LIMIT = 1152  # chunk_max_tokens * 3, as the reader is configured


def texts(reading):
    return [(p.headings, p.text, p.place) for p in reading.passages]


# ---------------------------------------------------------------------- the pieces
def test_kinds_by_extension():
    assert [kind_of(n) for n in ("a.PDF", "b.docx", "c.xlsx", "d.md", "e.markdown", "f.csv")] == \
        ["pdf", "docx", "xlsx", "md", "md", "csv"]
    assert [kind_of(n) for n in ("a.TXT", "b.tsv", "c.json", "d.xml", "e.html", "f.htm", "g.eml")] == \
        ["txt", "tsv", "json", "xml", "html", "html", "eml"]
    assert [kind_of(n) for n in ("a.pptx", "b.ODT", "c.ods", "d.odp")] == ["pptx", "odt", "ods", "odp"]
    assert [kind_of(n) for n in ("a.doc", "b.xls", "c.xlsm", "d.rtf", "e.ppt", "f.pptm", "noextension")] == [None] * 7


def test_cell_references_are_written_as_excel_writes_them():
    assert [column_letter(n) for n in (1, 26, 27, 52, 703)] == ["A", "Z", "AA", "AZ", "AAA"]
    assert sheet_ref("Prices") == "Prices" and sheet_ref("Sheet_2") == "Sheet_2"
    assert sheet_ref("Price list") == "'Price list'" and sheet_ref("O'Brien") == "'O''Brien'"
    assert sheet_ref("2026") == "'2026'"


def test_cell_values_as_text():
    assert [cell_text(v) for v in (None, 300000.0, 0.21, True, "  two\nlines ")] == ["", "300000", "0.21", "TRUE", "two lines"]
    assert cell_text(datetime(2026, 10, 19)) == "2026-10-19"  # noqa: DTZ001 - Excel dates have no time zone
    assert cell_text(datetime(2026, 10, 19, 14, 30)) == "2026-10-19 14:30"  # noqa: DTZ001


def test_long_text_is_cut_at_a_sentence_or_line_and_nothing_is_lost():
    text = " ".join(f"Sentence number {i} says something." for i in range(100))
    pieces = split_text(text, 200)
    assert all(len(p) <= 200 for p in pieces) and all(p.endswith(".") for p in pieces)
    assert " ".join(pieces) == text
    assert split_text("x" * 450, 200) == ["x" * 200, "x" * 200, "x" * 50]  # no space at all: a hard cut


def test_rows_are_split_with_the_first_row_repeated_and_their_cells_named():
    rows = [(1, ["Item", "Amount"])] + [(n, [f"item {n}", str(n * 100)]) for n in range(2, 40)]
    passages = rows_in_passages(rows, 200, sheet="Prices", cells=True)
    assert len(passages) > 1 and passages[0].place.startswith("Prices!A1:B")
    for p in passages[1:]:
        assert p.text.startswith("| Item | Amount |\n")
        assert len(p.text) <= 200
    first_rows = [int(p.place.split("!A")[1].split(":")[0]) for p in passages]
    last_rows = [int(p.place.rsplit("B", 1)[1]) for p in passages]
    assert first_rows[0] == 1 and last_rows[-1] == 39
    assert all(first == last + 1 for first, last in zip(first_rows[1:], last_rows, strict=False))  # no row twice, none left out


# ---------------------------------------------------------------------- Word
def word(tmp_path, build) -> Path:
    d = docx.Document()
    build(d)
    path = tmp_path / "test.docx"
    d.save(path)
    return path


def test_word_passages_carry_their_section_and_tables_their_rows(tmp_path):
    def build(d):
        d.add_paragraph("Deed of sale", style="Title")
        d.add_paragraph("Before us, the notary.")
        d.add_heading("Article 1. Parties", 1)
        d.add_paragraph("The seller is A. The buyer is B.")
        d.add_heading("Article 2", 1)
        d.add_heading("2.1 Price", 2)
        d.add_paragraph("The price is EUR 300,000.")
        t = d.add_table(rows=3, cols=2)
        for (r, c), v in {(0, 0): "Item", (0, 1): "Amount", (1, 0): "Price", (1, 1): "300,000"}.items():
            t.cell(r, c).text = v
        t.cell(2, 0).merge(t.cell(2, 1)).text = "Paid on signing"
        d.add_heading("2.2 Costs", 2)  # nothing under it: still a passage
        d.add_heading("Article 3. Occupancy", 1)
        d.add_paragraph("Vacant.")

    r = read(word(tmp_path, build), "docx", LIMIT)
    assert texts(r) == [
        (["Deed of sale"], "Before us, the notary.", None),
        (["Deed of sale", "Article 1. Parties"], "The seller is A. The buyer is B.", None),
        (["Deed of sale", "Article 2", "2.1 Price"], "The price is EUR 300,000.", None),
        (["Deed of sale", "Article 2", "2.1 Price"], "| Item | Amount |\n| Price | 300,000 |\n| Paid on signing |", None),
        (["Deed of sale", "Article 2"], "2.2 Costs", None),
        (["Deed of sale", "Article 3. Occupancy"], "Vacant.", None),
    ]
    assert r.furniture == []


def test_word_text_in_content_controls_and_tracked_changes(tmp_path):
    from docx.oxml import parse_xml

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def build(d):
        body = d.element.body
        sect = body[-1]
        body.insert(len(body) - 1, parse_xml(
            f'<w:sdt {w}><w:sdtContent><w:p><w:r><w:t>Filled in a content control.</w:t></w:r></w:p></w:sdtContent></w:sdt>'))
        body.insert(len(body) - 1, parse_xml(
            f'<w:p {w}><w:r><w:t xml:space="preserve">Kept </w:t></w:r><w:del w:id="1" w:author="x"><w:r><w:delText>deleted</w:delText></w:r></w:del>'
            f'<w:ins w:id="2" w:author="x"><w:r><w:t>inserted</w:t></w:r></w:ins></w:p>'))
        assert sect is body[-1]

    r = read(word(tmp_path, build), "docx", LIMIT)
    assert [p.text for p in r.passages] == ["Filled in a content control.\n\nKept inserted"]  # one section: one passage


def test_a_paragraph_with_an_outline_level_is_a_heading(tmp_path):
    from docx.oxml import parse_xml

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def build(d):
        body = d.element.body
        body.insert(0, parse_xml(f'<w:p {w}><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Conditions</w:t></w:r></w:p>'))
        d.add_paragraph("No suspensive conditions.")

    assert texts(read(word(tmp_path, build), "docx", LIMIT)) == [(["Conditions"], "No suspensive conditions.", None)]


def test_word_footers_are_furniture_where_the_mark_is_found(tmp_path):
    def build(d):
        d.add_paragraph("The answer.")
        d.sections[0].footer.paragraphs[0].text = "Made by sūveryn: answer · sūveryn-ref A-0123abcd"

    r = read(word(tmp_path, build), "docx", LIMIT)
    assert [p.text for p in r.passages] == ["The answer."]  # the footer is not a passage
    assert find_mark(r.furniture)["ref"] == "A-0123abcd"


def test_a_word_answer_exported_by_the_chat_carries_the_mark():
    """fixtures/marked-answer.docx: an answer exported to Word by the chat UI (lib/office.ts), as
    downloaded; the mark is its footer line. The same file saved as PDF is marked-answer.pdf."""
    r = read(FIXTURES / "marked-answer.docx", "docx", LIMIT)
    assert r.passages and r.passages[0].headings == ["What is the price?"]
    found = find_mark([*r.furniture, *(p.text for p in r.passages)])
    assert found and found["ref"] == "A-e063906e" and found["kind"] == "answer"


# ---------------------------------------------------------------------- Excel and CSV
def test_every_sheet_by_rows_with_their_cells(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Prices"
    ws.append(["Item", "Amount", "Date"])
    ws.append(["Price", 300000, datetime(2026, 10, 19)])  # noqa: DTZ001 - Excel dates have no time zone
    ws.append([])                     # an empty row is skipped, its number isn't reused
    ws.append([None, None, "late"])   # a row starting in column C
    hidden = wb.create_sheet("Price list")
    hidden.sheet_state = "hidden"     # hidden sheets are read too: their text is in the file
    hidden["B2"] = "=1+1"             # a formula never written by Excel has no value to read
    hidden["A3"] = "Note"
    path = tmp_path / "t.xlsx"
    wb.save(path)
    assert texts(read(path, "xlsx", LIMIT)) == [
        ([], "| Item | Amount | Date |\n| Price | 300000 | 2026-10-19 |\n|  |  | late |", "Prices!A1:C4"),
        ([], "| Note |", "'Price list'!A3:A3"),
    ]


def test_an_excel_table_exported_by_the_chat_carries_the_mark():
    """fixtures/marked-table.xlsx: a table exported to Excel by the chat UI (lib/office.ts); the mark is
    the last row of the sources sheet."""
    r = read(FIXTURES / "marked-table.xlsx", "xlsx", LIMIT)
    assert [p.place for p in r.passages] == ["Table!A1:C2", "Sources!A1:D4"]
    found = find_mark([p.text for p in r.passages])
    assert found and found["ref"] == "A-31710045"


def test_csv_with_semicolons_commas_or_tabs_and_in_windows_encoding(tmp_path):
    for content, encoding in [("Name;Amount\nA;1,5\nRené;2\n", "cp1252"), ("Name,Amount\nA,\"1,5\"\nRené,2\n", "utf-8-sig"),
                              ("Name\tAmount\nA\t1,5\nRené\t2\n", "utf-8")]:
        path = tmp_path / "t.csv"
        path.write_bytes(content.encode(encoding))
        assert texts(read(path, "csv", LIMIT)) == [([], "| Name | Amount |\n| A | 1,5 |\n| René | 2 |", "A1:B3")]


def test_a_spreadsheet_too_large_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(formats, "MAX_CELLS", 5)
    path = tmp_path / "t.csv"
    path.write_text("a;b\nc;d\ne;f\n")
    with pytest.raises(ValueError, match="more than 5 filled cells"):
        read(path, "csv", LIMIT)


# ---------------------------------------------------------------------- Markdown
def test_markdown_by_section_with_comments_as_furniture(tmp_path):
    path = tmp_path / "t.md"
    path.write_text("# Deed\n\nIntroduction.\n\n## Price\nThe price is EUR 300,000.\n\nOccupancy\n---------\n\nVacant.\n\n"
                    "# Annexes\n<!-- Made by sūveryn: answer · sūveryn-ref A-0123abcd -->\n"
                    "```\n# a comment in code, not a heading\n```\n\n# Nothing under this\n", encoding="utf-8")
    r = read(path, "md", LIMIT)
    assert texts(r) == [
        (["Deed"], "Introduction.", None),
        (["Deed", "Price"], "The price is EUR 300,000.", None),
        (["Deed", "Occupancy"], "Vacant.", None),
        (["Annexes"], "```\n# a comment in code, not a heading\n```", None),
        ([], "Nothing under this", None),
    ]
    assert find_mark(r.furniture)["ref"] == "A-0123abcd"


# ---------------------------------------------------------------------- broken files
@pytest.mark.parametrize("kind, content, says", [
    ("docx", b"PK\x03\x04 not really a zip", "not a valid Word file"),
    ("xlsx", b"PK\x03\x04 not really a zip", "not a valid Excel file"),
])
def test_a_broken_office_file_is_refused_with_a_reason(tmp_path, kind, content, says):
    path = tmp_path / f"t.{kind}"
    path.write_bytes(content)
    with pytest.raises(ValueError, match=says):
        read(path, kind, LIMIT)


def test_a_word_file_that_is_really_a_workbook_or_unpacks_too_large_is_refused(tmp_path, monkeypatch):
    wb = openpyxl.Workbook()
    path = tmp_path / "t.docx"
    wb.save(path)
    with pytest.raises(ValueError, match="not a valid Word file"):
        read(path, "docx", LIMIT)
    monkeypatch.setattr(formats, "MAX_UNPACKED_BYTES", 100)
    with pytest.raises(ValueError, match="too large once unpacked"):
        read(path, "xlsx", LIMIT)


def test_passages_are_plain_data():
    assert Passage("x") == Passage("x", [], None)


def test_the_reader_reads_these_formats_without_the_pdf_pipeline(tmp_path):
    """The reader process's Extractor sends a .docx, .xlsx, .md or .csv to formats (no OCR, no layout model)."""
    from suveryn_rag.config import RagSettings
    from suveryn_rag.extract import Extractor

    reader = Extractor.__new__(Extractor)  # without loading Docling's models
    reader.settings = RagSettings(chunk_max_tokens=100)
    path = tmp_path / "notes.md"
    path.write_text("# Price\n\n" + "The price is fixed. " * 40)
    ex = reader.extract(path)
    assert ex.document is None and ex.pages == 0 and ex.furniture == []
    assert all(p.headings == ["Price"] and len(p.text) <= 300 for p in ex.passages) and len(ex.passages) > 1


# ---------------------------------------------------------------------- text and data files (suveryn-tracker#267)
def write(tmp_path: Path, name: str, data: str | bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def test_a_text_file_is_read_by_paragraph_in_whatever_encoding_windows_wrote_it(tmp_path):
    text = "Article 1.\r\nThe price is € 300 000.\r\n\r\n  \r\nArticle 2.\r\nThe parties agree.\r\n"
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "cp1252"):
        reading = read(write(tmp_path, f"deed-{encoding}.txt", text.encode(encoding)), "txt", LIMIT)
        assert texts(reading) == [([], "Article 1.\nThe price is € 300 000.\n\nArticle 2.\nThe parties agree.", None)], encoding
    many = "\n\n".join(f"Paragraph {i} says something." for i in range(200))
    reading = read(write(tmp_path, "long.txt", many), "txt", LIMIT)
    assert len(reading.passages) > 1 and all(len(p.text) <= LIMIT for p in reading.passages)
    assert "\n\n".join(p.text for p in reading.passages) == many  # nothing lost


def test_a_utf16_text_file_isnt_taken_for_a_binary_one():
    assert formats.looks_like("txt", "Dear".encode("utf-16")[:8]) and formats.looks_like("csv", (b"\xfe\xff" + "a;b".encode("utf-16-be"))[:8])
    assert not formats.looks_like("txt", b"MZ\x90\x00\x03")


def test_a_tsv_file_is_read_by_cell_range(tmp_path):
    reading = read(write(tmp_path, "prices.tsv", "Item\tAmount, EUR\nchair\t100\n\ntable\t200\n"), "tsv", LIMIT)
    assert texts(reading) == [([], "| Item | Amount, EUR |\n| chair | 100 |\n| table | 200 |", "A1:B4")]


def test_json_is_read_value_by_value_each_at_its_json_pointer(tmp_path):
    data = ('{"deed": {"parties": [{"name": "Lotte Verbeke", "role": "seller"}, {"name": "Jan Peeters"}],'
            ' "price": 300000, "signed": true, "notary": null, "a/b~c": "escaped", "none": {}, "text": "two\\n lines"}}')
    reading = read(write(tmp_path, "deed.json", data), "json", LIMIT)
    assert texts(reading) == [([], "\n".join([
        "/deed/parties/0/name: Lotte Verbeke", "/deed/parties/0/role: seller", "/deed/parties/1/name: Jan Peeters",
        "/deed/price: 300000", "/deed/signed: true", "/deed/notary: null", "/deed/a~1b~0c: escaped", "/deed/text: two lines"]), "/deed")]
    rows = read(write(tmp_path, "rows.json", "[" + ",".join(f'{{"n": {i}, "item": "item {i}"}}' for i in range(200)) + "]"), "json", 300)
    assert len(rows.passages) > 1 and all(len(p.text) <= 300 for p in rows.passages)
    assert rows.passages[0].place is None and rows.passages[0].text.startswith("/0/n: 0\n/0/item: item 0")
    assert read(write(tmp_path, "one.json", '"just text"'), "json", LIMIT).passages == [Passage("just text", [], None)]


def test_json_too_deep_or_broken_is_refused_with_a_reason(tmp_path):
    for name, data in [("broken.json", '{"a": '), ("deeper.json", "[" * 100_000 + "]" * 100_000)]:
        with pytest.raises(Unreadable) as e:
            read(write(tmp_path, name, data), "json", LIMIT)
        assert e.value.code == "document.damaged", name


def test_xml_is_read_by_element_each_at_its_xpath(tmp_path):
    data = ('<?xml version="1.0" encoding="UTF-8"?><deed xmlns="urn:example:deed" id="7"><party><name>Lotte Verbeke</name></party>'
            '<party role="buyer"><name>Jan Peeters</name></party><clause>The price is <b>€ 300 000</b>, paid at signing.</clause></deed>')
    reading = read(write(tmp_path, "deed.xml", data), "xml", LIMIT)
    assert texts(reading) == [([], "\n".join([
        "/deed/@id: 7", "/deed/party[1]/name: Lotte Verbeke", "/deed/party[2]/@role: buyer", "/deed/party[2]/name: Jan Peeters",
        "/deed/clause: The price is € 300 000, paid at signing."]), "/deed")]  # prose with markup: as it reads


@pytest.mark.parametrize("data, code", [
    ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]><x>&b;</x>', "document.unreadable"),
    ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>', "document.unreadable"),
    ("<deed><unclosed></deed>", "document.damaged"),
])
def test_xml_with_entities_or_outside_files_is_never_expanded(tmp_path, data, code):
    with pytest.raises(Unreadable) as e:
        read(write(tmp_path, "x.xml", data), "xml", LIMIT)
    assert e.value.code == code


def test_html_is_read_by_section_without_its_scripts_and_styles(tmp_path):
    page = ('<!DOCTYPE html><html><head><meta charset="windows-1252"><title>Deed</title><style>p {color: red}</style>'
            '<script>document.write("hidden")</script></head><body><!-- a comment --><h1>Article 1</h1>'
            '<p>The price is <b>€ 300 000</b>.</p><p>Paid at<br>signing.</p><h2>Parties</h2>'
            '<table><tr><th>Name</th><th>Role</th></tr><tr><td>Lotte <i>Verbeke</i></td><td>seller</td></tr></table>'
            '<pre>Line 1\n    Line 2</pre><h1>Article 2</h1><h1>Article 3</h1><ul><li>One</li><li>Two</li></ul>'
            '</body></html>')
    reading = read(write(tmp_path, "deed.html", page.encode("cp1252")), "html", LIMIT)
    assert texts(reading) == [
        (["Article 1"], "The price is € 300 000.\n\nPaid at\nsigning.", None),
        (["Article 1", "Parties"], "| Name | Role |\n| Lotte Verbeke | seller |", None),
        (["Article 1", "Parties"], "Line 1\nLine 2", None),
        ([], "Article 2", None),  # a heading with nothing under it is text
        (["Article 3"], "One\n\nTwo", None)]
    assert reading.furniture == ["Deed", "a comment"]
    assert "hidden" not in str(reading) and "color" not in str(reading)


def test_html_says_its_encoding_or_is_read_as_any_text_file():
    assert formats.decode_html('<meta charset="iso-8859-1"><p>€</p>'.encode("cp1252")).endswith("<p>€</p>")
    assert formats.decode_html('<meta http-equiv="Content-Type" content="text/html; charset=utf-8"><p>é</p>'.encode()).endswith("é</p>")
    assert formats.decode_html("<p>é</p>".encode("cp1252")) == "<p>é</p>"  # no meta tag, not UTF-8
    assert formats.decode_html('<meta charset="nonsense"><p>é</p>'.encode()).endswith("é</p>")


def email_bytes(html: bool = False) -> bytes:
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"], m["To"], m["Cc"] = "Lotte Verbeke <lotte@firm.example>", "jan@firm.example", "an@firm.example"
    m["Subject"], m["Date"] = "Deed draft", "Wed, 25 Nov 2026 10:00:00 +0100"
    if html:
        m.set_content("<h1>Draft</h1><p>Dear Jan, the <b>draft</b>.</p><script>x()</script>", subtype="html")
    else:
        m.set_content("Dear Jan,\n\nThe draft is attached.\n\nLotte")
        m.add_alternative("<p>Dear Jan, HTML version</p>", subtype="html")
    m.add_attachment(b"%PDF-1.7", maintype="application", subtype="pdf", filename="deed.pdf")
    return bytes(m)


def test_an_email_is_read_with_who_when_and_what_under_its_subject(tmp_path):
    reading = read(write(tmp_path, "m.eml", email_bytes()), "eml", LIMIT)
    assert texts(reading) == [(["Deed draft"], "\n".join([
        "From: Lotte Verbeke <lotte@firm.example>", "To: jan@firm.example", "Cc: an@firm.example",
        "Date: Wed, 25 Nov 2026 10:00:00 +0100", "Subject: Deed draft"]) +
        "\n\nDear Jan,\n\nThe draft is attached.\n\nLotte", None)]  # the plain text, not the HTML alternative
    html = read(write(tmp_path, "h.eml", email_bytes(html=True)), "eml", LIMIT)
    assert [(p.headings, p.text.splitlines()[-1]) for p in html.passages] == [
        (["Deed draft"], "Subject: Deed draft"), (["Deed draft", "Draft"], "Dear Jan, the draft.")]


def test_every_part_of_an_email_is_read_or_listed_but_the_bodys_other_renderings(tmp_path):
    """Nothing left out unsaid (suveryn-tracker#267's review): a second text part shown inline (a list's footer),
    a picture in the HTML, a PDF sent inline, a part with no name are all read or listed."""
    from email.message import EmailMessage
    m = EmailMessage()
    m["Subject"] = "Deed"
    m.make_mixed()
    body = EmailMessage()
    body.set_content("The body.")
    body.add_alternative("<p>The body, in HTML.</p><img src='cid:logo'>", subtype="html")
    body.get_payload()[1].add_related(b"png", maintype="image", subtype="png", cid="<logo>")
    m.attach(body)
    footer = EmailMessage()
    footer.set_content("The list's footer.", disposition="inline")
    m.attach(footer)
    inline = EmailMessage()
    inline.set_content(b"%PDF-1.7", maintype="application", subtype="pdf", disposition="inline", filename="akte.pdf")
    inline["Content-ID"] = "<pdf>"
    m.attach(inline)
    unnamed = EmailMessage()
    unnamed.set_content(b"%PDF-1.7", maintype="application", subtype="pdf")
    m.attach(unnamed)
    parts = formats.email_parts(m)
    assert [p.get_content() for p in parts.texts] == ["The body.\n", "The list's footer.\n"]
    # the picture in the HTML rendering isn't text: listed, though the plain text is the body read
    assert [n for n, _ in parts.attachments] == ["attachment-1.png", "akte.pdf", "attachment-3.pdf"]
    reading = read(write(tmp_path, "m.eml", bytes(m)), "eml", LIMIT)
    assert reading.passages[0].text.endswith("The body.\n\nThe list's footer.")
    html_body = EmailMessage()
    html_body.set_content("<p>Only HTML</p><img src='cid:logo'>", subtype="html")
    html_body.add_related(b"png", maintype="image", subtype="png", cid="<logo>")
    assert [n for n, _ in formats.email_parts(html_body).attachments] == ["attachment-1.png"]  # shown in the body read
    cal = EmailMessage()
    cal.set_content("x")
    cal.add_attachment(b"BEGIN:VCALENDAR", maintype="text", subtype="calendar", disposition="attachment")
    assert [n for n, _ in formats.email_parts(cal).attachments] == ["attachment-1.ics"]


def test_a_plain_email_of_one_part_is_read(tmp_path):
    data = b"From: lotte@firm.example\nTo: jan@firm.example\nSubject: Deed\n\nThe deed is ready.\n"
    parts = formats.email_parts(formats.parse_email(data))
    assert len(parts.texts) == 1 and parts.attachments == []
    assert texts(read(write(tmp_path, "m.eml", data), "eml", LIMIT)) == [
        (["Deed"], "From: lotte@firm.example\nTo: jan@firm.example\nSubject: Deed\n\nThe deed is ready.", None)]


def test_a_file_in_the_html_rendering_is_listed_when_the_plain_text_is_read():
    """As Apple Mail sends HTML mail with a file placed in its text: alternative{plain, mixed{html, pdf, html}}."""
    from email.message import EmailMessage
    m = EmailMessage()
    m.make_alternative()
    plain, mixed = EmailMessage(), EmailMessage()
    plain.set_content("The text.")
    mixed.make_mixed()
    for part in ("<p>Before</p>", None, "<p>After</p>"):
        p = EmailMessage()
        if part is None:
            p.set_content(b"%PDF-1.7", maintype="application", subtype="pdf", filename="akte.pdf", disposition="inline")
        else:
            p.set_content(part, subtype="html")
        mixed.attach(p)
    m.attach(plain)
    m.attach(mixed)
    parts = formats.email_parts(m)
    assert [p.get_content() for p in parts.texts] == ["The text.\n"] and [n for n, _ in parts.attachments] == ["akte.pdf"]
    invitation = EmailMessage()  # as Outlook sends one: alternative{plain, html, calendar}
    invitation.set_content("Meeting.")
    invitation.add_alternative("<p>Meeting.</p>", subtype="html")
    invitation.add_alternative("BEGIN:VCALENDAR", subtype="calendar")
    assert [n for n, _ in formats.email_parts(invitation).attachments] == ["attachment-1.ics"]


def test_an_email_with_more_parts_than_any_real_one_is_refused_before_parsing(monkeypatch):
    monkeypatch.setattr(formats, "MAX_EMAIL_PARTS", 3)
    # parts with no Content-Type (plain text, by MIME's default) count as well: by their boundary lines
    data = b"Content-Type: multipart/mixed; boundary=b\n\n" + b"".join(b"--b\nContent-Disposition: inline\n\nx\n" for _ in range(5))
    with pytest.raises(Unreadable) as e:
        formats.parse_email(data)
    assert e.value.code == "document.too_large"


def test_an_email_with_a_header_that_cant_be_parsed_is_still_read(tmp_path):
    data = b"From: " + b"(" * 5000 + b"\nSubject: Deed\n\nThe deed is ready.\n"
    reading = read(write(tmp_path, "m.eml", data), "eml", LIMIT)
    text = "\n".join(p.text for p in reading.passages)  # the long header is cut into passages
    assert text.startswith("From: (((") and "Subject: Deed" in text and text.endswith("The deed is ready.")


def test_an_email_nested_past_any_mail_program_is_refused_with_a_reason(tmp_path):
    deep = b"Content-Type: multipart/mixed; boundary=b0\n\n" + b"".join(
        f"--b{i}\nContent-Type: multipart/mixed; boundary=b{i + 1}\n\n".encode() for i in range(1000))
    for data in (deep, b"Content-Disposition: attachment; filename=" + b"(" * 5000 + b"\n\nx"):
        with pytest.raises(Unreadable) as e:
            formats.email_parts(formats.parse_email(data))
        assert e.value.code == "document.damaged"


def test_html_that_leaves_out_its_end_tags_is_read_as_browsers_read_it(tmp_path):
    page = "<html><head><title>T</title><meta charset=utf-8><body><p>Body text one.</p><object><p>Fallback</p>"
    reading = read(write(tmp_path, "p.html", page), "html", LIMIT)
    assert texts(reading) == [([], "Body text one.\n\nFallback", None)] and reading.furniture == ["T"]
    reading = read(write(tmp_path, "q.html", "<title>Only a title"), "html", LIMIT)
    assert texts(reading) == [([], "Only a title", None)]  # a title never closed: the rest is the page
    reading = read(write(tmp_path, "r.html", "<head><title>T</title><meta charset=utf-8>Loose text<br>more"), "html", LIMIT)
    assert texts(reading) == [([], "Loose text\nmore", None)]  # text in the head: the body has begun


def test_json_or_xml_nested_too_deep_is_refused(tmp_path):
    for name, kind, data in [("deep.json", "json", "[" * 150 + "]" * 150), ("deep.xml", "xml", "<a>" * 150 + "</a>" * 150)]:
        with pytest.raises(Unreadable) as e:
            read(write(tmp_path, name, data), kind, LIMIT)
        assert e.value.code == "document.too_large", name


def test_a_kept_text_file_is_served_in_the_character_set_it_was_read_in():
    assert formats.content_type("é".encode(), "txt") == "text/plain; charset=utf-8"
    assert formats.content_type("é".encode("cp1252"), "csv") == "text/plain; charset=windows-1252"
    assert formats.content_type("é".encode("utf-16"), "txt") == "text/plain; charset=utf-16"
    assert formats.content_type('<meta charset="iso-8859-15"><p>€</p>'.encode("iso-8859-15"), "html") == "text/plain; charset=iso8859-15"
    assert formats.content_type(b"%PDF", "pdf") == "application/pdf" and formats.content_type(b"x", "eml") == "message/rfc822"


def test_json_and_xml_with_too_many_values_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(formats, "MAX_CELLS", 10)
    for name, kind, data in [("many.json", "json", "[" + ",".join(["1"] * 20) + "]"),
                             ("many.xml", "xml", "<r>" + "<v>1</v>" * 20 + "</r>")]:
        with pytest.raises(Unreadable) as e:
            read(write(tmp_path, name, data), kind, LIMIT)
        assert e.value.code == "document.too_large", name


# ---------------------------------------------------------------------- OpenDocument and PowerPoint (suveryn-tracker#271)
# fixtures/deed.odt, prices.ods and deck.odp are LibreOffice 24.2's own conversions of a fictional Word file, workbook
# and deck (python-docx, openpyxl, python-pptx); fixtures/deck.pptx is that deck.
def test_an_opendocument_text_is_read_by_section_as_word_is():
    reading = read(FIXTURES / "deed.odt", "odt", LIMIT)
    assert texts(reading) == [
        (["Article 1"], "The price is EUR 300 000.", None),
        (["Article 1", "Parties"], "| Name | Role |\n| Lotte Verbeke | seller |", None),
        (["Article 2"], "Signed at the office.", None)]
    assert reading.furniture == ["Footer: Office Testdorp"]  # a footer: checked for the mark, not stored


def test_an_opendocument_spreadsheet_is_read_as_the_same_workbook_in_excel(tmp_path):
    import openpyxl as xl
    wb = xl.Workbook()
    ws = wb.active
    ws.title = "Prices"
    for row in (["Item", "Amount", "Date", "Paid"], ["chair", 100.5, datetime(2026, 10, 19), True],  # noqa: DTZ001
                ["table", 200, datetime(2026, 11, 1), False]):  # noqa: DTZ001
        ws.append(row)
    ws["A10"] = "far"
    wb.create_sheet("Price list")["B2"] = "x"
    wb.save(tmp_path / "prices.xlsx")
    assert texts(read(FIXTURES / "prices.ods", "ods", LIMIT)) == texts(read(tmp_path / "prices.xlsx", "xlsx", LIMIT)) == [
        ([], "| Item | Amount | Date | Paid |\n| chair | 100.5 | 2026-10-19 | TRUE |\n| table | 200 | 2026-11-01 | FALSE |\n| far |",
         "Prices!A1:D10"),
        ([], "|  | x |", "'Price list'!A2:B2")]


@pytest.mark.parametrize("name, kind", [("deck.pptx", "pptx"), ("deck.odp", "odp")])
def test_a_deck_is_read_slide_by_slide_each_numbered_as_a_page(name, kind):
    reading = read(FIXTURES / name, kind, LIMIT)
    assert reading.pages == 3  # the third slide is empty: counted, nothing to read on it
    assert [(p.headings, p.text, p.page) for p in reading.passages] == [
        (["Deed intake"], "First point\nSecond point\n\nSay this aloud.", 1),  # the speaker notes after the slide's text
        (["Parties"], "In a group", 2),  # text in a group of shapes
        (["Parties"], "| Name | Role |\n| Lotte | seller |", 2)]


def odf(tmp_path: Path, kind: str, content: str, mimetype: str | None = None, manifest: str = "") -> Path:
    path = tmp_path / f"x.{kind}"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", mimetype or formats.ODF_TYPES[kind])
        z.writestr("content.xml", content)
        if manifest:
            z.writestr("META-INF/manifest.xml", manifest)
    return path


NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')


def test_an_opendocument_texts_spaces_notes_comments_and_deletions_are_read_as_it_reads(tmp_path):
    content = (f'<office:document-content {NS}><office:body><office:text>'
               '<text:tracked-changes><text:changed-region><text:deletion><text:p>deleted words</text:p></text:deletion>'
               '</text:changed-region></text:tracked-changes>'
               '<text:h text:outline-level="2">Price</text:h>'
               '<text:p>EUR<text:s text:c="2"/>300<text:tab/>000<text:note><text:note-citation>1</text:note-citation>'
               '<text:note-body><text:p>Before costs.</text:p></text:note-body></text:note>.'
               '<office:annotation><text:p>Check this</text:p></office:annotation></text:p>'
               '<text:list><text:list-item><text:p>One</text:p></text:list-item><text:list-item><text:p>Two</text:p></text:list-item></text:list>'
               '</office:text></office:body></office:document-content>')
    reading = read(odf(tmp_path, "odt", content), "odt", LIMIT)
    assert texts(reading) == [(["Price"], "EUR  300\t000.\n\nBefore costs.\n\nOne\n\nTwo", None)]
    assert reading.furniture == ["Check this"]


def test_a_spreadsheets_million_empty_rows_and_repeated_cells_are_counted_not_written_out(tmp_path, monkeypatch):
    rows = ('<table:table-row table:number-rows-repeated="1048570"><table:table-cell table:number-columns-repeated="1024"/></table:table-row>'
            '<table:table-row><table:table-cell table:number-columns-repeated="3"/><table:table-cell office:value-type="float" '
            'office:value="2.0"><text:p>2,00</text:p></table:table-cell><table:table-cell table:number-columns-repeated="16000"/></table:table-row>')
    content = f'<office:document-content {NS}><office:body><office:spreadsheet><table:table table:name="S">{rows}</table:table></office:spreadsheet></office:body></office:document-content>'
    assert texts(read(odf(tmp_path, "ods", content), "ods", LIMIT)) == [([], "|  |  |  | 2 |", "S!A1048571:D1048571")]
    monkeypatch.setattr(formats, "MAX_CELLS", 10)
    many = (f'<office:document-content {NS}><office:body><office:spreadsheet><table:table table:name="S">'
            '<table:table-row table:number-rows-repeated="1000000"><table:table-cell table:number-columns-repeated="16384" '
            'office:value-type="string"><text:p>x</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet>'
            '</office:body></office:document-content>')  # a few hundred bytes for 16 billion cells
    with pytest.raises(Unreadable) as e:
        read(odf(tmp_path, "ods", many), "ods", LIMIT)
    assert e.value.code == "document.too_large"
    wide = content.replace('table:number-columns-repeated="16000"', 'table:number-columns-repeated="999999999"')
    assert texts(read(odf(tmp_path, "ods", wide), "ods", LIMIT))[0][2] == "S!A1048571:D1048571"  # an empty run costs nothing


@pytest.mark.parametrize("mimetype, manifest, code", [
    ("application/vnd.oasis.opendocument.spreadsheet", "", "document.damaged"),  # an .ods named .odt
    (None, '<manifest:manifest><manifest:file-entry><manifest:encryption-data/></manifest:file-entry></manifest:manifest>',
     "document.password_protected"),
])
def test_an_opendocument_that_isnt_what_it_says_or_is_encrypted_is_refused(tmp_path, mimetype, manifest, code):
    with pytest.raises(Unreadable) as e:
        read(odf(tmp_path, "odt", f"<office:document-content {NS}/>", mimetype, manifest), "odt", LIMIT)
    assert e.value.code == code


def test_opendocument_xml_with_entities_is_never_expanded(tmp_path):
    content = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    with pytest.raises(Unreadable) as e:
        read(odf(tmp_path, "odt", content), "odt", LIMIT)
    assert e.value.code == "document.unreadable"


def test_tables_across_an_opendocument_text_share_one_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(formats, "MAX_CELLS", 100)
    table = '<table:table><table:table-row table:number-rows-repeated="60"><table:table-cell><text:p>x</text:p></table:table-cell></table:table-row></table:table>'
    content = f'<office:document-content {NS}><office:body><office:text>{table * 2}</office:text></office:body></office:document-content>'
    with pytest.raises(Unreadable) as e:  # 60 cells each, 120 together
        read(odf(tmp_path, "odt", content), "odt", LIMIT)
    assert e.value.code == "document.too_large"


DRAW = 'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'


def test_text_boxes_inside_text_boxes_are_read_once_and_quickly(tmp_path):
    """suveryn-tracker#271's review: 24 nested boxes in 591 bytes took 84 s and 4 GB, the innermost read 2^23 times."""
    inner = "<text:p>Innermost.</text:p>"
    for _ in range(24):
        inner = f"<text:p>Box<draw:frame><draw:text-box>{inner}</draw:text-box></draw:frame></text:p>"
    content = f'<office:document-content {NS} {DRAW}><office:body><office:text>{inner}</office:text></office:body></office:document-content>'
    reading = read(odf(tmp_path, "odt", content), "odt", LIMIT)
    text = "\n".join(p.text for p in reading.passages)
    assert text.count("Innermost.") == 1 and text.count("Box") == 24


def test_a_drawing_anchored_in_a_paragraph_is_read_after_it(tmp_path):
    content = (f'<office:document-content {NS} {DRAW}><office:body><office:text><text:p>The plan.<draw:custom-shape>'
               '<text:p>Fictional price EUR 123.456</text:p></draw:custom-shape></text:p></office:text></office:body></office:document-content>')
    assert texts(read(odf(tmp_path, "odt", content), "odt", LIMIT)) == [([], "The plan.\n\nFictional price EUR 123.456", None)]


def test_a_merged_cell_keeps_the_columns_where_they_are(tmp_path):
    """As LibreOffice writes a merged A1:B1: the cell it covers stays a column."""
    rows = ('<table:table-row><table:table-cell table:number-columns-spanned="2"><text:p>Item and kind</text:p></table:table-cell>'
            '<table:covered-table-cell/><table:table-cell><text:p>Amount</text:p></table:table-cell></table:table-row>'
            '<table:table-row><table:table-cell><text:p>Total</text:p></table:table-cell><table:table-cell/>'
            '<table:table-cell office:value-type="float" office:value="350"><text:p>350</text:p></table:table-cell></table:table-row>')
    for kind, body in [("ods", "spreadsheet"), ("odt", "text")]:
        content = f'<office:document-content {NS}><office:body><office:{body}><table:table table:name="S">{rows}</table:table></office:{body}></office:body></office:document-content>'
        reading = read(odf(tmp_path, kind, content), kind, LIMIT)
        assert reading.passages[0].text == "| Item and kind |  | Amount |\n| Total |  | 350 |", kind


def test_comments_on_cells_and_slides_are_furniture_not_text(tmp_path):
    cell = ('<table:table-cell><text:p>Price</text:p><office:annotation><text:p>Check with Jan</text:p></office:annotation></table:table-cell>'
            '<table:table-cell><office:annotation><text:p>Only a comment</text:p></office:annotation></table:table-cell>')
    content = f'<office:document-content {NS}><office:body><office:spreadsheet><table:table table:name="S"><table:table-row>{cell}</table:table-row></table:table></office:spreadsheet></office:body></office:document-content>'
    reading = read(odf(tmp_path, "ods", content), "ods", LIMIT)
    assert texts(reading) == [([], "| Price |", "S!A1:A1")] and reading.furniture == ["Check with Jan", "Only a comment"]
    slide = (f'<office:document-content {NS} {DRAW} xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
             'xmlns:officeooo="http://openoffice.org/2009/office"><office:body><office:presentation><draw:page>'
             '<draw:frame presentation:class="outline"><draw:text-box><text:p>Point</text:p></draw:text-box></draw:frame>'
             '<officeooo:annotation><text:p>A reviewer\'s remark</text:p></officeooo:annotation></draw:page>'
             '</office:presentation></office:body></office:document-content>')
    reading = read(odf(tmp_path, "odp", slide), "odp", LIMIT)
    assert [(p.text, p.page) for p in reading.passages] == [("Point", 1)] and reading.furniture == ["A reviewer's remark"]


def test_odd_numbers_in_an_opendocument_are_read_past_not_refused(tmp_path):
    content = (f'<office:document-content {NS}><office:body><office:text><text:h text:outline-level="one">Price</text:h>'
               '<text:p>A<text:s text:c="two"/>B</text:p></office:text></office:body></office:document-content>')
    assert texts(read(odf(tmp_path, "odt", content), "odt", LIMIT)) == [(["Price"], "A B", None)]


def test_an_opendocument_title_is_the_heading_above_the_rest(tmp_path):
    content = (f'<office:document-content {NS} xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"><office:automatic-styles>'
               '<style:style style:name="P1" style:parent-style-name="Title"/></office:automatic-styles><office:body><office:text>'
               '<text:p text:style-name="P1">Deed of sale</text:p><text:h text:outline-level="1">Price</text:h><text:p>EUR 300.</text:p>'
               '</office:text></office:body></office:document-content>')
    assert texts(read(odf(tmp_path, "odt", content), "odt", LIMIT)) == [(["Deed of sale", "Price"], "EUR 300.", None)]


@pytest.mark.parametrize("kind", ["docx", "xlsx", "pptx"])
def test_an_office_file_protected_with_a_password_is_refused_as_such(tmp_path, kind):
    """fixtures/protected.docx: a fictional note encrypted by msoffcrypto-tool (MS-OFFCRYPTO, as Office does);
    fixtures/old.doc: LibreOffice's .doc of it, unencrypted. Both are compound files, not zips."""
    protected, old = (FIXTURES / "protected.docx").read_bytes(), (FIXTURES / "old.doc").read_bytes()
    assert formats.looks_like(kind, protected[:8])
    for data, code in [(protected, "document.password_protected"), (old, "document.damaged")]:  # a .doc renamed
        with pytest.raises(Unreadable) as e:
            read(write(tmp_path, f"x.{kind}", data), kind, LIMIT)
        assert e.value.code == code


def test_a_table_in_a_cell_and_a_footnote_in_a_cell_are_read_with_the_cell(tmp_path):
    inner = '<table:table><table:table-row><table:table-cell><text:p>Inner value</text:p></table:table-cell></table:table-row></table:table>'
    cell = (f'<table:table-cell><text:p>Outer</text:p>{inner}</table:table-cell>'
            '<table:table-cell><text:p>Price<text:note><text:note-body><text:p>Before costs.</text:p></text:note-body></text:note></text:p></table:table-cell>')
    content = (f'<office:document-content {NS}><office:body><office:text><table:table><table:table-row>{cell}</table:table-row>'
               '</table:table></office:text></office:body></office:document-content>')
    assert texts(read(odf(tmp_path, "odt", content), "odt", LIMIT)) == [([], "| Outer Inner value | Price Before costs. |", None)]


def test_a_decks_slides_are_stored_as_its_chunks_pages():
    pytest.importorskip("psycopg")
    from suveryn_rag.extract import Extraction
    from suveryn_rag.pipeline import Rag
    from suveryn_rag.store import Original

    class Store:
        def add_document(self, name, digest, pages, ocr_pages, chunks, vectors, warnings, owner, case_id, **kw):
            self.stored = (pages, [(c.page_start, c.page_end, c.headings) for c in chunks])
            return "doc"

        def document_status(self, doc_id):
            return "ok", []

    rag = Rag.__new__(Rag)
    rag.store = Store()
    rag._embed_passages = lambda chunks, timings, t: [[0.0]] * len(chunks)
    reading = read(FIXTURES / "deck.pptx", "pptx", LIMIT)
    ex = Extraction(document=None, pages=reading.pages, ocr_pages=0, mixed_pages=0, passages=reading.passages, furniture=[])
    result = rag._store_passages(ex, None, "deck.pptx", "digest", "user-a", None, Original("x", b""))
    assert result.pages == 3
    assert rag.store.stored == (3, [(1, 1, ["Deed intake"]), (2, 2, ["Parties"]), (2, 2, ["Parties"])])


@pytest.mark.parametrize("name, kind", [("deck-footer.pptx", "pptx"), ("deck-footer.odp", "odp")])
def test_a_slides_footer_and_date_are_furniture(name, kind):
    """fixtures/deck-footer.pptx: python-pptx, a slide with its layout's footer and date; .odp: LibreOffice's of it,
    which declares the footer once for the deck (presentation:footer-decl)."""
    reading = read(FIXTURES / name, kind, LIMIT)
    assert [(p.text, p.page) for p in reading.passages] == [("Point", 1)]
    assert {"Office Testdorp, confidential", "25 November 2026"} <= set(reading.furniture)


@pytest.mark.parametrize("name, kind", [("prices.ods", "ods"), ("deck.odp", "odp"), ("deed.odt", "odt"), ("deck.pptx", "pptx")])
def test_a_damaged_package_is_refused_as_damaged_not_as_a_crash(tmp_path, name, kind):
    data = bytearray((FIXTURES / name).read_bytes())
    with zipfile.ZipFile(FIXTURES / name) as z:  # the compressed bytes of the main part, garbled
        info = z.getinfo({"ods": "content.xml", "odp": "content.xml", "odt": "content.xml", "pptx": "ppt/slides/slide1.xml"}[kind])
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data[start + 10:start + 40] = b"\xff" * 30
    with pytest.raises(Unreadable) as e:
        read(write(tmp_path, name, bytes(data)), kind, LIMIT)
    assert e.value.code == "document.damaged"


@pytest.mark.parametrize("member", ["mimetype", "META-INF/manifest.xml"])
def test_an_opendocument_with_a_damaged_small_part_is_damaged_too(tmp_path, member):
    data = bytearray((FIXTURES / "deed.odt").read_bytes())
    with zipfile.ZipFile(FIXTURES / "deed.odt") as z:
        info = z.getinfo(member)
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data[start:start + min(info.compress_size, 8)] = b"\xff" * min(info.compress_size, 8)
    with pytest.raises(Unreadable) as e:
        read(write(tmp_path, "x.odt", bytes(data)), "odt", LIMIT)
    assert e.value.code == "document.damaged"


def test_a_deck_that_lists_a_slide_it_doesnt_hold_is_damaged(tmp_path):
    path = tmp_path / "x.pptx"
    with zipfile.ZipFile(FIXTURES / "deck.pptx") as src, zipfile.ZipFile(path, "w") as out:
        for info in src.infolist():
            if info.filename != "ppt/slides/slide1.xml":
                out.writestr(info, src.read(info))
    with pytest.raises(Unreadable) as e:
        read(path, "pptx", LIMIT)
    assert e.value.code == "document.damaged"
