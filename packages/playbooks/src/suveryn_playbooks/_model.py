"""A playbook as the product sees it: ``Playbook``, ``Fact``, ``Wording``. Built from a manifest
file by ``manifest.load``; the gateway and the harness use these and never the YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# What one value is: ``text``, an ``amount`` (money), a ``date`` or a ``number`` (a count, a share, a
# percentage: a figure without currency). ``list`` (format 3) is a fact that holds several entries,
# each a record of plain-valued fields or one plain value; its leaves are the entries' values.
# ``choice`` (format 3, "Choices"): one of a few named options (``Fact.options``), read by the model
# when the documents say it and otherwise asked; what a step's ``when`` turns on.
LeafKind = Literal["text", "amount", "date", "number", "choice"]
FactKind = Literal["text", "amount", "date", "number", "choice", "list"]
StepKind = Literal["request", "read", "ask", "checkpoint", "produce", "check"]

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
    # The routine's questions: keyed by step id for a ``request`` and for an ``ask`` step's
    # one template (``{label}`` is the fact's label), or by ``<step id>.<fact id>`` for one fact's own.
    questions: dict[str, str] = field(default_factory=dict)
    # A sentence per check step (format 3): what the check says when it holds ("The founders' shares add up
    # to the shares issued"); shown with its result at the checkpoint and in the summary.
    checks: dict[str, str] = field(default_factory=dict)
    # A name per step, for the line that says a step was skipped ("Bank certificate: not needed, …"); a step
    # without one is named by its id.
    steps: dict[str, str] = field(default_factory=dict)
    # The heading of the facts panel beside the run's conversation ("Facts for the deed"); empty: the
    # UI's generic "Facts" (docs/design/playbooks.md, "The chat UI").
    facts_title: str = ""

    def label(self, path: str) -> str:
        """The words for a fact or one of a list's leaves: ``price`` -> "Price"; ``founders[2].name`` ->
        "Founder(s) 2 · Name" (the list's label, the entry's number, the field's label from
        ``labels["founders.name"]``); ``conditions[1]`` -> "Conditions 1". An unknown id is shown as is."""
        from .paths import split
        root, index, field_id = split(path)
        if root is None:
            return self.labels.get(path, path)
        head = self.labels.get(root, root)
        if index is None:
            return head
        head = f"{head} {index}"
        if field_id is None:
            return head
        return f"{head} · {self.labels.get(f'{root}.{field_id}', field_id)}"

    def option(self, fact_id: str, option: str) -> str:
        """The words for a choice's option: ``labels["contribution_kind.cash"]``, else the option id."""
        return self.labels.get(f"{fact_id}.{option}", option)

    def step(self, step_id: str) -> str:
        return self.steps.get(step_id, step_id)

    def question(self, step_id: str, fact_id: str | None = None) -> str:
        """The words for a step's question, for one fact when ``fact_id`` is given: that fact's own
        text if the pack has one, else the step's template with the fact's label filled in."""
        if fact_id is not None:
            own = self.questions.get(f"{step_id}.{fact_id}")
            if own:
                return own
            return self.questions.get(step_id, "{label}").replace("{label}", self.label(fact_id))
        return self.questions.get(step_id, "")


@dataclass(frozen=True)
class Fact:
    """One thing the playbook reads: its id (stable, the UI's vocabulary keys on it), what it is,
    in the words the model gets (English; the model answers in the documents' language), and its kind."""

    id: str
    ask: str
    kind: FactKind = "text"
    # A list's entries (format 3): records of these fields (each a plain-valued Fact), or, with no fields,
    # one plain value of ``item_kind`` per entry. A list's leaves are addressed by path: ``founders[1].name``,
    # ``conditions[2]`` (``paths``); its own id names the list as a whole.
    fields: tuple[Fact, ...] = ()
    item_kind: LeafKind = "text"
    # choice: the option ids (``cash``, ``in_kind``); their words per language are ``labels["<fact>.<option>"]``
    options: tuple[str, ...] = ()
    # date: the date fact a term written instead of a date counts from ("four months after the signing":
    # ``agreement_date``); the harness works the date out (``suveryn_harness.terms``) and a person checks it
    counts_from: str = ""

    @property
    def leaf_kind(self) -> LeafKind:
        """The kind of one value of this fact: its own, or an entry's for a list of plain values."""
        return self.item_kind if self.kind == "list" else self.kind  # type: ignore[return-value]

    def field(self, field_id: str) -> Fact | None:
        return next((f for f in self.fields if f.id == field_id), None)


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
    expects: str = ""                  # request: a name for what is asked (``bank_certificate``), so a read can aim at it
    rule: str = ""                     # check: the comparison, as written (``rules.parse_rule`` reads it)
    when: str = ""                     # any step: runs only when a choice fact has (or hasn't) an option (``conditions.parse_when``); else skipped
    documents: tuple[str, ...] = ()    # read: the names (``expects``) of the requests whose documents it reads; empty: every document
    by: str = "anyone_in_case"         # checkpoint: who may pass it: anyone_in_case, or manager (the case's manager, the notary; the case's roles, no other)
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
    steps: tuple[Step, ...] = ()       # the routine
    format: int = 3                    # the manifest format the playbook was written in

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def fact(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fact_id), None)

    def leaf(self, path: str) -> Fact | None:
        """The fact a path names a value of: the fact itself (``price``; a list's whole, ``founders``), a
        list's field (``founders[1].name`` -> the ``name`` field) or a list of plain values' entry
        (``conditions[2]`` -> the list, whose ``item_kind`` is the value's). None: no such fact, field or shape."""
        from .paths import split
        root, index, field_id = split(path)
        f = self.fact(root) if root else None
        if f is None:
            return None
        if index is None:
            return f if field_id is None else None
        if f.kind != "list":
            return None
        if field_id is None:
            return f if not f.fields else None
        return f.field(field_id) if f.fields else None

    def leaf_kind(self, path: str) -> LeafKind:
        """The kind of the value a path names; ``text`` for a path that names nothing."""
        f = self.leaf(path)
        return f.leaf_kind if f is not None else "text"

    def wording(self, language: str) -> Wording:
        """The words in ``language``, else in English."""
        return self.text.get(language) or self.text["en"]

    @property
    def slug(self) -> str:
        """The id's last part: the path segment in the API (``deed-intake``)."""
        return self.id.rsplit("/", 1)[1]
