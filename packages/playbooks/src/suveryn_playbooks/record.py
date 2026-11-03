"""A playbook as a record: the loaded ``Playbook`` written out as plain data and read back, so a run
can keep the manifest it started under (docs/design/playbooks.md, "The data model": a run pinned to
its manifest). ``to_record`` is JSON-ready (dicts, lists, strings); ``from_record`` gives the same
``Playbook`` back, field for field, whatever the installed manifest has since become. Nothing in the
record is interpreted: a run reads its own facts, steps, instructions and words, and only those.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ._model import Fact, Playbook, Step, Wording


def to_record(playbook: Playbook) -> dict[str, Any]:
    """The playbook as plain data: ``dataclasses.asdict`` with tuples as lists."""
    d = asdict(playbook)
    return _plain(d)


def from_record(record: dict[str, Any]) -> Playbook:
    """The playbook a record describes. Unknown keys are refused (``TypeError``): a record a newer
    product wrote is not guessed at."""
    facts = tuple(_fact(f) for f in record["facts"])
    steps = tuple(Step(id=s["id"], kind=s["kind"], needs=tuple(s.get("needs", ())), facts=tuple(s.get("facts", ())),
                       min=s.get("min", 1), allow_none=s.get("allow_none", False), by=s.get("by", "anyone_in_case"),
                       template=s.get("template", "summary"), expects=s.get("expects", ""),
                       documents=tuple(s.get("documents", ())), rule=s.get("rule", ""), when=s.get("when", "")) for s in record.get("steps", ()))
    text = {lang: Wording(w["title"], w["summary"], dict(w["labels"]), dict(w.get("questions", {})), dict(w.get("checks", {})),
                          dict(w.get("steps", {})), w.get("facts_title", ""))
            for lang, w in record.get("text", {}).items()}
    return Playbook(id=record["id"], pack=record["pack"], version=record["version"], name=record["name"],
                    case_types=tuple(record["case_types"]), facts=facts, instructions=record["instructions"], text=text,
                    steps=steps, format=record.get("format", 2))


def _fact(f: dict[str, Any]) -> Fact:
    return Fact(id=f["id"], ask=f["ask"], kind=f.get("kind", "text"), fields=tuple(_fact(x) for x in f.get("fields", ())),
                item_kind=f.get("item_kind", "text"), options=tuple(f.get("options", ())))


def _plain(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v
