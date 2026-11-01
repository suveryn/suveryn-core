"""Amounts and dates as a deed writes them: in figures, with a space between the thousands, or in words
(VM regression 03c8f74, finding 5 and question 1).

Deeds write "412 500,00 EUR", "zesentwintigduizend achthonderd euro", "le douze mai deux mille quatorze".
The checks compared figures letter for letter, so a right answer that wrote "412.500" was flagged against
a passage writing "412 500", and an amount the deed writes out could never be matched. Here they are
read as values, in Dutch, French and English:

- ``join_groups``: "412 500" (a space between groups of three digits) as one figure;
- ``amounts_in``: the amounts a text writes out in words (from a thousand, or followed by euro);
- ``dates_in``: the dates a text writes with the month's name, the day and the year in figures or words;
- ``number`` and ``as_amount`` / ``as_date``: one value, for a playbook's fact of kind amount or date.

Deterministic and small on purpose: a value it can't read is left alone (no warning made up), and the
check that uses it still compares facts with their passage, never with what a model thinks they mean.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

_UNITS_NL = {"nul": 0, "een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8,
             "negen": 9, "tien": 10, "elf": 11, "twaalf": 12, "dertien": 13, "veertien": 14, "vijftien": 15, "zestien": 16,
             "zeventien": 17, "achttien": 18, "negentien": 19, "twintig": 20, "dertig": 30, "veertig": 40, "vijftig": 50,
             "zestig": 60, "zeventig": 70, "tachtig": 80, "negentig": 90}
_UNITS_FR = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
             "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
             "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
             "septante": 70, "huitante": 80, "octante": 80, "nonante": 90}
_UNITS_EN = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
             "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
             "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"honderd": 100, "cent": 100, "cents": 100, "hundred": 100,
           "duizend": 1000, "mille": 1000, "thousand": 1000,
           "miljoen": 10**6, "million": 10**6, "millions": 10**6, "miljard": 10**9, "milliard": 10**9, "milliards": 10**9, "billion": 10**9}
_JOIN = {"en": "en", "et": "et", "and": "and"}
_ORDINALS = {"eerste": 1, "premier": 1, "1er": 1, "first": 1}
_SMALL = {**_UNITS_NL, **_UNITS_FR, **_UNITS_EN}
# The pieces one Dutch word is built of ("zesentwintigduizend"), longest first so "zeventien" wins over "zeven".
_MORPHEMES = sorted([*_UNITS_NL, *_SCALES, "en", "ën"], key=len, reverse=True)

MONTHS = {m: i for i, names in enumerate([
    ("januari", "janvier", "january", "jan"), ("februari", "fevrier", "february", "feb"),
    ("maart", "mars", "march", "mrt"), ("april", "avril", "apr"), ("mei", "mai", "may"), ("juni", "juin", "june"),
    ("juli", "juillet", "july"), ("augustus", "aout", "august", "aug"),
    ("september", "septembre", "sep", "sept"), ("oktober", "octobre", "october", "okt", "oct"),
    ("november", "novembre", "nov"), ("december", "decembre", "dec")], 1) for m in names}
_EURO = re.compile(r"^(euro|eur|€)$", re.IGNORECASE)
_TOKEN = re.compile(r"[^\W_]+|€", re.UNICODE)
_GROUPED = re.compile(r"(?<=\d) (?=\d{3}(?![\d]))")


def fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word.casefold()) if not unicodedata.combining(c))


def join_groups(text: str) -> str:
    """"412 500,00" as one figure: a space between groups of three digits becomes a narrow no-break space,
    which the figure readers already take as a thousands separator."""
    return _GROUPED.sub(" ", text)


def _pieces(word: str) -> list[str] | None:
    """A word as number pieces: "zesentwintigduizend" -> zes, en, twintig, duizend; None if it isn't one."""
    w = fold(word).replace("-", "")
    if w in _SMALL or w in _SCALES:
        return [w]
    out, i = [], 0
    while i < len(w):
        for m in _MORPHEMES:
            mm = fold(m)
            if w.startswith(mm, i):
                out.append(mm)
                i += len(mm)
                break
        else:
            return None
    return out if any(p != "en" for p in out) else None


def number(words: list[str]) -> int | None:
    """The value of number words ("zesentwintigduizend achthonderd", "deux mille quatorze", "quatre-vingt-dix",
    "two hundred and five"), or None when a word isn't part of a number."""
    pieces: list[str] = []
    for w in words:
        for part in fold(w).split("-"):
            if not part:
                continue
            if part in _JOIN:
                pieces.append("en")
                continue
            p = _pieces(part)
            if p is None:
                return None
            pieces += p
    if not any(p in _SMALL or p in _SCALES for p in pieces):
        return None
    total, small = 0, 0
    for p in pieces:
        if p == "en":
            continue
        if p in _SCALES:
            scale = _SCALES[p]
            if scale == 100:
                small = (small or 1) * 100
            else:
                total += (small or 1) * scale
                small = 0
        else:
            n = _SMALL[p]
            small = small * 20 if n == 20 and small and small % 100 == 4 and p.startswith("vingt") else small + n  # quatre-vingt
    return total + small


def _runs(text: str) -> list[tuple[list[str], str | None]]:
    """Runs of number words in a text, each with the word after it."""
    tokens = _TOKEN.findall(text)
    runs, current = [], []
    for i, t in enumerate(tokens):
        f = fold(t)
        if (f in _JOIN and current) or (f not in _JOIN and _pieces(f) is not None):
            current.append(t)
            continue
        if current:
            while current and fold(current[-1]) in _JOIN:
                current.pop()
            if current:
                runs.append((current, t))
            current = []
    if current:
        runs.append((current, None))
    return runs


def amounts_in(text: str) -> set[Decimal]:
    """The amounts a text writes out in words: from a thousand, or any written number followed by euro."""
    out = set()
    for words, after in _runs(text):
        n = number(words)
        if n is not None and (n >= 1000 or (after is not None and _EURO.match(after))):
            out.add(Decimal(n))
    return out


def _day(token: str) -> int | None:
    f = fold(token)
    if f in _ORDINALS:
        return _ORDINALS[f]
    m = re.fullmatch(r"(\d{1,2})(?:e|er|ste|de|st|nd|rd|th)?", f)
    if m:
        return int(m.group(1))
    n = number([f])
    return n if n is not None and 1 <= n <= 31 else None


def dates_in(text: str) -> set[tuple[int, int, int]]:
    """Dates written with the month's name, the day and the year in figures or in words:
    "12 mei 2014", "twaalf mei tweeduizend veertien", "le douze mai deux mille quatorze", "1er janvier 2020"."""
    tokens = _TOKEN.findall(text)
    out = set()
    for i, t in enumerate(tokens):
        month = MONTHS.get(fold(t).rstrip("."))
        if month is None or i == 0:
            continue
        day = _day(tokens[i - 1])
        if day is None:
            continue
        year = None
        if i + 1 < len(tokens) and re.fullmatch(r"\d{4}", tokens[i + 1]):
            year = int(tokens[i + 1])
        else:
            words = []
            for t2 in tokens[i + 1:i + 6]:
                if _pieces(fold(t2)) is None and fold(t2) not in _JOIN:
                    break
                words.append(t2)
            # the longest run of words that reads as a year
            for k in range(len(words), 0, -1):
                n = number(words[:k])
                if n is not None and 1800 <= n <= 2100:
                    year = n
                    break
        if year is not None:
            out.add((day, month, year))
    return out


def as_amount(value: str, sep: str = ",") -> Decimal | None:
    """One fact's amount: the first figure (read in the sources' decimal style) or the amount in words."""
    from .calc import TEXT_FIGURE, _value
    for f in TEXT_FIGURE.findall(join_groups(value)):
        if (v := _value(f, sep)) is not None and (len(re.sub(r"\D", "", f)) >= 3 or re.search(r"[., ]", f)):
            return v
    words = amounts_in(value)
    return min(words) if words else None


def as_date(value: str) -> tuple[int, int, int] | None:
    """One fact's date: numeric (12/05/2014) or written (12 mei 2014, in words too)."""
    from .calc import DATE
    m = DATE.search(value)
    if m:
        d, mo, y = (int(x) for x in re.split(r"[./-]", m.group(0)))
        return d, mo, y + 2000 if y < 100 else y
    found = dates_in(value)
    return min(found) if found else None
