"""Uploads read directly (suveryn_rag.formats): Word, Excel, Markdown, CSV and TSV, text, JSON, XML, HTML and an
email's message: passages with their section, cells or path, nothing left out, and sūveryn's export mark found
wherever the export puts it. Fictional documents only."""
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
    assert [kind_of(n) for n in ("a.doc", "b.xls", "c.xlsm", "d.rtf", "noextension")] == [None] * 5


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
