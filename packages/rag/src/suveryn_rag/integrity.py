"""Checks that no document text is silently lost between the PDF and the stored chunks.

Four safeguards, prompted by losses seen on real documents:

1. Furniture rule: layout models label some text as page header/footer ("furniture") and
   drop it. Only text that really repeats (page numbers, a running title on most pages) may
   be dropped; anything else is restored as document text.
2. Completeness: every body text item must end up in a chunk. A heading with no text after
   it (e.g. a closing "Voor eensluidend afschrift") gets no chunk from the chunker, so it is
   recovered as a chunk of its own.
3. Text-layer recovery (``missing_words``, ``lines_with``): lines of a page's PDF text layer that
   hold words no stored chunk contains (e.g. table cells the table model couldn't place) are
   kept verbatim as a chunk of their own.
4. Page coverage: the words of each page's PDF text layer are compared with the stored
   chunks for that page. A shortfall that remains after recovery is reported as a warning and
   puts the document in ``needs_review``, because then text was lost in a way we don't
   recognise yet.

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
    """Something a reviewer of the document should know: where, what kind, and a text-free detail."""

    page: int | None
    kind: str     # "text_recovered" | "furniture_restored" | "text_layer_recovered" | "page_coverage_low"
                  # | "instruction_like_text" (text addressed to an AI; pipeline.py, suveryn-tracker#21)
                  # | "layout_failed" (Docling couldn't read the page; pipeline.py)
    detail: str

    @property
    def needs_review(self) -> bool:
        """True if this warning should put the document in ``needs_review``."""
        # Recovered or restored text is kept, so the document is complete; a coverage
        # shortfall means text may be missing, which a person has to check.
        return self.kind in ("page_coverage_low", "layout_failed")


# Characters read with the wrong encoding. A PDF font can encode its text as Mac Roman; read as Windows-1252
# or Latin-1, “ ” ’ – é ö come out as Ò Ó Õ Ð Ž š (reported 2026-10-11: "ÒopdrachtenreglementeringÓ",
# "ŽŽn" for "één"). Text encoded as UTF-8 and read as Windows-1252 gives "Ã©" for "é". Fixed per document,
# and only characters that are unusual in Dutch, French, English or German text, so correct text next to
# them (a document can mix fonts) is left alone.
USUAL = set("éèêëàáâäçïîíìôöóòùûüúÿñœæßãõåøÉÈÊËÀÁÂÄÇÏÎÍÔÖÙÛÜÚÑŒÆÃÅØ"
            "“”‘’„‚–—…•€°§©®™«»·×±²³¹½¼¾µ‰′″¡¿¢£¥¶\u00a0\u202f\u2009\u2010\u2011\u00ad")
# PDFium marks a hyphen it put at a line break as U+FFFE (a noncharacter, never real text).
LINE_BREAK_HYPHEN = "\ufffe"
_UTF8_AS_CP1252 = re.compile("[\u00c2-\u00f4][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u2122]{1,3}")
MIN_REPAIRS = 3  # a single odd character ("Ó Briain") is no evidence


def _unusual(ch: str) -> bool:
    return ord(ch) > 127 and ch not in USUAL and ch != LINE_BREAK_HYPHEN


def _byte(ch: str) -> bytes | None:
    try:
        return ch.encode("cp1252")
    except UnicodeEncodeError:
        return bytes([ord(ch)]) if ord(ch) < 256 else None  # Latin-1 (cp1252 leaves 0x81, 0x8d, ... undefined)


def _mac_roman(ch: str) -> str | None:
    """What an unusual character was if its byte was Mac Roman, when that is a usual character."""
    b = _byte(ch)
    fixed = b.decode("mac_roman") if b else None
    return fixed if fixed in USUAL else None


def _utf8(run: str) -> str | None:
    try:
        fixed = b"".join(_byte(c) or b"\xff" for c in run).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return fixed if len(fixed) == 1 and (fixed in USUAL or fixed.isalpha()) else None


def misdecoding(text: str) -> str | None:
    """How ``text`` was misread, if it clearly was: "utf-8" or "mac_roman" (at least ``MIN_REPAIRS`` characters
    put right, and nearly all unusual characters explained), else None."""
    utf8 = [m for m in _UTF8_AS_CP1252.finditer(text) if _utf8(m.group())]
    if len(utf8) >= MIN_REPAIRS:
        return "utf-8"
    unusual = [ch for ch in text if _unusual(ch)]
    fixable = [ch for ch in unusual if _mac_roman(ch)]
    return "mac_roman" if len(fixable) >= MIN_REPAIRS and len(fixable) >= 0.8 * len(unusual) else None


def repair_characters(text: str, how: str | None) -> str:
    """``text`` put right as ``misdecoding`` found the document misread; line-break hyphens always."""
    text = text.replace(LINE_BREAK_HYPHEN, "-")
    if how == "utf-8":
        return _UTF8_AS_CP1252.sub(lambda m: _utf8(m.group()) or m.group(), text)
    if how == "mac_roman":
        text = "".join((_mac_roman(ch) or ch) if _unusual(ch) else ch for ch in text)
        # Ô is usual (French), but in such a document Ô opening a word is a misread ‘ ("Ôwelzijn op het werk’").
        return re.sub(r"(?<![^\s(])Ô(?=[^\W\d_])(?=[^’\n]{1,80}’)", "‘", text)
    return text


def norm(text: str) -> str:
    """Lower-case, NFKC-normalised text with typographic dashes, quotes and the low comma (U+201A) unified."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‚", ",").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip()


def words(text: str) -> set[str]:
    """Comparable words: 2+ letters/digits, line-end hyphenation joined, punctuation ignored."""
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return set(re.findall(r"\w{2,}", norm(text)))


# OCR noise: text in a figure that is upside down or mirrored, read by OCR as letters (reported 2026-10-11:
# a rotated diagram came back as "(uesozoeysjeerdsuom — sBuinebwo) …" and was restored as missing text).
# Such words have a capital inside them, letters followed by a digit, or no vowel; real text rarely does.
_WEIRD = re.compile(r"[a-zß-ÿ][A-ZÀ-Þ]|[^\W\d_]\d|^[^\W\d_aeiouyàáâäèéêëìíîïòóôöùúûüAEIOUYÀ-ÏÒ-ÖÙ-Ü]{3,}$")


def ocr_noise(line: str, vocabulary: set[str]) -> bool:
    """Whether a text-layer line is OCR noise: several odd words (``_WEIRD``), and most of its words occur
    nowhere in the document's other text (``vocabulary``, as ``words`` gives them)."""
    tokens = [t for t in (re.sub(r"^\W+|\W+$", "", t) for t in line.split()) if len(t) >= 2]
    if not tokens:
        return False
    weird = sum(bool(_WEIRD.search(t)) for t in tokens)
    unknown = sum(not (words(t) <= vocabulary) for t in tokens)
    # A short line only when every word is odd twice over ("3Y91Za03"), not a name like "McDonald".
    short_ok = all(len(_WEIRD.findall(t)) >= 2 for t in tokens)
    return weird >= 1 and (len(tokens) >= 3 or short_ok) and weird / len(tokens) >= 0.15 and unknown / len(tokens) >= 0.5


def is_page_number(text: str) -> bool:
    """True for "3", "Pagina 3", "pagina 3 van 8", "Page 2 of 5", "p. 4", "- 7 -" and similar."""
    return bool(PAGE_NUMBER.match(text.strip()))


def split_furniture(furniture: list[tuple[int, str]], n_pages: int) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Split header/footer items into (dropped, restored).

    Dropped: page numbers, and text that (with digits ignored) recurs on at least half the
    pages, minimum two. Everything else is real content the layout model mislabelled.
    """
    key = lambda t: re.sub(r"\d+", "#", norm(t))
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


def missing_words(page_texts: list[str], chunk_pages: list[tuple[int | None, int | None, str]],
                  dropped: list[tuple[int, str]]) -> dict[int, tuple[set[str], set[str]]]:
    """Per page: (words of its text layer, those not found in the stored text that claims the page).

    chunk_pages: (page_start, page_end, text incl. headings) per stored chunk.
    dropped: furniture that was legitimately dropped (its words are not counted as missing).
    """
    out = {}
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
        out[p] = (ref, ref - have)
    return out


def page_coverage(page_texts: list[str], chunk_pages: list[tuple[int | None, int | None, str]],
                  dropped: list[tuple[int, str]]) -> list[IntegrityWarning]:
    """Compare each page's text layer with the stored text that claims that page."""
    warnings = []
    for p, (ref, missing) in missing_words(page_texts, chunk_pages, dropped).items():
        coverage = 1 - len(missing) / len(ref)
        if coverage < COVERAGE_THRESHOLD and len(missing) >= MIN_MISSING_WORDS:
            warnings.append(IntegrityWarning(p, "page_coverage_low",
                                    f"{coverage:.1%} of the page's words found in stored text; {len(missing)} missing"))
    return warnings


def lines_with(page_text: str, missing: set[str]) -> str:
    """The text-layer lines of a page that contain any of the missing words, in reading order.

    Used to recover text the layout or table model dropped (e.g. table cells it couldn't place):
    the lines come straight from the PDF's text layer, so nothing is invented or reworded.
    """
    keep = [line.strip() for line in page_text.splitlines() if line.strip() and words(line) & missing]
    return "\n".join(dict.fromkeys(keep))  # drop repeated lines, keep order


# ---------------------------------------------------------------- keyword search helpers
STOPWORDS = {"wat", "welke", "welk", "wie", "waar", "wanneer", "hoe", "hoeveel", "waarom", "waarvoor", "is", "zijn", "er", "een", "de", "het", "van", "voor", "in", "op", "aan", "met", "door", "bij", "naar", "en", "of", "te", "die", "dat", "dit", "deze", "heeft", "hebben", "wordt", "worden", "kan", "mag", "moet", "ook", "nog", "niet", "geen", "als", "om", "tot", "uit", "over", "onder", "the", "an", "what", "which", "who", "whom", "when", "where", "how", "much", "many", "does", "do", "did", "are", "was", "were", "be", "to", "for", "on", "and", "or", "with", "by", "at", "from", "le", "la", "les", "des", "du", "un", "une", "quel", "quelle", "quels", "quelles", "qui", "que", "est", "et", "ou", "au", "aux", "pour", "par", "sur", "dans"}


def query_terms(question: str) -> list[str]:
    """Search terms from a question: no stopwords, no words under 3 letters (numbers are kept), order kept, no duplicates."""
    seen, out = set(), []
    for t in re.findall(r"\w+", norm(question)):
        if (len(t) >= 3 or t.isdigit()) and t not in STOPWORDS and t not in seen:
            seen.add(t)
            out.append(t)
    return out
