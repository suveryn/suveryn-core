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
