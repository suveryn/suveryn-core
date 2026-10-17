"""The official playbooks: content and identity, no runtime (docs/design/playbooks.md).

A playbook is a fixed list of facts to read from a case's uploaded documents, the instructions the
model gets for it, and its identity: ``id`` (``playbook/<pack>/<name>``), ``pack`` and ``version``.
The identifiers are the platform's (docs/design/platform.md, "Identifiers"): they go into the run
record, every document a playbook produces, and later the registry and the licence, so they are
chosen once and never change. The version is separate from the id: a change that changes results
is a new minor version, a change that makes an old run unreadable a new major one.

``entitled(playbook_id)`` is the single place a licence check lands (the commercial model: a signed
file the office installs). Today every official playbook is entitled on every appliance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FactKind = Literal["text", "amount", "date"]


@dataclass(frozen=True)
class Fact:
    """One thing the playbook reads: its id (stable, the UI's vocabulary keys on it), what it is,
    in the words the model gets (English; the model answers in the documents' language), and its kind."""

    id: str
    ask: str
    kind: FactKind = "text"


@dataclass(frozen=True)
class Playbook:
    id: str            # playbook/<pack>/<name>
    pack: str          # pack/<profession-jurisdiction>
    version: str       # "1.0"
    name: str          # the result document's name, in English; the UI translates the label
    case_types: tuple[str, ...]  # which case types it fits (cases.md: the type decides which playbooks fit)
    facts: tuple[Fact, ...]
    instructions: str  # what the model is told, after the grounded instructions, before the excerpts
    languages: dict[str, dict[str, str]] = field(default_factory=dict)  # fact id -> label, per language; the UI's

    @property
    def slug(self) -> str:
        """The id's last part: the path segment in the API (``deed-intake``)."""
        return self.id.rsplit("/", 1)[1]

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])


def entitled(playbook_id: str) -> bool:
    """Whether this appliance may run the playbook. The licence check lands here (commercial model);
    until there is one, every official playbook is entitled."""
    return find(playbook_id) is not None


def find(playbook_id: str) -> Playbook | None:
    return next((p for p in PLAYBOOKS if p.id == playbook_id), None)


def by_slug(slug: str) -> Playbook | None:
    return next((p for p in PLAYBOOKS if p.slug == slug), None)


def for_case_type(case_type: str) -> list[Playbook]:
    return [p for p in PLAYBOOKS if case_type in p.case_types]


from .be_notary.deed_intake import (
    DEED_INTAKE,
)

PLAYBOOKS: tuple[Playbook, ...] = (DEED_INTAKE,)

__all__ = ["PLAYBOOKS", "Fact", "FactKind", "Playbook", "by_slug", "entitled", "find", "for_case_type"]
