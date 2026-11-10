"""How sūveryn reads amounts, numbers and dates: the one reader of the harness (decision of 10 November 2026).

Deeds write "412 500,00 EUR", "1,2 miljoen", "zesentwintigduizend achthonderd euro", "le douze mai deux mille
quatorze", "2021-03-12". The citation check (``support``), the source marking (``marking``), a playbook's facts
(``facts``) and its checks (``checks``) each read them their own way until now, so a check and a marking could
disagree about the same text: 16 of 31 common forms read differently. Here they are read once, in Dutch, French
and English, and ``tests/reading_cases.json`` says what each form means:

- ``decimal_style`` and ``figure_value``: a figure by the document's way of writing decimals;
- ``read``: every amount, number and date in a text, with where it is;
- ``number``: number words ("zesentwintigduizend", "quatre-vingt-dix", "two hundred and five");
- ``as_amount`` / ``as_number`` / ``as_date``: one value, for a playbook's fact of that kind.

Deterministic and small on purpose: a value it can't read is left alone (no warning made up), and what uses it
still compares facts with their passage, never with what a model thinks they mean. Nothing else in the harness
is imported here.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

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
           "duizend": 1000, "mille": 1000, "mil": 1000, "thousand": 1000,
           "miljoen": 10**6, "million": 10**6, "millions": 10**6, "miljard": 10**9, "milliard": 10**9, "milliards": 10**9, "billion": 10**9}
_JOIN = {"en": "en", "et": "et", "and": "and"}
_ORDINALS = {"eerste": 1, "premier": 1, "1er": 1, "first": 1, "derde": 3, "troisieme": 3}
_SMALL = {**_UNITS_NL, **_UNITS_FR, **_UNITS_EN}
# The pieces one Dutch word is built of ("zesentwintigduizend"), longest first so "zeventien" wins over "zeven".
_MORPHEMES = sorted([*_UNITS_NL, *_SCALES, "en", "ën"], key=len, reverse=True)

MONTHS = {m: i for i, names in enumerate([
    ("januari", "janvier", "january", "jan"), ("februari", "fevrier", "february", "feb"),
    ("maart", "mars", "march", "mrt"), ("april", "avril", "apr"), ("mei", "mai", "may"), ("juni", "juin", "june"),
    ("juli", "juillet", "july"), ("augustus", "aout", "august", "aug"),
    ("september", "septembre", "sep", "sept"), ("oktober", "octobre", "october", "okt", "oct"),
    ("november", "novembre", "nov"), ("december", "decembre", "dec")], 1) for m in names}
_TOKEN = re.compile(r"[^\W_]+|€", re.UNICODE)


@lru_cache(maxsize=8192)
def fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word.casefold()) if not unicodedata.combining(c))


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
    # a word ending in "en" is no number ("Tienen", "achten"): Dutch number words never end with the joint
    return out if any(p != "en" for p in out) and out[-1] != "en" else None


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


# ------------------------------------------------------------------------------- how a document writes decimals

Style = Literal["comma", "point", "mixed"] | None

_UNIT = r"\s?(?:%|EUR|€|USD|\$|GBP|£|BEF)"
_COMMA_STYLE = re.compile(rf"\d{{1,3}}(?:\.\d{{3}})+,\d{{2}}(?![\d.,])|\d,\d{{2}}{_UNIT}|(?:EUR|€)\s?\d+,\d{{2}}(?![\d.,])")
_POINT_STYLE = re.compile(rf"\d{{1,3}}(?:,\d{{3}})+\.\d{{2}}(?![\d.,])|\d\.\d{{2}}{_UNIT}|(?:EUR|€|USD|\$)\s?\d+\.\d{{2}}(?![\d.,])")


def decimal_style(text: str) -> Style:
    """How a document writes decimals, read once from its whole text: "comma" when its amounts and percentages
    ("414.834,24 EUR", "6,49%") all write the decimals with a comma, "point" when they all use a point
    ("414,834.24", "11.50 EUR"), "mixed" when it has both, None when it has neither. Clause numbers ("2.15") and
    dates say nothing. Decision of 10 November 2026: a figure that reads either way ("28.848") is read in the style
    of the documents that write it, never guessed from the text around one passage."""
    c, p = bool(_COMMA_STYLE.search(text)), bool(_POINT_STYLE.search(text))
    return "mixed" if c and p else "comma" if c else "point" if p else None


_SPACES = re.compile(r"[    ]")


def figure_value(raw: str, style: Style = None) -> Decimal | None:
    """A figure's value. Both separators: the last is the decimal one ("1.275.000,00", "1,275,000.00"). One separator
    more than once: grouping ("1.275.000"). One separator once: decimals when one, two or four and more digits follow
    ("12,5", "12.5", "0,1234"), or after a lone 0 ("0,125"); three digits after it ("412,500", "1.250") read either
    way, and the document's ``style`` decides; a document that doesn't say reads them as thousands, as amounts are
    written far more often than three decimals. Spaces between groups of three are grouping ("1 275 000"). None for
    what isn't one figure ("2.15.3", a clause number)."""
    s = _SPACES.sub("", raw)
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        head, _, tail = s.rpartition(dec)
        groups = head.split("." if dec == "," else ",")
        if dec in head or not 1 <= len(groups[0]) <= 3 or any(len(g) != 3 for g in groups[1:]):
            return None
        return Decimal("".join(groups) + "." + tail)
    sep = "," if "," in s else "." if "." in s else None
    if sep is None:
        return Decimal(s)
    parts = s.split(sep)
    if len(parts) > 2:
        if 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
            return Decimal("".join(parts))
        return None
    head, tail = parts
    if len(tail) != 3 or head == "0" or len(head) > 3:
        return Decimal(head + "." + tail)
    decimal = (style == "comma" and sep == ",") or (style == "point" and sep == ".")
    return Decimal(head + "." + tail) if decimal else Decimal(head + tail)


# ------------------------------------------------------------------------------------- what a text says

@dataclass(frozen=True)
class Found:
    """One amount, number or date in a text, where it is (code-point offsets): ``kind`` "number" (``value`` a
    Decimal), "date" (day, month, year) or "month" (month, year: "maart 2021"). ``words``: a number written in
    words; ``currency``: a currency written right before or after it; ``percent``: a percentage ("10%", "tien procent");
    ``measure``: what the number measures, when the text says so right at it: a currency ("EUR", "USD", "GBP"),
    "percent", "area" (m², ha), or a time ("day", "week", "month", "year"); None for a bare number or a count of things;
    ``approximate``: the text says it isn't exact ("ongeveer", "circa", "environ", "about", "±")."""

    start: int
    end: int
    kind: Literal["number", "date", "month"]
    value: Decimal | tuple[int, ...]
    words: bool = False
    currency: bool = False
    percent: bool = False
    approximate: bool = False
    measure: str | None = None


_NOT_AFTER_WORD = r"(?<![^\W_])"
_LETTER = r"[^\W\d_]"
# A figure on its own, not glued to letters ("oyosish4" in OCR noise is no 4): grouped by . or , or by a (no-break)
# space between groups of three ("1 250"), never by any space ("2021 12" is two numbers).
_FIGURE = re.compile(_NOT_AFTER_WORD + r"(?:\d{1,3}(?:[    ]\d{3})+(?!\d)|\d+)(?:[.,]\d+)*(?!\d|" + _LETTER + ")")
# Scale words after a figure: "1,2 miljoen", "two million", "3 mio".
_FIGURE_SCALES = {"duizend": 10**3, "mille": 10**3, "thousand": 10**3, "miljoen": 10**6, "miljoenen": 10**6,
                  "million": 10**6, "millions": 10**6, "mio": 10**6, "mln": 10**6, "miljard": 10**9, "milliard": 10**9,
                  "milliards": 10**9, "billion": 10**9, "mld": 10**9}
_SCALE_AFTER = re.compile(r"[   ]*(" + "|".join(_FIGURE_SCALES) + r")\.?(?!" + _LETTER + ")", re.IGNORECASE)
_CURRENCY = r"(euros?|eur|€|usd|us\$|\$|dollars?|gbp|£|pounds?)"
_EURO_AFTER = re.compile(r"\s*" + _CURRENCY + r"(?![^\W_])", re.IGNORECASE)
_EURO_BEFORE = re.compile(r"(?<![^\W_])" + _CURRENCY + r"\s*$", re.IGNORECASE)
_CURRENCIES = {"euro": "EUR", "euros": "EUR", "eur": "EUR", "€": "EUR", "usd": "USD", "us$": "USD", "$": "USD", "dollar": "USD",
               "dollars": "USD", "gbp": "GBP", "£": "GBP", "pound": "GBP", "pounds": "GBP"}
_AREA_AFTER = re.compile(r"\s*(?:m²|m2\b|ha\b|vierkante\s+meters?\b|mètres?\s+carrés?\b|square\s+met(?:er|re)s?\b|sq\.?\s?m\b)", re.IGNORECASE)
_WORD_AFTER = re.compile(r"\s+([^\W\d_]+)")
# A time a number counts, by the word right after it ("6 weken", "trois mois", "30 days"); working days are days here
_TIMES = {**dict.fromkeys(("dag", "dagen", "werkdag", "werkdagen", "jour", "jours", "day", "days"), "day"),
          **dict.fromkeys(("week", "weken", "semaine", "semaines", "weeks"), "week"),
          **dict.fromkeys(("maand", "maanden", "mois", "month", "months"), "month"),
          **dict.fromkeys(("jaar", "jaren", "an", "ans", "annee", "annees", "year", "years"), "year")}


def _measure(text: str, start: int, end: int, percent: bool) -> tuple[bool, str | None]:
    """(a currency is written at the number, what the number measures) for the number at ``[start, end)``."""
    if percent:
        return False, "percent"
    money = _EURO_AFTER.match(text, end) or _EURO_BEFORE.search(text[max(0, start - 8):start])
    if money:
        return True, _CURRENCIES[money.group(1).lower()]
    if _AREA_AFTER.match(text, end):
        return False, "area"
    word = _WORD_AFTER.match(text, end)
    return False, _TIMES.get(fold(word.group(1))) if word else None
_ISO = re.compile(r"(?<![\d.,/-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d])")
_NUMERIC_DATE = re.compile(r"(?<![\d.,/-])(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?!\d|[.,]\d)")
_MONTH_NAME = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")"
_MONTH_FIRST = re.compile(_NOT_AFTER_WORD + r"(" + _MONTH_NAME + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")
PERCENT_SIGN = re.compile(r"[ \u00a0\u202f]*(?:%|procent|percent|pourcent|pour[ \u00a0]cent|pct\.?)$", re.IGNORECASE)
_PERCENT_AFTER = re.compile(r"[ \u00a0\u202f]*(?:%|procent|percent|pourcent|pour[ \u00a0]cent|pct\.?)(?![^\W_])", re.IGNORECASE)
# Words that say a figure isn't exact, right before it (an amount's currency may sit between): "ongeveer € 450.000",
# "circa 12", "environ 10 %", "about 3", "± 450.000". What they qualify (an amount, a surface) is for the user to judge.
_APPROXIMATE_BEFORE = re.compile(r"(?:ongeveer|ong\.|circa|ca\.|zowat|nagenoeg|plusminus|environ|approximativement|à peu près|"
                                 r"approximately|approx\.|about|around|roughly|±|\+/-|~)\s*(?:(?:euro|eur|€)\s*)?$", re.IGNORECASE)


def _approximate(text: str, start: int) -> bool:
    return bool(_APPROXIMATE_BEFORE.search(text[max(0, start - 32):start]))


# A single word that is an article far more often than a count: "een woning", "un immeuble", "one of them".
_ARTICLES = {"een", "un", "une", "one"}


def _year(y: str) -> int:
    return int(y) if len(y) == 4 else 2000 + int(y) if int(y) < 50 else 1900 + int(y)


def _real(day: int, month: int, year: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def read(text: str, style: Style = None) -> list[Found]:
    """Every amount, number and date in a text, in order, as one reader sees them for the whole harness (the
    citation check, the source marking, a playbook's facts and checks): ``reading_cases.json`` says what each written
    form means. ``style``: how the document writes decimals (``decimal_style``). Dates are read first, so a date's
    figures are no amounts; then figures, with a scale word after them; then numbers in words."""
    out: list[Found] = []

    def free(a: int, z: int) -> bool:
        return not any(a < f.end and z > f.start for f in out)

    def add(f: Found) -> None:
        if free(f.start, f.end):
            out.append(f)

    folded = fold(text)  # same length as text for the scripts deeds use; MONTHS keys are folded
    for m in _ISO.finditer(text):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        if _real(d, mo, y):
            add(Found(m.start(), m.end(), "date", (d, mo, y)))
    for m in _NUMERIC_DATE.finditer(text):
        d, mo, y = int(m[1]), int(m[3]), _year(m[4])
        if _real(d, mo, y):
            add(Found(m.start(), m.end(), "date", (d, mo, y)))
    if len(folded) == len(text):
        for m in _MONTH_FIRST.finditer(folded):
            mo, d, y = MONTHS[m[1]], int(m[2]), int(m[3])
            if _real(d, mo, y):
                add(Found(m.start(), m.end(), "date", (d, mo, y)))
    for f in _written_dates(text):
        add(f)
    for m in _FIGURE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        v = figure_value(m.group(0), style)
        if v is None:
            continue
        end = m.end()
        if scale := _SCALE_AFTER.match(text, end):
            v, end = v * _FIGURE_SCALES[scale.group(1).lower()], scale.end()
        percent = _PERCENT_AFTER.match(text, end)
        currency, measure = _measure(text, m.start(), end, bool(percent))
        add(Found(m.start(), percent.end() if percent else end, "number", v, currency=currency, percent=bool(percent),
                  approximate=_approximate(text, m.start()), measure=measure))
    for f in _word_numbers(text):
        add(f)
    return sorted(out, key=lambda f: f.start)


def _spans(text: str) -> list[re.Match]:
    return list(_TOKEN.finditer(text))


def _written_dates(text: str) -> list[Found]:
    """Dates with the month's name: the day before it in figures, as an ordinal or in words, the year after it in
    figures or words ("12 mei 2014", "1er mars 2021", "twaalf mei tweeduizend veertien", "le douze mai deux mille
    quatorze", "drie en twintig mei", the older notarial form); a month and a year alone are a month."""
    toks = _spans(text)
    words = [t.group(0) for t in toks]
    out: list[Found] = []
    for i, t in enumerate(toks):
        month = MONTHS.get(fold(t.group(0)))
        if month is None:
            continue
        year, last = None, i
        if i + 1 < len(toks) and re.fullmatch(r"\d{4}", words[i + 1]):
            year, last = int(words[i + 1]), i + 1
        else:
            run = []
            for w in words[i + 1:i + 6]:
                if _pieces(fold(w)) is None and fold(w) not in _JOIN:
                    break
                run.append(w)
            for k in range(len(run), 0, -1):
                n = number(run[:k])
                if n is not None and 1800 <= n <= 2100:
                    year, last = n, i + k
                    break
        if year is None:
            continue
        day, first = _day_before(words, i)
        if day is not None and _real(day, month, year):
            out.append(Found(toks[first].start(), toks[last].end(), "date", (day, month, year)))
        elif day is None and last == i + 1 and re.fullmatch(r"\d{4}", words[i + 1]):
            out.append(Found(t.start(), toks[last].end(), "month", (month, year)))
    return out


def _day(token: str) -> int | None:
    f = fold(token)
    if f in _ORDINALS:
        return _ORDINALS[f]
    m = re.fullmatch(r"(\d{1,2})(?:e|er|ste|de|st|nd|rd|th)?", f)
    if m:
        return int(m.group(1))
    n = number([f])
    if n is None:  # an ordinal in words: "drieëntwintigste", "tweede"
        stem = re.sub(r"(ste|de)$", "", f)
        n = number([stem]) if stem != f else None
    return n if n is not None and 1 <= n <= 31 else None


def _day_before(tokens: list[str], i: int) -> tuple[int | None, int]:
    """The day written before the month at ``i`` and the index of its first token: one token ("12", "twaalf",
    "drieëntwintigste"), or several number words: the older notarial form "drie en twintig", "vijf en twintigste",
    French "vingt-trois" (VM regression 9c97d76, finding 3). The longest run of up to four words that reads as 1 to 31."""
    for k in (4, 3, 2):
        if i < k:
            continue
        words = [fold(w) for w in tokens[i - k:i]]
        if words[-1] not in _JOIN and _pieces(words[-1]) is None:
            words[-1] = re.sub(r"(ste|de)$", "", words[-1])  # an ordinal's last word
        if words[0] in _JOIN or words[-1] in _JOIN or not all(w in _JOIN or _pieces(w) is not None for w in words):
            continue
        n = number(words)
        if n is not None and 1 <= n <= 31:
            return n, i - k
    if i < 1:
        return None, i
    return _day(tokens[i - 1]), i - 1


_TEN_IS_ENGLISH = re.compile(r"\b(?:the|of|and|days?|weeks?|months?|years?|per ?cent|within|shall|is|are|per|for|by)\b|\bten\s*\(10\)",
                             re.IGNORECASE)


def _word_numbers(text: str) -> list[Found]:
    """Numbers written in words: runs of number words ("zesentwintigduizend achthonderd", "deux cent mille", "vingt
    et un"). Not a scale word alone ("pour cent"), not an article ("een woning"), not "in acht nemen"."""
    toks = _spans(text)
    out: list[Found] = []
    i = 0
    while i < len(toks):
        if _pieces(fold(toks[i].group(0))) is None:
            i += 1
            continue
        j = i
        while j + 1 < len(toks) and (_pieces(fold(toks[j + 1].group(0))) is not None
                                     or (fold(toks[j + 1].group(0)) in _JOIN and j + 2 < len(toks)
                                         and _pieces(fold(toks[j + 2].group(0))) is not None)) \
                and not text[toks[j].end():toks[j + 1].start()].strip(" - "):
            j += 1
        run = [t.group(0) for t in toks[i:j + 1]]
        start, end, i = toks[i].start(), toks[j].end(), j + 1
        pieces = [p for w in run for part in fold(w).split("-") if part and part not in _JOIN for p in (_pieces(part) or [])]
        if len(pieces) == 1 and pieces[0] in _SCALES:  # a scale word alone: "pour cent", "duizend"
            continue
        if len(run) == 1 and run[0].lower() in _ARTICLES:
            continue
        if fold(run[-1]) == "acht" and len(run) == 1 and re.search(r"\bin\s+$", text[max(0, start - 4):start], re.IGNORECASE):
            continue
        if len(run) == 1 and fold(run[0]) == "ten" and text.strip() != run[0] and not _TEN_IS_ENGLISH.search(
                text[max(0, start - 60):end + 60]):
            continue  # Dutch "ten laste", "ten kadaster": ten only where the text around it is English, or says "(10)"
        n = number(run)
        if n is None:
            continue
        percent = _PERCENT_AFTER.match(text, end)
        currency, measure = _measure(text, start, end, bool(percent))
        out.append(Found(start, percent.end() if percent else end, "number", Decimal(n), words=True,
                         currency=currency, percent=bool(percent), approximate=_approximate(text, start), measure=measure))
    return out


# ----------------------------------------------------------------------------- one value, for a playbook's fact

def numbers_in(text: str, style: Style = None) -> set[Decimal]:
    """Every number in a passage, short ones and those in words included: what a ``number`` fact's value is checked
    against (``as_number``). The citation check leaves short figures out on purpose (``support``), which is right
    for a chat answer and wrong for a count the playbook asked for."""
    return {f.value for f in read(text, style) if f.kind == "number"}


def first_amount(value: str, style: Style = None) -> Found | None:
    """One fact's amount, with what the text says about it (approximate): the first amount in it. A short plain
    figure ("3 aandelen", "art. 12") is none, nor a percentage, nor a number in words under a thousand without euro."""
    for f in read(value, style):
        if f.kind != "number" or f.percent:
            continue
        if f.words and (f.value >= 1000 or f.currency):
            return f
        if not f.words and (f.value >= 100 or re.search(r"[.,\s]", value[f.start:f.end])):
            return f
    return None


def as_amount(value: str, style: Style = None) -> Decimal | None:
    """One fact's amount (``first_amount``), its value only."""
    f = first_amount(value, style)
    return f.value if f else None


def as_percent(value: str, style: Style = None) -> Decimal | None:
    """The one percentage a value gives ("10%", "tien procent van de koopprijs", "2,5 pour cent"), or None when it gives
    none, or two (no guess which), or an amount besides it."""
    found = [f for f in read(value, style) if f.kind == "number"]
    shares = [f for f in found if f.percent]
    if len(shares) != 1 or len(found) != 1 or not 0 < shares[0].value <= 100:
        return None
    return shares[0].value


def as_number(value: str, style: Style = None) -> Decimal | None:
    """One fact's number (a count, a share, a percentage: a figure without currency): the first number, however
    short ("3 aandelen" -> 3)."""
    return next((f.value for f in read(value, style) if f.kind == "number"), None)


def as_date(value: str) -> tuple[int, int, int] | None:
    """One fact's date: numeric (12/05/2014) or written (12 mei 2014, in words too)."""
    return next((f.value for f in read(value) if f.kind == "date"), None)
