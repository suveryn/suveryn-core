"""A playbook as the product sees it: ``Playbook``, ``Fact``, ``Wording``. Built from a manifest
file by ``manifest.load``; the gateway and the harness use these and never the YAML."""

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
