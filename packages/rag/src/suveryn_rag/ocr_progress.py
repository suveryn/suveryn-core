"""An OCRmyPDF plugin that reports text recognition page by page (``reading.Progress``, step ``ocr``).

OCRmyPDF reports its work through a progress bar it asks its plugins for (``get_progressbar_class``);
this one forwards the page count of the "OCR" stage to ``current``, the reporter of the document being
read, and ignores the other stages. Set ``current`` around one ``ocrmypdf.ocr`` call (``reporting``);
the reader reads one document at a time. It never writes to stdout (OCRmyPDF's rule, and the reader's
answers go there).
"""

import contextlib
import threading
from collections.abc import Callable, Iterator

from ocrmypdf import hookimpl

current: Callable[[int, int], None] | None = None   # (pages done, pages in all)
_lock = threading.Lock()


@contextlib.contextmanager
def reporting(report: Callable[[int, int], None]) -> Iterator[None]:
    global current
    with _lock:
        current = report
    try:
        yield
    finally:
        with _lock:
            current = None


class PageProgress:
    """OCRmyPDF's ``ProgressBar`` protocol. A page counts as done when its last half is (OCRmyPDF
    reports a page in two halves: recognised, then put back into the PDF)."""

    def __init__(self, *, total=None, desc=None, unit=None, disable=False, **_):
        self.total, self.desc, self.done = total, desc, 0.0
        self.counts = desc == "OCR" and unit == "page" and bool(total)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, n=1, *, completed=None):
        if not self.counts:
            return
        self.done = float(completed) if completed is not None else self.done + n
        report = current
        if report is not None:
            report(min(int(self.done), int(self.total)), int(self.total))


@hookimpl(tryfirst=True)
def get_progressbar_class():
    return PageProgress
