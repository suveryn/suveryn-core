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

Step = Literal["read", "ocr", "layout", "store"]

# What the interface says for each code (chat-ui i18n, ``failure*``). Keep the two in step.
CODES = ("password", "damaged", "too_many_pages", "too_large", "no_text", "unsupported", "timeout", "unreadable")


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


class Unreadable(ValueError):
    """The document can't be read. ``code`` is one of ``CODES``; ``detail`` holds numbers for the message
    (``pages``, ``max``, ``minutes``). A ValueError, as the reasons were before they had codes."""

    def __init__(self, message: str, code: str = "unreadable", **detail: int):
        super().__init__(message)
        self.code = code if code in CODES else "unreadable"
        self.detail = {k: int(v) for k, v in detail.items()}
