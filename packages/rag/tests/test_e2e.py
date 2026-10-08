"""End-to-end regression test with planted traps (see trap_deed.py). Runs on the GPU machine:
needs suveryn-rag installed (uv sync --all-packages), a database (SUVERYN_TEST_DATABASE_URL) and
Docling/bge-m3. The scanned variants also need poppler (pdf2image): a plain scan, and a scan whose
pages carry a short digital label ("thin" text layer) that must not stop OCR.

Quality bar:
- every page of a scan is OCR'd, also under a thin digital text layer;
- no text lost: the closing heading and the footer-area content line are stored;
- real furniture dropped: the running header and page numbers are not in any chunk;
- the cadastral reference comes through intact;
- every question finds the right passage in the top 5 with the correct page, and the
  buried tenant arrears in the top 3;
- no leftover files in the work directory;
- the document reaches status "ok", and forgetting it removes everything.
"""

import os
import re
import shutil

import pytest

pytest.importorskip("suveryn_rag")
pytest.importorskip("docling")
pytest.importorskip("reportlab")
URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")

from suveryn_rag.config import RagSettings  # noqa: E402
from suveryn_rag.extract import text_layer  # noqa: E402
from suveryn_rag.integrity import norm  # noqa: E402

import trap_deed  # noqa: E402


@pytest.fixture(scope="module")
def rag(tmp_path_factory):
    from dataclasses import replace

    from suveryn_rag.pipeline import Rag

    settings = replace(RagSettings.from_env(), database_url=URL, work_dir=tmp_path_factory.mktemp("work"))
    r = Rag(settings)
    yield r
    r.close()


def variants(tmp_path):
    born = trap_deed.build(tmp_path / "trap.pdf")
    out = [("born-digital", born)]
    if shutil.which("pdftoppm"):
        out.append(("scanned", trap_deed.scanned(born, tmp_path / "trap_scan.pdf")))
        out.append(("scanned-thin-text", trap_deed.scanned_with_label(born, tmp_path / "trap_thin.pdf")))
    return out


@pytest.mark.parametrize("kind", ["born-digital", "scanned", "scanned-thin-text"])
def test_trap_deed(rag, tmp_path, kind):
    found = dict(variants(tmp_path))
    if kind not in found:
        pytest.skip("pdftoppm not available for the scanned variants")
    pdf = found[kind]
    true_pages = text_layer(found["born-digital"])  # page truth from the generated text
    r = rag.ingest(pdf)
    try:
        # Every page of a scan must be OCR'd, also when a thin digital label sits on top of it.
        assert r.ocr_pages == (0 if kind == "born-digital" else r.pages), f"{kind}: {r.ocr_pages}/{r.pages} pages OCR'd"
        rows = rag.store._conn.execute(
            "SELECT text, page_start, page_end, headings, origin FROM chunks WHERE document_id = %s", (r.document_id,)
        ).fetchall()
        stored = norm(" ".join(t + " " + " ".join(h) for t, _, _, h, _ in rows))

        assert norm(trap_deed.CLOSING_HEADING) in stored, "closing heading lost"
        assert norm("recht van opstal ten gunste van Stroomnet Oost") in stored, "footer-area content lost"
        assert norm("Kenmerk TST/2026/0042") not in stored, "running header not dropped"
        assert not any(re.fullmatch(r"\s*pagina \d+\s*", norm(t)) for t, *_ in rows), "page number stored as a chunk"
        assert re.search(r"sectie k, nummer 4182", stored), "cadastral reference garbled"
        assert all(ps is not None for _, ps, *_ in rows), "chunk without page number"
        assert r.status == "ok", f"document flagged: {r.warnings}"
        assert not any(rag.settings.work_dir.rglob("*")), "files left in the work directory"

        for item in trap_deed.QUESTIONS:
            expect = norm(item["expect"])
            pages = [p for p, text in enumerate(true_pages, 1) if expect in norm(text)]
            hits = rag.retrieve(item["q"], k=5, document_id=r.document_id)
            rank = next((i for i, h in enumerate(hits, 1) if expect in norm(h.citation.text)), None)
            assert rank, f"{kind}: no passage with {item['expect']!r} in top 5 for {item['q']!r}"
            src = hits[rank - 1].citation.source
            assert src.page in pages, f"{kind}: {item['q']!r} cited page {src.page}, text is on {pages}"
            if item["expect"] == "48.200":
                assert rank <= 3, f"{kind}: buried tenant arrears only at rank {rank}"
    finally:
        assert rag.forget(r.document_id)
        assert rag.store.document_status(r.document_id) is None
