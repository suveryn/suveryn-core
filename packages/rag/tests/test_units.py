"""Fast tests without GPU or database. Skipped where suveryn-rag isn't installed (uv sync --all-packages)."""

import os
import stat
import tempfile
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("suveryn_rag")
from suveryn_rag.chunking import chunk_pages, location_label
from suveryn_rag.workspace import private_workdir


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


def test_offline_by_default_and_only_fetch_may_download(monkeypatch):
    from suveryn_rag import offline

    for name in offline.OFFLINE:
        monkeypatch.setenv(name, "0")  # also makes monkeypatch restore them afterwards
    monkeypatch.delenv("SUVERYN_ALLOW_DOWNLOADS", raising=False)
    offline.enforce()
    assert all(os.environ[k] == v for k, v in offline.OFFLINE.items())  # overrides a contrary setting
    monkeypatch.setenv("SUVERYN_ALLOW_DOWNLOADS", "1")
    offline.enforce()
    assert "HF_HUB_OFFLINE" not in os.environ and os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


# ---------------------------------------------------------------- the layout model running out of GPU memory
# Seen on the pod, 2026-10-11: with a larger chat model loaded the GPU was full, Docling returned a
# "partial success" with 11 pages failed on "CUDA out of memory", and only the text-layer recovery kept
# the text (without structure, page headers included). The status is now checked, and retried on the CPU.

class _Item:
    def __init__(self, page, text="tekst"):
        self.text, self.prov = text, [type("P", (), {"page_no": page})()]


class _Doc:
    def __init__(self, pages):
        self.items = [_Item(p) for p in pages]

    def iterate_items(self, included_content_layers=None):
        return [(i, 0) for i in self.items]


class _Result:
    def __init__(self, status, pages, errors=()):
        self.status, self.document = status, _Doc(pages)
        self.errors = [type("E", (), {"error_message": e})() for e in errors]


class _Converter:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def convert(self, source, raises_on_error=True):
        assert raises_on_error is False  # a failed page must not raise: it's checked instead
        self.calls += 1
        return self.result


def test_a_gpu_out_of_memory_layout_is_read_again_on_the_cpu():
    pytest.importorskip("docling")
    from docling.datamodel.base_models import ConversionStatus
    from suveryn_rag.extract import convert_with_fallback

    oom = ["CUDA out of memory. Tried to allocate 100.00 MiB."] * 11
    gpu = _Converter(_Result(ConversionStatus.PARTIAL_SUCCESS, [4], oom))
    cpu = _Converter(_Result(ConversionStatus.SUCCESS, range(1, 13)))
    doc, device, errors = convert_with_fallback("x.pdf", gpu, lambda: cpu, on_gpu=True)
    assert (device, errors, cpu.calls) == ("cpu", [], 1)
    assert {i.prov[0].page_no for i in doc.items} == set(range(1, 13))

    ok = _Converter(_Result(ConversionStatus.SUCCESS, [1, 2]))
    never = _Converter(None)
    assert convert_with_fallback("x.pdf", ok, lambda: never, on_gpu=True)[1:] == ("cuda", []) and never.calls == 0

    other = _Converter(_Result(ConversionStatus.PARTIAL_SUCCESS, [1], ["unsupported image"]))
    _, device, errors = convert_with_fallback("x.pdf", other, lambda: never, on_gpu=True)
    assert device == "cuda" and len(errors) == 1 and never.calls == 0  # only out-of-memory is retried


def test_pages_with_text_the_layout_model_missed_are_found():
    from suveryn_rag.extract import unread_pages

    texts = ["Een pagina met genoeg tekst om als tekstpagina te gelden, zeker." * 2] * 4 + ["5"]
    assert unread_pages(_Doc([2]), texts) == [1, 3, 4]  # page 5 has (almost) no text layer: nothing to miss


def test_layout_failures_put_the_document_in_review():
    from suveryn_rag.integrity import IntegrityWarning

    assert IntegrityWarning(3, "layout_failed", "x").needs_review
    assert not IntegrityWarning(3, "instruction_like_text", "x").needs_review


def test_an_identical_upload_reads_again_only_a_poorly_read_copy():
    from suveryn_rag.pipeline import should_read_again

    assert not should_read_again("ok", 0.0)  # read well: the stored copy is returned
    assert not should_read_again("ok", 0.4)  # some recovered text is normal
    assert should_read_again("ok", 0.92)  # reported: 92% recovered from the text layer, read while the GPU was full
    assert should_read_again("needs_review", 0.0)


def test_quotes_read_as_mac_roman_are_put_right():
    from suveryn_rag.integrity import misdecoded_quotes, repair_quotes
    from suveryn_rag.pipeline import should_read_again

    reported = "de ÒopdrachtenreglementeringÓ van 2019 Ð zie art. 3, dÕHondt"  # reported 2026-10-11
    assert misdecoded_quotes(reported)
    assert repair_quotes(reported) == "de “opdrachtenreglementering” van 2019 – zie art. 3, d’Hondt"
    assert not misdecoded_quotes("Dara Ó Briain en Óscar")  # a real Ó is not evidence
    assert should_read_again("ok", 0.0, misdecoded=True)
