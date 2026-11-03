"""A step's ``when`` (format 3, "Choices"): the one condition a step may carry, read by a notary at a
glance: ``contribution_kind == cash``, ``contribution_kind != in_kind``. The fact is a ``choice``; the
option one of its options. The runtime evaluates it when the step is reached, on the choice's value
as it stands; a step whose condition doesn't hold is skipped and the thread says why. No and/or, no
other kinds of fact: the day a condition needs more, it needs a decision, not a longer line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ._model import Playbook

_WHEN = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*(==|!=)\s*([a-z][a-z0-9_]*)\s*$")


@dataclass(frozen=True)
class When:
    fact: str
    op: str          # "==" or "!="
    option: str

    def __str__(self) -> str:
        return f"{self.fact} {self.op} {self.option}"

    def holds(self, value: str | None) -> bool | None:
        """Whether the condition holds for the choice's value; None when the choice isn't known."""
        if not value:
            return None
        return (value == self.option) if self.op == "==" else (value != self.option)


def parse_when(text: str, playbook: Playbook) -> When:
    m = _WHEN.match(text or "")
    if not m:
        raise ValueError(f"when {text!r}: expected <choice fact> == <option> or <choice fact> != <option>")
    fact, op, option = m.groups()
    f = playbook.fact(fact)
    if f is None:
        raise ValueError(f"when {text!r}: {fact!r} is not one of the playbook's facts")
    if f.kind != "choice":
        raise ValueError(f"when {text!r}: {fact!r} is {f.kind}; a condition turns on a choice")
    if option not in f.options:
        raise ValueError(f"when {text!r}: {option!r} is not one of {fact}'s options ({', '.join(f.options)})")
    return When(fact, op, option)
