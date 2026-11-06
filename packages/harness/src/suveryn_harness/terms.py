"""A term written instead of a date, worked out (board P01, decision of 6 November 2026).

An agreement often gives a deadline as a term ("binnen vier maanden na de ondertekening", "dans les deux mois
de la signature", "within 30 days after signing") rather than a date. A playbook says which date such a term
counts from (``counts_from: agreement_date``); when the run has that date, sūveryn works the deadline out and
says how: the date it counted from, the number and the unit. The value is then a date, and the fact stays under
*Check* until a person confirms it (``needs: computed``). Nothing is worked out when the term isn't one this
module reads with certainty: no figure, no unit, no direction (after or before), two terms, working days (a
calendar of public holidays is not built), or no date to count from; the value then stays as written, for a
person to work out (``not_a_date``).

Months and years are calendar months and years: the same day number, or the month's last day when it has no
such day (31 January plus one month is 28 or 29 February).
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from .values import fold, number

UNITS = {
    "dag": "day", "dagen": "day", "jour": "day", "jours": "day", "day": "day", "days": "day",
    "week": "week", "weken": "week", "semaine": "week", "semaines": "week", "weeks": "week",
    "maand": "month", "maanden": "month", "mois": "month", "month": "month", "months": "month",
    "jaar": "year", "jaren": "year", "an": "year", "ans": "year", "annee": "year", "annees": "year", "year": "year", "years": "year",
}
LANGUAGE = {**{w: "nl" for w in ("dag", "dagen", "week", "weken", "maand", "maanden", "jaar", "jaren")},
            **{w: "fr" for w in ("jour", "jours", "semaine", "semaines", "mois", "an", "ans", "annee", "annees")},
            **{w: "en" for w in ("day", "days", "weeks", "month", "months", "year", "years")}}
BEFORE = {"voor", "voorafgaand", "avant", "precedant", "before", "prior", "preceding"}
# "binnen vier maanden na", "dans les deux mois de", "within four months of": the term is the period after the event
# ("de" and "of" read as after only right behind the unit; "vóór" is folded to "voor")
STRONG_AFTER = {"na", "vanaf", "volgend", "volgende", "rekenen", "apres", "compter", "suivant", "after", "from", "following"}
WORKING = {"werkdag", "werkdagen", "ouvrable", "ouvrables", "ouvre", "ouvres", "business", "working"}
ONE = {"een", "un", "une", "one", "a"}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

MONTH_NAMES = {
    "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}


def read_term(text: str) -> tuple[int, str, int, str] | None:
    """(how many, the unit, +1 after or -1 before, the language) of the one term in the text, or None."""
    words = [fold(w) for w in _WORD.findall(text)]
    if any(w in WORKING for w in words):
        return None  # working days: not worked out (no calendar of public holidays)
    found: list[tuple[int, str, int, str]] = []
    for i, w in enumerate(words):
        unit = UNITS.get(w)
        if unit is None or i == 0:
            continue
        # "an" is a year in French only after a figure ("un an", "1 an"), never the English article
        how_many = _how_many(words[max(0, i - 3):i])
        if how_many is None:
            continue
        after = words[i + 1:i + 4]
        if any(a in BEFORE for a in after[:2]):
            direction = -1
        elif any(a in STRONG_AFTER for a in after[:3]) or (after[:1] and after[0] in {"de", "of"}):
            direction = 1
        else:
            continue
        found.append((how_many, unit, direction, LANGUAGE.get(w, "en")))
    return found[0] if len(found) == 1 else None


def _how_many(before: list[str]) -> int | None:
    """The count right before a unit: a figure ("30"), number words ("vier", "quatre-vingt-dix", "dertig"), or
    one ("een maand", "un mois", "a month")."""
    if not before:
        return None
    last = before[-1]
    if last.isdigit():
        n = int(last)
        return n if 0 < n <= 3650 else None
    for start in range(len(before)):
        n = number(before[start:])
        if n is not None and 0 < n <= 3650:
            return n
    return 1 if last in ONE else None


def add_term(base: date, how_many: int, unit: str, direction: int) -> date:
    """The date ``how_many`` units after (or before) ``base``; months and years as calendar months."""
    if unit in ("day", "week"):
        return base + timedelta(days=direction * how_many * (7 if unit == "week" else 1))
    months = direction * how_many * (12 if unit == "year" else 1)
    y, m = divmod(base.month - 1 + months, 12)
    year, month = base.year + y, m + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def written(d: date, language: str) -> str:
    """A date as the agreement would write it: "12 februari 2027", "12 février 2027", "12 February 2027"."""
    return f"{d.day} {MONTH_NAMES.get(language, MONTH_NAMES['en'])[d.month - 1]} {d.year}"


def work_out(text: str, base: tuple[int, int, int] | None) -> tuple[str, dict] | None:
    """The term in ``text`` counted from ``base`` (day, month, year): the date as written, and how it was worked
    out (for the card: "Worked out: 12 October 2026 plus four months"). None when there is nothing to count."""
    term = read_term(text)
    if term is None or base is None:
        return None
    how_many, unit, direction, language = term
    try:
        start = date(base[2], base[1], base[0])
        end = add_term(start, how_many, unit, direction)
    except (ValueError, OverflowError):
        return None
    return written(end, language), {"base": start.isoformat(), "amount": how_many, "unit": unit,
                                     "direction": "after" if direction > 0 else "before", "date": end.isoformat()}
