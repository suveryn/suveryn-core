"""Evaluating a playbook's check steps (format 3, "Checks"): the rule a manifest states
(``suveryn_playbooks.rules``) against the run's values as they stand, read by kind the way the
check by meaning reads them (``values``). The server computes; the model never does arithmetic
(the harness's rule for ``[[calc]]``). A result is one of three: the rule holds, it fails (with both
sides as computed, for the notary), or it is open (a value is missing or gives no amount, number or
date as written: a person works it out first). A failed check is a point for the notary at the
checkpoint, never a block.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from suveryn_playbooks import entry, split
from suveryn_playbooks.rules import Rule, Term

from .calc import source_decimal_separator
from .values import as_amount, as_date, as_number


EMPTY = object()  # the latest or earliest of a list with no entries


@dataclass(frozen=True)
class CheckResult:
    status: str                 # "holds", "fails", "open"
    left: str = ""              # both sides as computed, in words a person reads ("50.000", "2026-11-03")
    right: str = ""
    missing: tuple[str, ...] = ()   # open: the paths whose values the rule needs and can't read


def evaluate(rule: Rule, values: dict[str, str], sep: str | None = None) -> CheckResult:
    """``values``: every current value by path (``price``, ``founders[2].contribution``), as written; a
    missing or empty value is not there. ``sep``: the decimal separator the values use; None: judged
    from the values themselves."""
    sep = sep or source_decimal_separator(" ".join(v for v in values.values() if v))
    left, lm = _value(rule.left, rule.value_kind, values, sep)
    right, rm = _value(rule.right, rule.value_kind, values, sep)
    missing = (*lm, *rm)
    if missing or left is None or right is None:
        return CheckResult("open", _show(left), _show(right), missing)
    if left is EMPTY or right is EMPTY:  # "every term falls before the deed" with no term at all: holds
        return CheckResult("holds", _show(left), _show(right))
    holds = {"==": left == right, "!=": left != right, "<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[rule.op]
    return CheckResult("holds" if holds else "fails", _show(left), _show(right))


def _value(term: Term, kind: str, values: dict[str, str], sep: str):
    """What a term yields, and the paths it needs but can't read."""
    if term.kind == "literal":
        return Decimal(term.literal), ()
    if term.kind == "fact":
        v = _typed(values.get(term.fact, ""), kind, sep)
        return v, (() if v is not None else (term.fact,))
    paths = [p for p in values if split(p)[0] == term.fact and p != term.fact]
    entries = sorted({split(p)[1] for p in paths if split(p)[1] is not None})  # type: ignore[misc]
    if term.kind == "count":
        return Decimal(len(entries)), ()
    found, missing = [], []
    for i in entries:
        path = entry(term.fact, i, term.field)
        v = _typed(values.get(path, ""), kind, sep)
        if v is None:
            missing.append(path)
        else:
            found.append(v)
    if missing:
        return None, tuple(missing)
    if term.kind == "sum":
        return sum(found, Decimal(0)), ()
    if not found:
        return EMPTY, ()  # latest or earliest of no entries: nothing to compare, the check holds (evaluate)
    return (max(found) if term.kind == "latest" else min(found)), ()


def _typed(value: str, kind: str, sep: str):
    if not value:
        return None
    if kind == "amount":
        return as_amount(value, sep)
    if kind == "number":
        return as_number(value, sep)
    d = as_date(value)
    return (d[2], d[1], d[0]) if d else None  # year, month, day: comparable


def _show(v) -> str:
    if v is None or v is EMPTY:
        return ""
    if isinstance(v, tuple):
        return f"{v[0]:04d}-{v[1]:02d}-{v[2]:02d}"
    return f"{v.normalize():f}"
