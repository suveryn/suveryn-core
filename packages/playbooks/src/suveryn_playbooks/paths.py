"""Paths: how one value of a playbook's facts is named (format 3, docs/design/playbooks.md, "Lists").

A plain fact's value is named by its id: ``price``. A list's values are named by the entry's number,
counted from 1 in the order the documents give them, and the field: ``founders[1].name``,
``founders[2].contribution``; a list of plain values by the entry alone: ``conditions[2]``. The list's
own id, ``founders``, names the list as a whole (the fact that the documents name no founders at all is
recorded on it). Paths are the keys everything downstream works on: the run's record (``case_facts``),
the checkpoint, a person's answer, the summary. They are strings, so nothing that stores or sends a
fact id changes shape; only what a path means does.
"""
from __future__ import annotations

import re

MAX_ENTRIES = 50   # entries a list may have; a deed with more parties than this is one nobody checks at a glance

_PATH = re.compile(r"^([a-z][a-z0-9_]{0,49})(?:\[([1-9][0-9]?)\](?:\.([a-z][a-z0-9_]{0,49}))?)?$")


def split(path: str) -> tuple[str | None, int | None, str | None]:
    """``(root, entry, field)``: ``price`` -> ("price", None, None); ``founders[2].name`` -> ("founders", 2, "name");
    ``conditions[1]`` -> ("conditions", 1, None). Not a path: ``(None, None, None)``."""
    m = _PATH.match(path or "")
    if not m:
        return None, None, None
    root, index, field_id = m.group(1), m.group(2), m.group(3)
    if index is not None and int(index) > MAX_ENTRIES:
        return None, None, None
    return root, int(index) if index else None, field_id


def root(path: str) -> str:
    """The fact a path belongs to: ``founders[2].name`` -> ``founders``; a non-path is its own root."""
    r, _, _ = split(path)
    return r if r is not None else path


def entry(root_id: str, index: int, field_id: str | None = None) -> str:
    """The path of one entry's value: ``entry("founders", 2, "name")`` -> ``founders[2].name``."""
    return f"{root_id}[{index}]" + (f".{field_id}" if field_id else "")
