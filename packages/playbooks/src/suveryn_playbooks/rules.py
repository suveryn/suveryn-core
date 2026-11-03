"""A check's rule (format 3, "Checks"): one comparison a notary can read, parsed here so the loader can
refuse a wrong one with the step named, and evaluated by the harness (``suveryn_harness.checks``),
which knows how to read an amount, a number or a date from a value as written.

    sum(founders.shares) == shares
    sum(founders.contribution) == contribution
    certified_amount == contribution
    count(founders) >= 1
    plan_date <= deed_date

A rule is ``term operator term``. A term names a fact (``contribution``), the sum of a list's field
(``sum(founders.contribution)``), the number of a list's entries (``count(founders)``) or a plain number
(``1``, ``100``, ``0.5``). Operators: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``. Both sides must be of one kind
(amount, number or date); a sum is of its field's kind, a count is a number, a literal is a number.
Nothing else: no arithmetic, no and/or, no text. The format grows into a programming language the day
a notary can't read a line and know what it does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ._model import LeafKind, Playbook

OPERATORS = ("==", "!=", "<=", ">=", "<", ">")
_TERM = re.compile(r"^(?:(sum)\(([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\)|(count)\(([a-z][a-z0-9_]*)\)|([a-z][a-z0-9_]*)|(\d+(?:\.\d+)?))$")
_RULE = re.compile(r"^\s*(.+?)\s*(==|!=|<=|>=|<|>)\s*(.+?)\s*$")


@dataclass(frozen=True)
class Term:
    """One side of a rule."""
    kind: str                 # "fact", "sum", "count", "literal"
    fact: str = ""            # the fact id, or the list id for sum and count
    field: str = ""           # sum: the field
    literal: str = ""         # literal: the number as written

    def __str__(self) -> str:
        if self.kind == "sum":
            return f"sum({self.fact}.{self.field})"
        if self.kind == "count":
            return f"count({self.fact})"
        return self.fact if self.kind == "fact" else self.literal


@dataclass(frozen=True)
class Rule:
    left: Term
    op: str
    right: Term
    value_kind: LeafKind       # what both sides are: amount, number or date

    def __str__(self) -> str:
        return f"{self.left} {self.op} {self.right}"

    @property
    def facts(self) -> tuple[str, ...]:
        """The facts the rule reads (list ids for sums and counts)."""
        return tuple(t.fact for t in (self.left, self.right) if t.kind != "literal")


def parse_rule(text: str, playbook: Playbook) -> Rule:
    """The rule a check step states, checked against the playbook's facts. ``ValueError`` says what is
    wrong, in words the loader prefixes with the step."""
    m = _RULE.match(text or "")
    if not m:
        raise ValueError(f"rule {text!r}: expected <term> <operator> <term> with one of {', '.join(OPERATORS)}")
    left, right = _term(m.group(1)), _term(m.group(3))
    kinds = (_kind_of(left, playbook), _kind_of(right, playbook))
    if left.kind == "literal" and right.kind == "literal":
        raise ValueError(f"rule {text!r}: compares two numbers and no fact")
    named = [k for k in kinds if k is not None]
    if len(set(named)) > 1:
        raise ValueError(f"rule {text!r}: compares {named[0]} with {named[1]}; both sides must be of one kind")
    kind = named[0]
    if kind == "date" and any(t.kind in ("literal", "sum", "count") for t in (left, right)):
        raise ValueError(f"rule {text!r}: a date compares only with a date fact")
    return Rule(left, m.group(2), right, kind)


def _term(text: str) -> Term:
    m = _TERM.match(text.strip())
    if not m:
        raise ValueError(f"term {text!r}: a fact id, sum(<list>.<field>), count(<list>) or a number")
    if m.group(1):
        return Term("sum", m.group(2), m.group(3))
    if m.group(4):
        return Term("count", m.group(5))
    if m.group(6):
        return Term("fact", m.group(6))
    return Term("literal", literal=m.group(7))


def _kind_of(term: Term, playbook: Playbook) -> LeafKind | None:
    """The kind of what the term yields; None for a literal (it takes the other side's)."""
    if term.kind == "literal":
        return None
    f = playbook.fact(term.fact)
    if f is None:
        raise ValueError(f"term {term}: {term.fact!r} is not one of the playbook's facts")
    if term.kind == "fact":
        if f.kind not in ("amount", "number", "date"):
            raise ValueError(f"term {term}: {term.fact!r} is {f.kind}; a check compares amounts, numbers or dates")
        return f.kind  # type: ignore[return-value]
    if f.kind != "list":
        raise ValueError(f"term {term}: {term.fact!r} is not a list")
    if term.kind == "count":
        return "number"
    x = f.field(term.field)
    if x is None:
        raise ValueError(f"term {term}: {term.fact!r} has no field {term.field!r}")
    if x.kind not in ("amount", "number"):
        raise ValueError(f"term {term}: {term.fact}.{term.field} is {x.kind}; a sum is of amounts or numbers")
    return x.kind
