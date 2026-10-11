"""A stand-in for the PDF reader process (suveryn_rag.isolation), for test_isolation.py.

Runs the real reader loop (``serve``) with a fake extraction. The file name asks for a behaviour:
crash, hang, garbage, env (report the names of PATH and SUVERYN_* variables), anything else: a one-page document.
"""

import os
import sys
import time
from pathlib import Path

from docling_core.types.doc import DoclingDocument
from suveryn_rag.extract import Extraction
from suveryn_rag.isolation import protocol_streams, serve


def fake_extract(pdf: Path) -> Extraction:
    print("noise a library printed to stdout")  # must not corrupt the answers
    if pdf.stem == "crash":
        os._exit(139)  # like a segfault in a native parser
    if pdf.stem == "hang":
        time.sleep(60)
    if pdf.stem == "garbage":
        answers.write(b"\x80\x81 not json\n")
        answers.flush()
        return None
    if pdf.stem == "env":
        raise RuntimeError(" ".join(sorted(k for k in os.environ if k.startswith("SUVERYN_") or k == "PATH")))
    if pdf.stem == "fails":
        raise ValueError("no pages")
    doc = DoclingDocument(name=pdf.stem)
    doc.add_text(label="text", text="Een akte.")
    return Extraction(document=doc, pages=1, ocr_pages=0, mixed_pages=0, page_texts=["Een akte."],
                      timings={"layout": 0.1})


if __name__ == "__main__":
    requests, answers = protocol_streams()
    if len(sys.argv) > 1 and sys.argv[1] == "broken":
        answers.write(b'{"ready": false, "error": "ModuleNotFoundError: docling"}\n')
        answers.flush()
        raise SystemExit(1)
    serve(fake_extract, requests, answers)
