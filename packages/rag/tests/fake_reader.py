"""A stand-in for the document reader process (suveryn_rag.isolation), for test_isolation.py.

Runs the real reader loop (``serve``) with a fake extraction. The file name asks for a behaviour:
crash, hang, garbage, hostile (a forged crash report), env (report the names of PATH and SUVERYN_* variables), a spreadsheet's passages
(prices.xlsx), a deck's slides (deck.pptx), malformed passages (bad.xlsx, bad.pptx), progress (three OCR pages reported, then the document),
slow (reports a page, then takes a minute), locked (a protected PDF), anything else: a one-page document.
"""

import os
import sys
import time
from pathlib import Path

from docling_core.types.doc import DoclingDocument
from suveryn_rag.extract import Extraction
from suveryn_rag.formats import Passage
from suveryn_rag.isolation import protocol_streams, serve
from suveryn_rag.reading import Progress, Unreadable, Watch


def fake_extract(pdf: Path, watch: Watch | None = None) -> Extraction:
    watch = watch or Watch()
    print("noise a library printed to stdout")  # must not corrupt the answers
    if pdf.stem == "crash":
        os._exit(139)  # like a segfault in a native parser
    if pdf.stem == "hang":
        time.sleep(60)
    if pdf.stem == "hostile":  # a reader a document took over: a crash report that would forge a log line and quote it
        import json
        answers.write(json.dumps({"ok": False, "crashed": "ValueError\nINFO forged line",
                                  "where": "Purchase price 385,000 euro, plot 123"}).encode() + b"\n")
        answers.flush()
        return None
    if pdf.stem == "garbage":
        answers.write(b"\x80\x81 not json\n")
        answers.flush()
        return None
    if pdf.stem == "env":
        # what the reader's environment holds, as a reason the reader gives (an exception's message never comes through)
        raise Unreadable(" ".join(sorted(k for k in os.environ if k.startswith("SUVERYN_") or k == "PATH")))
    if pdf.stem == "fails":
        raise ValueError("no pages")
    if pdf.stem == "locked":
        raise Unreadable("the PDF is protected with a password", "document.password_protected")
    if pdf.stem == "big":
        raise Unreadable("the document has 900 pages; at most 500 can be read", "document.pages_too_many", pages=900, max=500)
    if pdf.stem in ("progress", "slow"):
        for done in range(1, 4 if pdf.stem == "progress" else 2):
            watch.report(Progress("ocr", done, 3))
        watch.report(Progress("layout", None, 3))
        if pdf.stem == "slow":
            time.sleep(60)
    if pdf.name == "prices.xlsx":
        return Extraction(document=None, pages=0, ocr_pages=0, mixed_pages=0, timings={"read": 0.1},
                          passages=[Passage("| Item | Amount |\n| Price | 300000 |", [], "Prices!A1:B2")],
                          furniture=["a footer"])
    if pdf.name == "deck.pptx":
        return Extraction(document=None, pages=2, ocr_pages=0, mixed_pages=0,
                          passages=[Passage("First point", ["Intake"], None, 1), Passage("Second", [], None, 2)])
    if pdf.name == "bad.pptx":
        return Extraction(document=None, pages=1, ocr_pages=0, mixed_pages=0,
                          passages=[Passage("text", [], None, 0)])  # a slide is numbered from 1
    if pdf.name == "bad.xlsx":
        return Extraction(document=None, pages=0, ocr_pages=0, mixed_pages=0,
                          passages=[Passage("text", [7], None)])  # headings must be strings
    doc = DoclingDocument(name=pdf.stem)
    doc.add_text(label="text", text="A deed.")
    return Extraction(document=doc, pages=1, ocr_pages=0, mixed_pages=0, page_texts=["A deed."],
                      timings={"layout": 0.1})


if __name__ == "__main__":
    requests, answers = protocol_streams()
    if len(sys.argv) > 1 and sys.argv[1] == "broken":
        answers.write(b'{"ready": false, "error": "ModuleNotFoundError: docling"}\n')
        answers.flush()
        raise SystemExit(1)
    serve(fake_extract, requests, answers)
