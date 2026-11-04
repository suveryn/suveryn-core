"""Text recognition reported page by page (``ocr_progress``): only OCRmyPDF's "OCR" stage counts, a page is
done when its last half is, and nothing is reported outside ``reporting``. No OCR is run."""

import pytest

pytest.importorskip("ocrmypdf")
from suveryn_rag import ocr_progress  # noqa: E402
from suveryn_rag.ocr_progress import PageProgress, reporting  # noqa: E402


def test_the_ocr_stage_reports_whole_pages_done_out_of_all():
    seen: list[tuple[int, int]] = []
    with reporting(lambda done, total: seen.append((done, total))):
        with PageProgress(total=3, desc="OCR", unit="page") as bar:
            for _ in range(6):
                bar.update(0.5)                   # each page in two halves: recognised, then put back
    assert seen == [(0, 3), (1, 3), (1, 3), (2, 3), (2, 3), (3, 3)]


def test_completed_sets_the_count_and_it_never_passes_the_total():
    seen: list[tuple[int, int]] = []
    with reporting(lambda done, total: seen.append((done, total))):
        bar = PageProgress(total=2, desc="OCR", unit="page")
        bar.update(completed=1)
        bar.update(5)
    assert seen == [(1, 2), (2, 2)]


@pytest.mark.parametrize("kw", [dict(total=4, desc="Optimize", unit="page"), dict(total=4, desc="OCR", unit="image"),
                                dict(total=None, desc="OCR", unit="page"), dict(total=0, desc="OCR", unit="page")])
def test_other_stages_and_unknown_totals_report_nothing(kw):
    seen: list = []
    with reporting(lambda *a: seen.append(a)):
        PageProgress(**kw).update(1)
    assert seen == []


def test_outside_reporting_nobody_is_told_and_nothing_fails():
    with reporting(lambda *a: None):
        assert ocr_progress.current is not None
    assert ocr_progress.current is None
    PageProgress(total=1, desc="OCR", unit="page").update(1)   # no reporter: nothing happens


def test_the_reporter_is_cleared_even_when_reading_fails():
    with pytest.raises(RuntimeError):
        with reporting(lambda *a: None):
            raise RuntimeError("tesseract died")
    assert ocr_progress.current is None


def test_ocrmypdf_is_given_this_progress_bar():
    assert ocr_progress.get_progressbar_class() is PageProgress
