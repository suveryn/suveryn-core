"""Following a document while it is read (docs/design/chat-ui.md §5, the attachment cards).

- ``Progress``: how far reading has got. A PDF is read in steps: text recognition on scanned pages
  (``ocr``, page by page: OCRmyPDF reports each page, ``ocr_progress``), the layout (``layout``, the
  whole document at once: Docling reports no pages), then storing it (``store``: passages, embeddings,
  the database). Word, Excel, Markdown and CSV files are read in one step (``read``).
- ``Watch``: what the job hands the reading: where to report progress, and whether the person has
  cancelled. ``check()`` raises ``Cancelled`` between steps; the reader process is stopped at once
  (``isolation``).
- ``Unreadable``: a document that can't be read, with a ``code`` the interface translates (the
  message stays English, for the log and the API) and the numbers it needs (``detail``).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from suveryn_harness import messages

Step = Literal["read", "ocr", "layout", "store"]


@dataclass(frozen=True)
class Progress:
    step: Step
    done: int | None = None    # pages done in this step, when it counts pages
    total: int | None = None   # the document's pages, when known


class Cancelled(Exception):
    """The person cancelled the upload while it was read."""


@dataclass
class Watch:
    report: Callable[[Progress], None] = field(default=lambda p: None)
    cancelled: Callable[[], bool] = field(default=lambda: False)

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled


class ReaderCrashed(Exception):
    """The isolated reader failed while it read, in a way nobody planned for: what it sent instead of an exception's
    message, which may quote the document, is its type (``kind``) and where it was raised (``where``). The service
    fails the job as ``system.internal`` with a reference logged with them, as any unplanned failure is."""

    def __init__(self, kind: str, where: str):
        super().__init__(kind)
        self.kind, self.where = kind, where


class Unreadable(ValueError):
    """The document can't be read. ``code`` is a refusal of the registry's ``document`` area
    (suveryn_harness/messages.json), with ``detail``'s numbers as its parameters (``pages``, ``max``,
    ``minutes``); anything else is ``document.unreadable``. A ValueError, as the reasons were before they had
    codes."""

    def __init__(self, message: str, code: str = "document.unreadable", **detail: int):
        super().__init__(message)
        known = messages.CODES.get(code)
        self.code = code if known and code.startswith("document.") and known.kind == "refused" else "document.unreadable"
        self.detail = {k: int(v) for k, v in detail.items()}
