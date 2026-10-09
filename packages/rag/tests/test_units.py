"""Fast tests without GPU or database. Skipped where suveryn-rag isn't installed (uv sync --all-packages)."""

import os
import stat
import tempfile
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("suveryn_rag")
from suveryn_rag.chunking import chunk_pages, location_label  # noqa: E402
from suveryn_rag.workspace import private_workdir  # noqa: E402


def fake_chunk(*page_lists):
    return NS(meta=NS(doc_items=[NS(prov=[NS(page_no=p) for p in pages]) for pages in page_lists]))


def test_chunk_pages_spans_all_items():
    assert chunk_pages(fake_chunk([3], [3, 4], [5])) == (3, 5)


def test_chunk_pages_without_provenance():
    assert chunk_pages(NS(meta=NS(doc_items=[NS(prov=None)]))) == (None, None)


def test_location_label():
    assert location_label(3, 3, []) == "p. 3"
    assert location_label(3, 4, ["Artikel 2 — Koopprijs"]) == "p. 3-4 · Artikel 2 — Koopprijs"
    assert location_label(None, None, []) is None


def test_private_workdir_is_private_redirects_temp_and_is_removed(tmp_path):
    base = tmp_path / "work"
    before_env = os.environ.get("TMPDIR")
    with private_workdir(base) as d:
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
        assert os.environ["TMPDIR"] == str(d) and tempfile.gettempdir() == str(d)
        with tempfile.NamedTemporaryFile(delete=False) as f:  # e.g. what OCRmyPDF does
            f.write(b"searchable copy")
        assert f.name.startswith(str(d))
    assert not d.exists()
    assert os.environ.get("TMPDIR") == before_env
    assert stat.S_IMODE(base.stat().st_mode) == 0o700


def test_private_workdir_removed_on_error(tmp_path):
    with pytest.raises(RuntimeError), private_workdir(tmp_path / "w") as d:
        (d / "partial.pdf").write_bytes(b"x")
        raise RuntimeError("OCR failed")
    assert not d.exists()


def test_plan_ocr_scans_thin_and_mixed_pages():
    pytest.importorskip("pypdfium2")
    from suveryn_rag.extract import PageProfile, plan_ocr

    profiles = [PageProfile(chars=2400, image_share=0.02),  # born-digital with a logo: keep
                PageProfile(chars=0, image_share=1.0),       # plain scan: OCR
                PageProfile(chars=15, image_share=1.0),      # scan with a copier label: OCR
                PageProfile(chars=1800, image_share=0.18),   # digital text + pasted-in scan: OCR images
                PageProfile(chars=1900, image_share=0.0)]    # pure text: keep
    assert plan_ocr(profiles) == [2, 3, 4]
    assert [p.is_mixed for p in profiles] == [False, False, False, True, False]


def test_job_status_maps_document_status():
    from suveryn_rag.service import job_status

    assert job_status("ok") == "ready"
    assert job_status("needs_review") == "needs_review"
