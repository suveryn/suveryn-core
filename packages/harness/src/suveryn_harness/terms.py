"""Values worked out from another fact (board P01, decisions of 6 and 10 November 2026): a date written as a term, and
an amount written as a percentage.

An agreement often gives a deadline as a term ("binnen vier maanden na de ondertekening", "dans les deux mois
de la signature", "within 30 days after signing", "binnen tien werkdagen na …") rather than a date. A playbook says
which date such a term counts from (``counts_from: agreement_date``); when the run has that date, sūveryn works the
deadline out and says how: the date it counted from, the number and the unit. The value is then a date, and the fact
stays under *Check* until a person confirms it (``needs: computed``). Nothing is worked out when the term isn't one
this module reads with certainty: no figure, no unit, no direction (after or before), two terms, or no date to count
from; the value then stays as written, for a person to work out (``not_a_date``).

Months and years are calendar months and years: the same day number, or the month's last day when it has no
such day (31 January plus one month is 28 or 29 February). Working days are counted on the playbook's pack's
calendar (``suveryn_playbooks.Calendar``: which weekdays are worked, and the holidays), never on one country's for
all: a pack without one leaves a term in working days to a person, and the note says which calendar was used.

An amount is likewise often a share of another ("een voorschot van tien procent van de koopprijs"): a playbook says
which amount (``share_of: price``), and when the run has it, sūveryn works the amount out, written as that amount is
("€ 38.500,00"), and says how. Only a value that gives one percentage and nothing else is worked out.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from .language import NUMBER_WORDS, languages_of, table, words
from .values import Style, as_amount, as_percent, decimal_style, fold, number, read


class Calendar(Protocol):
    """What working days are counted on (``suveryn_playbooks.Calendar``, a pack's own data)."""

    name: dict[str, str]
    workdays: tuple[int, ...]
    fixed: tuple[str, ...]
    after_easter: tuple[int, ...]
    dates: tuple[str, ...]

# The words of a term come from the languages' files (``language``): the unit, what makes it a term before or after
# an event, what makes days working days, and "one" before a unit.
UNITS = table("time_units")                               # "maanden", "jours", "werkdagen" -> month, day, workday
BEFORE = set(words("term_before"))
# "binnen vier maanden na", "dans les deux mois de", "within four months of": the term is the period after the event
STRONG_AFTER = set(words("term_after"))
AFTER_RIGHT_BEHIND = set(words("term_after_right_behind"))  # "de", "of": after only right behind the unit
# "jours ouvrables", "business days": the word that makes days working days, after or before the unit
WORKING_AFTER = set(words("working_after"))
WORKING_BEFORE = set(words("working_before"))
ONE = set(words("one"))
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
MONTH_NAMES = {lang: t["months_written"] for lang, t in NUMBER_WORDS.items()}


def _language(unit_word: str, direction_words: list[str]) -> str:
    """The language a term is written in: its unit's, and where a unit is the same word in two languages ("week"),
    that of the word that says before or after."""
    of_unit = languages_of("time_units", unit_word)
    for name in ("term_before", "term_after", "term_after_right_behind"):
        for w in direction_words:
            both = [lang for lang in languages_of(name, w) if lang in of_unit]
            if both:
                return both[0]
    return of_unit[0] if of_unit else "en"


def read_term(text: str) -> tuple[int, str, int, str] | None:
    """(how many, the unit, +1 after or -1 before, the language) of the one term in the text, or None. The unit is
    day, week, month, year or workday ("werkdagen", "jours ouvrables", "business days")."""
    words = [fold(w) for w in _WORD.findall(text)]
    found: list[tuple[int, str, int, str]] = []
    for i, w in enumerate(words):
        unit = UNITS.get(w)
        if unit is None or i == 0:
            continue
        before, after = words[max(0, i - 3):i], words[i + 1:i + 4]
        if unit == "day" and after[:1] and after[0] in WORKING_AFTER:  # "jours ouvrables"
            unit, after = "workday", after[1:] + words[i + 4:i + 5]
        elif unit == "day" and before[-1:] and before[-1] in WORKING_BEFORE:  # "business days"
            unit, before = "workday", words[max(0, i - 4):i - 1]
        # "an" is a year in French only after a figure ("un an", "1 an"), never the English article
        how_many = _how_many(before)
        if how_many is None:
            continue
        if any(a in BEFORE for a in after[:2]):
            direction = -1
        elif any(a in STRONG_AFTER for a in after[:3]) or (after[:1] and after[0] in AFTER_RIGHT_BEHIND):
            direction = 1
        else:
            continue
        found.append((how_many, unit, direction, _language(w, after[:3])))
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


def add_term(base: date, how_many: int, unit: str, direction: int, cal: Calendar | None = None) -> date:
    """The date ``how_many`` units after (or before) ``base``; months and years as calendar months, working days on
    ``cal`` (the base day itself not counted)."""
    if unit == "workday":
        if cal is None:
            raise ValueError("working days need a calendar")
        return add_workdays(base, how_many, direction, cal)
    if unit in ("day", "week"):
        return base + timedelta(days=direction * how_many * (7 if unit == "week" else 1))
    months = direction * how_many * (12 if unit == "year" else 1)
    y, m = divmod(base.month - 1 + months, 12)
    year, month = base.year + y, m + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def easter(year: int) -> date:
    """Easter Sunday in the Gregorian calendar (the anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holidays(year: int, cal: Calendar) -> set[date]:
    """A calendar's holidays in one year."""
    out = {date(year, int(d[:2]), int(d[3:])) for d in cal.fixed}
    out |= {easter(year) + timedelta(days=n) for n in cal.after_easter}
    out |= {date.fromisoformat(d) for d in cal.dates if d.startswith(f"{year}-")}
    return out


def add_workdays(base: date, how_many: int, direction: int, cal: Calendar) -> date:
    """The date ``how_many`` working days after (or before) ``base`` on the calendar: a day is worked when its weekday
    is a working day and it is no holiday."""
    if not cal.workdays:
        raise ValueError("a calendar without working days")
    day, left, years = base, how_many, {}
    while left > 0:
        day += timedelta(days=direction)
        if day.year not in years:
            years[day.year] = holidays(day.year, cal)
        if day.weekday() in cal.workdays and day not in years[day.year]:
            left -= 1
    return day


def written(d: date, language: str) -> str:
    """A date as the agreement would write it: "12 februari 2027", "12 février 2027", "12 February 2027"."""
    return f"{d.day} {MONTH_NAMES.get(language, MONTH_NAMES['en'])[d.month - 1]} {d.year}"


def work_out(text: str, base: tuple[int, int, int] | None, cal: Calendar | None = None) -> tuple[str, dict] | None:
    """The term in ``text`` counted from ``base`` (day, month, year): the date as written, and how it was worked
    out (for the card: "Worked out: 12 October 2026 plus four months"). Working days need ``cal``, and the note names
    it. None when there is nothing to count."""
    term = read_term(text)
    if term is None or base is None:
        return None
    how_many, unit, direction, language = term
    if unit == "workday" and cal is None:
        return None  # no calendar of this pack's working days: a person counts them
    try:
        start = date(base[2], base[1], base[0])
        end = add_term(start, how_many, unit, direction, cal)
    except (ValueError, OverflowError):
        return None
    how = {"base": start.isoformat(), "amount": how_many, "unit": unit,
           "direction": "after" if direction > 0 else "before", "date": end.isoformat()}
    if unit == "workday" and cal is not None:
        how["calendar"] = dict(cal.name)
    return written(end, language), how


def work_out_share(text: str, of: str, style: Style = None) -> tuple[str, dict] | None:
    """The percentage in ``text`` of the amount ``of`` ("tien procent van de koopprijs" of "EUR 385.000,00"): the amount
    as ``of`` writes amounts ("EUR 38.500,00"), and how it was worked out. None when ``text`` gives no one percentage
    alone, or ``of`` no amount."""
    percent = as_percent(text, style)
    whole = as_amount(of, style)
    if percent is None or whole is None:
        return None
    share = (whole * percent / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return written_like(share, of, style), {"kind": "share", "percent": format(percent.normalize(), "f"), "of": str(whole),
                                             "amount": str(share)}


def written_like(value: Decimal, like: str, style: Style = None) -> str:
    """An amount written the way ``like`` writes its amount: its decimal separator and grouping, decimals when it has
    them (or the amount needs them), and its currency before or after."""
    found = next((f for f in read(like, style) if f.kind == "number"), None)
    raw = like[found.start:found.end] if found else ""
    style = style or decimal_style(like)
    dec = "." if style == "point" or (style is None and re.search(r",\d{3}(?!\d)", raw) and "." in raw.split(",")[-1]) else ","
    group = " " if re.search(r"\d[ \u00a0\u202f]\d{3}", raw) else ("," if dec == "." else ".")
    places = 2 if re.search(r"[.,]\d{2}$", raw) or value != value.to_integral() else 0
    whole, _, frac = f"{abs(value):.{places}f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", group)
    number = grouped + (dec + frac if places else "")
    currency = re.search(r"EUR|€|euro", like, re.IGNORECASE)
    if currency is None or found is None:
        return number
    return f"{currency.group(0)} {number}" if currency.start() < found.start else f"{number} {currency.group(0)}"
