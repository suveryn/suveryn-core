"""Checks that no document text is silently lost between the PDF and the stored chunks.

Three safeguards, prompted by losses seen on real deeds:

1. Furniture rule: layout models label some text as page header/footer ("furniture") and
   drop it. Only text that really repeats (page numbers, a running title on most pages) may
   be dropped; anything else is restored as document text.
2. Completeness: every body text item must end up in a chunk. A heading with no text after
   it (e.g. a closing "Voor eensluidend afschrift") gets no chunk from the chunker, so it is
   recovered as a chunk of its own.
3. Page coverage: the words of each page's PDF text layer are compared with the stored
   chunks for that page. A shortfall is reported as a warning and puts the document in
   ``needs_review``, because then text was lost in a way we don't recognise yet.

All functions here are pure (no Docling, no database), so they are cheap to test.
"""

import math
import re
import unicodedata
from dataclasses import dataclass

PAGE_NUMBER = re.compile(
    r"^\W*((pagina|page|blz|p)\.?\s*)?\d{1,4}(\s*(/|van|of|sur|de)\s*\d{1,4})?\W*$", re.IGNORECASE)
COVERAGE_THRESHOLD = 0.95  # share of a page's words that must be found in stored text
MIN_MISSING_WORDS = 3      # ignore tiny shortfalls (hyphenation, stray OCR marks)


@dataclass(frozen=True)
class IntegrityWarning:
    page: int | None
    kind: str     # "text_recovered" | "furniture_restored" | "page_coverage_low"
    detail: str

    @property
    def needs_review(self) -> bool:
        # Recovered or restored text is kept, so the document is complete; a coverage
        # shortfall means text may be missing, which a person has to check.
        return self.kind == "page_coverage_low"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‚", ",").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip()


def words(text: str) -> set[str]:
    """Comparable words: 2+ letters/digits, line-end hyphenation joined, punctuation ignored."""
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return set(re.findall(r"\w{2,}", norm(text)))


def is_page_number(text: str) -> bool:
    return bool(PAGE_NUMBER.match(text.strip()))


def split_furniture(furniture: list[tuple[int, str]], n_pages: int) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Split header/footer items into (dropped, restored).

    Dropped: page numbers, and text that (with digits ignored) recurs on at least half the
    pages, minimum two. Everything else is real content the layout model mislabelled.
    """
    key = lambda t: re.sub(r"\d+", "#", norm(t))  # noqa: E731
    pages_per_key: dict[str, set[int]] = {}
    for page, text in furniture:
        pages_per_key.setdefault(key(text), set()).add(page)
    needed = max(2, math.ceil(n_pages / 2))
    dropped, restored = [], []
    for page, text in furniture:
        if not text.strip():
            continue
        repeats = len(pages_per_key[key(text)]) >= needed
        (dropped if is_page_number(text) or repeats else restored).append((page, text))
    return dropped, restored


def page_coverage(page_texts: list[str], chunk_pages: list[tuple[int | None, int | None, str]],
                  dropped: list[tuple[int, str]]) -> list[IntegrityWarning]:
    """Compare each page's text layer with the stored text that claims that page.

    chunk_pages: (page_start, page_end, text incl. headings) per stored chunk.
    dropped: furniture that was legitimately dropped (its words are not counted as missing).
    """
    warnings = []
    for p, ref_text in enumerate(page_texts, 1):
        ref = words(ref_text)
        if not ref:
            continue
        have: set[str] = set()
        for start, end, text in chunk_pages:
            if start is not None and start - 1 <= p <= (end or start) + 1:  # chunks spanning a page break
                have |= words(text)
        for page, text in dropped:
            if page == p:
                have |= words(text)
        missing = ref - have
        coverage = 1 - len(missing) / len(ref)
        if coverage < COVERAGE_THRESHOLD and len(missing) >= MIN_MISSING_WORDS:
            warnings.append(IntegrityWarning(p, "page_coverage_low",
                                    f"{coverage:.0%} of the page's words found in stored text; {len(missing)} missing"))
    return warnings


# ---------------------------------------------------------------- keyword search helpers
STOPWORDS = set("""
wat welke welk wie waar wanneer hoe hoeveel waarom waarvoor is zijn er een de het van voor in op aan met door bij
naar en of te die dat dit deze heeft hebben wordt worden kan mag moet ook nog niet geen als om tot uit over onder
the an what which who whom when where how much many does do did is are was were be of to in for on and or with by at from
le la les de des du un une quel quelle quels quelles qui que est et ou en au aux pour par sur dans
""".split())


def query_terms(question: str) -> list[str]:
    """Search terms from a question: no stopwords, no 1-letter tokens, order kept, no duplicates."""
    seen, out = set(), []
    for t in re.findall(r"\w+", norm(question)):
        if (len(t) >= 3 or t.isdigit()) and t not in STOPWORDS and t not in seen:
            seen.add(t)
            out.append(t)
    return out
