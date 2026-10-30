"""A playbook as the product sees it: ``Playbook``, ``Fact``, ``Wording``. Built from a manifest
file by ``manifest.load``; the gateway and the harness use these and never the YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FactKind = Literal["text", "amount", "date"]
StepKind = Literal["request", "read", "ask", "checkpoint", "produce"]

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
    # The routine's questions (format 2): keyed by step id for a ``request`` and for an ``ask`` step's
    # one template (``{label}`` is the fact's label), or by ``<step id>.<fact id>`` for one fact's own.
    questions: dict[str, str] = field(default_factory=dict)

    def question(self, step_id: str, fact_id: str | None = None) -> str:
        """The words for a step's question, for one fact when ``fact_id`` is given: that fact's own
        text if the pack has one, else the step's template with the fact's label filled in."""
        if fact_id is not None:
            own = self.questions.get(f"{step_id}.{fact_id}")
            if own:
                return own
            return self.questions.get(step_id, "{label}").replace("{label}", self.labels.get(fact_id, fact_id))
        return self.questions.get(step_id, "")


@dataclass(frozen=True)
class Fact:
    """One thing the playbook reads: its id (stable, the UI's vocabulary keys on it), what it is,
    in the words the model gets (English; the model answers in the documents' language), and its kind."""

    id: str
    ask: str
    kind: FactKind = "text"


@dataclass(frozen=True)
class Step:
    """One step of the routine (docs/design/playbooks.md, "The routine"). The runtime in the gateway
    walks the steps; the model is only ever asked inside a ``read``."""

    id: str
    kind: StepKind
    needs: tuple[str, ...] = ()        # steps that must be done first (the manifest's default: the previous one)
    facts: tuple[str, ...] = ()        # read, ask: the fact ids concerned (the manifest's "all" is expanded)
    min: int = 1                       # request: how many uploaded documents the case needs before the step is done
    allow_none: bool = False           # request: a person may say there is no such document
    by: str = "anyone_in_case"         # checkpoint: who may pass it
    template: str = "summary"          # produce: which product


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
    steps: tuple[Step, ...] = ()       # the routine; a format-1 manifest gets the implicit read, checkpoint, produce
    format: int = 1                    # the manifest format the playbook was written in

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def wording(self, language: str) -> Wording:
        """The words in ``language``, else in English."""
        return self.text.get(language) or self.text["en"]

    @property
    def slug(self) -> str:
        """The id's last part: the path segment in the API (``deed-intake``)."""
        return self.id.rsplit("/", 1)[1]
