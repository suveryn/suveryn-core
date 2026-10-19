"""The official playbooks: content and identity, no runtime (docs/design/playbooks.md).

A playbook is a fixed list of facts to read from a case's uploaded documents, the instructions the
model gets for it, and its identity: ``id`` (``playbook/<pack>/<name>``), ``pack`` and ``version``.
The identifiers are the platform's (docs/design/platform.md, "Identifiers"): they go into the run
record, every document a playbook produces, and later the registry and the licence, so they are
chosen once and never change. The version is separate from the id: a change that changes results
is a new minor version, a change that makes an old run unreadable a new major one.

``covered(playbook_id)`` is the single place the licence check lands: whether the playbook is
certified and listed in the appliance's manifest (development context §8, suveryn-tracker#35). A
playbook that isn't covered still runs: the licensing model warns and never blocks. Today every
official playbook is covered on every appliance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FactKind = Literal["text", "amount", "date"]

# The product's interface languages, in this order: the server's one list (docs/translations.md).
# The gateway uses it for the sign-in page's language; the chat UI has the same list in
# packages/chat-ui/src/i18n/languages.ts and the Keycloak realm in supportedLocales;
# tests/test_content.py checks that they all agree and that every playbook has its words in each.
LANGUAGES = ("en", "nl", "fr")


@dataclass(frozen=True)
class Wording:
    """A playbook's words in one language: its title ("Deed intake"), one line on what it does, and
    a label per fact id. The playbook carries them, so a new playbook or pack needs no UI change."""

    title: str
    summary: str
    labels: dict[str, str]


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
    name: str          # in English: the stored result's file name ("Deed intake 2026/0417 (1.0).txt")
    case_types: tuple[str, ...]  # which case types it fits (cases.md: the type decides which playbooks fit)
    facts: tuple[Fact, ...]
    instructions: str  # what the model is told, after the grounded instructions, before the excerpts
    text: dict[str, Wording] = field(default_factory=dict)  # per language (LANGUAGES): title, summary, fact labels

    def wording(self, language: str) -> Wording:
        """The words in ``language``, else in English."""
        return self.text.get(language) or self.text["en"]

    @property
    def slug(self) -> str:
        """The id's last part: the path segment in the API (``deed-intake``)."""
        return self.id.rsplit("/", 1)[1]

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])


def pack_text(package: str, slug: str) -> dict[str, Wording]:
    """A playbook's words in every language, from its pack's ``text/<language>.json`` (one file per
    language for the whole pack, so a new language is one new file per pack; docs/translations.md)."""
    import json
    from importlib.resources import files

    out = {}
    for lang in LANGUAGES:
        entry = json.loads(files(package).joinpath("text", f"{lang}.json").read_text(encoding="utf-8"))[slug]
        out[lang] = Wording(entry["title"], entry["summary"], dict(entry["labels"]))
    return out


def covered(playbook_id: str) -> bool:
    """Whether the playbook is certified and covered by the appliance's support agreement (listed in
    its manifest by id and fingerprint). The licence check lands here and nowhere else. It never
    decides whether a run starts: an uncovered playbook runs with a warning to everyone (the
    licensing model, §8: "a warning, never a block"). Until there is a manifest, every official
    playbook is covered."""
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

__all__ = ["LANGUAGES", "PLAYBOOKS", "Fact", "FactKind", "Playbook", "Wording", "by_slug", "covered", "find", "for_case_type",
           "pack_text"]
