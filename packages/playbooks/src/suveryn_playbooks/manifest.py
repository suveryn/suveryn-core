"""The playbook manifest: a playbook as a file (docs/design/playbooks.md, "The manifest").

A manifest is a YAML document that says what a playbook is: its identity, the case types it fits,
the facts it reads and the instructions the model gets. ``load`` turns one into a ``Playbook``;
nothing else in the product reads YAML. The point of the file form is that a playbook can be
picked up and moved: signed into a pack bundle, uploaded to an appliance by its administrator,
written by an office for itself, shown in full to a reviewer. Code can't be any of that.

The format is validated strictly (unknown keys are errors), because the people writing manifests
by hand are administrators, not developers, and a misspelt key that is silently ignored is a
playbook that quietly does something else. Every error names the file and the field.

What the manifest does *not* carry, on purpose:

- The table the model is asked to fill. That is the harness's contract with the model (``facts.py``
  reads it), not content; the loader appends it to the instructions (``table_scaffold``). A manifest
  author writes what the playbook is for; how the answer is shaped is the runtime's business.
- The wording per language. It stays in the pack's ``text/<lang>.json`` next to the manifest, one
  file per language for the whole pack (docs/translations.md); the loader looks it up by the
  manifest's slug. Whether an office's own playbook may carry its wording inline is open
  (docs/design/playbooks.md, "Open").
- Products beyond the summary, model roles, conditions. Those join with later formats; a manifest
  names its format version so an old file is read as what it is.

Two formats load: ``manifest: 2``, identity, facts, instructions and ``steps``, the routine itself
(format 1, without steps, was retired before any was published; review pass 8), and ``manifest: 3``,
format 2 plus two kinds of fact: ``number`` (a figure without currency) and ``list`` (several entries,
each a record of plain-valued ``of`` fields, or one plain value of kind ``of``; see ``paths``). A
format-2 file loads unchanged; a format-2 file that uses a format-3 kind is refused with the fact
named, so a file says what it needs. A ``read`` step's answer is JSON of the facts' shape
(``read_schema``), which the model server holds the model to by grammar; the loader appends that shape
in words to the instructions (``answer_scaffold``). ``request`` a
document, ``read`` facts from the documents, ``ask`` about the facts not found, a ``checkpoint`` where
a person confirms, ``produce`` the summary. Each step says what it ``needs`` (by default the step
before it). The questions a ``request`` or ``ask`` step puts to people are the pack's wording
(``text/<lang>.json``, ``questions``), keyed by step id, so they are reviewed and translated like the
labels; the model never words them. ``validate_steps`` checks the graph: ids unique, needs resolve,
no cycles, a checkpoint before any produce, an ask only about facts a read before it reads.

The JSON Schema in ``schema/playbook-manifest.schema.json`` is generated from the model here
(``json_schema``) and kept in sync by a test; editors use it for completion and validation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ._model import Fact, FactKind, LeafKind, Playbook, Step, StepKind, Wording
from .paths import MAX_ENTRIES

MANIFEST_VERSIONS = (2, 3)
FORMAT_3_KINDS = ("number", "list")
_STEP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")

_ID = re.compile(r"^playbook/[a-z0-9-]+/[a-z0-9-]+$")
_PACK = re.compile(r"^pack/[a-z0-9-]+$")
_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+$")
_FACT_ID = re.compile(r"^[a-z][a-z0-9_]{0,49}$")   # the UI's vocabulary and the run's JSON key on it
_CASE_TYPE = re.compile(r"^[a-z][a-z0-9-]{0,49}$")


class ManifestError(ValueError):
    """A manifest that can't be loaded: the message names the file and what is wrong with it."""


class FieldSpec(BaseModel):
    """One field of a list's entries (format 3): a plain-valued fact inside the record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_FACT_ID.pattern, description="Stable within the list; labelled as <list id>.<field id>")
    ask: str = Field(min_length=1, max_length=500, description="What the field is, in the words the model gets (English)")
    kind: LeafKind = Field(default="text", description="text, amount, date or number: decides which checks apply")


class FactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_FACT_ID.pattern, description="Stable id; the UI's labels and the run's facts key on it")
    ask: str = Field(min_length=1, max_length=500, description="What the fact is, in the words the model gets (English)")
    kind: FactKind = Field(default="text", description="text, amount, date or number: decides which checks apply; list (format 3): several entries")
    of: tuple[FieldSpec, ...] | LeafKind | None = Field(default=None, description="list only: the entries' fields (a record each), or the kind of each entry's one value")

    @field_validator("of")
    @classmethod
    def _of(cls, v):
        if isinstance(v, tuple):
            if not v:
                raise ValueError("a list of records needs at least one field")
            if len(v) > 20:
                raise ValueError("at most 20 fields per entry")
            ids = [f.id for f in v]
            if len(set(ids)) != len(ids):
                raise ValueError("field " + ", ".join(sorted({i for i in ids if ids.count(i) > 1})) + " is listed twice")
        return v

    def check_kind(self) -> None:
        if self.kind == "list" and self.of is None:
            raise ValueError(f"fact {self.id!r}: kind list needs 'of' (the entries' fields, or the kind of each entry's value)")
        if self.kind != "list" and self.of is not None:
            raise ValueError(f"fact {self.id!r}: 'of' only applies to kind list")


class StepSpec(BaseModel):
    """One step as written (format 2). Which fields apply depends on ``kind``; the others are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_STEP_ID.pattern, description="Stable within the playbook; the run records progress by it")
    kind: StepKind
    needs: tuple[str, ...] | None = Field(default=None, description="Steps done before this one; default: the previous step")
    facts: tuple[str, ...] | Literal["all"] | None = Field(default=None, description="read, ask: which facts; \"all\" for every fact")
    min: int | None = Field(default=None, ge=1, le=50, description="request: uploaded documents needed (default 1)")
    allow_none: bool | None = Field(default=None, description="request: a person may answer that there is no such document")
    expects: str | None = Field(default=None, pattern=_FACT_ID.pattern, description="request: a name for what is asked, so a read can aim at it")
    documents: tuple[str, ...] | None = Field(default=None, description="read: the names (expects) of the requests whose documents it reads; absent: every document")
    by: Literal["anyone_in_case"] | None = Field(default=None, description="checkpoint: who may pass it")
    template: Literal["summary"] | None = Field(default=None, description="produce: the product (only the summary today)")

    _ALLOWED: ClassVar[dict[str, frozenset[str]]] = {
        "request": frozenset({"min", "allow_none", "expects"}),
        "read": frozenset({"facts", "documents"}),
        "ask": frozenset({"facts"}),
        "checkpoint": frozenset({"by"}),
        "produce": frozenset({"template"}),
    }

    def check_fields(self) -> None:
        given = {k for k in ("facts", "min", "allow_none", "by", "template", "expects", "documents") if getattr(self, k) is not None}
        wrong = given - self._ALLOWED[self.kind]
        if wrong:
            raise ValueError(f"step {self.id!r} ({self.kind}): {', '.join(sorted(wrong))} does not apply to this kind")
        if self.kind in ("read", "ask") and self.facts is None:
            raise ValueError(f"step {self.id!r} ({self.kind}): facts is required (a list of fact ids, or \"all\")")


class Manifest(BaseModel):
    """The file as written. ``to_playbook`` makes the product's object from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: Literal[2, 3] = Field(description="The manifest format's version: 2 (facts, instructions and steps) or 3 (number and list facts too)")
    id: str = Field(pattern=_ID.pattern, description="playbook/<pack>/<name>; never changes once published")
    pack: str = Field(pattern=_PACK.pattern, description="pack/<profession-jurisdiction>")
    version: str = Field(pattern=_VERSION.pattern, description="major.minor, separate from the id")
    name: str = Field(min_length=1, max_length=80, description="In English: the stored result's file name")
    case_types: tuple[str, ...] = Field(min_length=1, description="Which case types the playbook fits")
    facts: tuple[FactSpec, ...] = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=4000, description="What the model is told, before the table")
    steps: tuple[StepSpec, ...] = Field(min_length=1, max_length=50, description="The routine")

    @field_validator("case_types")
    @classmethod
    def _case_types(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for t in v:
            if not _CASE_TYPE.match(t):
                raise ValueError(f"case type {t!r}: lower-case letters, digits and hyphens")
        if len(set(v)) != len(v):
            raise ValueError("a case type is listed twice")
        return v

    @field_validator("facts")
    @classmethod
    def _facts(cls, v: tuple[FactSpec, ...]) -> tuple[FactSpec, ...]:
        seen: set[str] = set()
        for f in v:
            if f.id in seen:
                raise ValueError(f"fact {f.id!r} is listed twice")
            seen.add(f.id)
            f.check_kind()
        return v

    def check_consistent(self) -> None:
        """The checks that span fields: the id's pack segment is the pack's, and the steps a valid graph."""
        pack = self.pack.removeprefix("pack/")
        if not self.id.startswith(f"playbook/{pack}/"):
            raise ValueError(f"id {self.id!r} does not belong to pack {self.pack!r}")
        if self.manifest < 3:
            for f in self.facts:
                if f.kind in FORMAT_3_KINDS:
                    raise ValueError(f"fact {f.id!r}: kind {f.kind} needs manifest: 3")
        validate_steps(self.resolved_steps(), {f.id for f in self.facts})

    def resolved_steps(self) -> tuple[Step, ...]:
        """The steps as the runtime sees them: defaults filled in, "all" expanded, ``needs`` defaulting
        to the step before."""
        out: list[Step] = []
        previous: str | None = None
        for sp in self.steps:
            sp.check_fields()
            facts = tuple(f.id for f in self.facts) if sp.facts == "all" else tuple(sp.facts or ())
            needs = sp.needs if sp.needs is not None else ((previous,) if previous else ())
            out.append(Step(id=sp.id, kind=sp.kind, needs=tuple(needs), facts=facts, min=sp.min or 1,
                            allow_none=bool(sp.allow_none), by=sp.by or "anyone_in_case", template=sp.template or "summary",
                            expects=sp.expects or "", documents=tuple(sp.documents or ())))
            previous = sp.id
        return tuple(out)

    @property
    def slug(self) -> str:
        return self.id.rsplit("/", 1)[1]

    def to_playbook(self, text: dict[str, Wording]) -> Playbook:
        facts = tuple(_fact(f) for f in self.facts)
        return Playbook(
            id=self.id,
            pack=self.pack,
            version=self.version,
            name=self.name,
            case_types=self.case_types,
            facts=facts,
            instructions=self.instructions.rstrip("\n") + "\n\n" + answer_scaffold(facts),
            text=text,
            steps=self.resolved_steps(),
            format=self.manifest,
        )


def _fact(f: FactSpec) -> Fact:
    if f.kind != "list":
        return Fact(f.id, f.ask, f.kind)
    if isinstance(f.of, tuple):
        return Fact(f.id, f.ask, "list", fields=tuple(Fact(x.id, x.ask, x.kind) for x in f.of))
    return Fact(f.id, f.ask, "list", item_kind=f.of or "text")


# ------------------------------------------------------------------ the answer's shape

# One value as the model gives it: as written in the documents (or null: not there), and the excerpts it
# comes from. Strings always; the harness reads them by kind.
LEAF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"value": {"type": ["string", "null"], "maxLength": 2000},
                   "sources": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 99}, "maxItems": 8}},
    "required": ["value", "sources"],
    "additionalProperties": False,
}


def _fact_schema(f: Fact) -> dict[str, Any]:
    if f.kind != "list":
        return LEAF_SCHEMA
    if f.fields:
        item: dict[str, Any] = {"type": "object", "properties": {x.id: LEAF_SCHEMA for x in f.fields},
                                "required": [x.id for x in f.fields], "additionalProperties": False}
    else:
        item = LEAF_SCHEMA
    return {"type": "array", "items": item, "maxItems": MAX_ENTRIES}


def read_schema(facts: tuple[Fact, ...]) -> dict[str, Any]:
    """The JSON Schema of a read step's answer, the shape the model server holds the model to: one key
    per fact, in the playbook's order; a plain fact is ``{"value": "as written" | null, "sources": [n, …]}``;
    a list is an array of entries, each a record of its fields' values, or one value. A manifest never
    writes this itself; the harness reads the answer by it (``suveryn_harness.facts``)."""
    return {"type": "object", "properties": {f.id: _fact_schema(f) for f in facts},
            "required": [f.id for f in facts], "additionalProperties": False}


def _leaf_words(f: Fact) -> str:
    return f'{{"value": <{f.ask}; copied as written, or null>, "sources": [<excerpt numbers>]}}'


def answer_scaffold(facts: tuple[Fact, ...]) -> str:
    """The answer's shape in words, appended to the instructions so the model sees what is asked of
    it: one line per fact, a list with one entry spelled out. What the server enforces is ``read_schema``."""
    lines = ["Answer with one JSON object of exactly this shape and nothing else:", "{"]
    for i, f in enumerate(facts):
        comma = "," if i < len(facts) - 1 else ""
        if f.kind != "list":
            lines.append(f'  "{f.id}": {_leaf_words(f)}{comma}')
        elif f.fields:
            lines.append(f'  "{f.id}": [')
            lines.append("    {")
            for j, x in enumerate(f.fields):
                lines.append(f'      "{x.id}": {_leaf_words(x)}{"," if j < len(f.fields) - 1 else ""}')
            lines.append("    }")
            lines.append(f"  ]{comma}")
        else:
            lines.append(f'  "{f.id}": [ {_leaf_words(f)} ]{comma}')
    lines.append("}")
    lists = [f for f in facts if f.kind == "list"]
    if lists:
        lines.append("A list (" + ", ".join(f.id for f in lists) + ") has one entry per item the documents name, in the order "
                     "the documents give them, and is [] when they name none.")
    lines.append('A fact the excerpts do not contain gets "value": null and "sources": []. Every value is a string copied '
                 "as the documents write it; never a number or a date in another form.")
    return "\n".join(lines)


def validate_steps(steps: tuple[Step, ...], fact_ids: set[str]) -> None:
    """The graph rules. ``ValueError`` names the step."""
    ids = [s.id for s in steps]
    if len(set(ids)) != len(ids):
        raise ValueError("steps: " + ", ".join(sorted({i for i in ids if ids.count(i) > 1})) + " listed twice")
    by_id = {s.id: s for s in steps}
    for s in steps:
        for n in s.needs:
            if n not in by_id:
                raise ValueError(f"step {s.id!r}: needs {n!r}, which is not a step")
            if n == s.id:
                raise ValueError(f"step {s.id!r}: needs itself")
        for f in s.facts:
            if f not in fact_ids:
                raise ValueError(f"step {s.id!r}: fact {f!r} is not one of the playbook's facts")
    # no cycles: every step reachable in dependency order
    done: set[str] = set()
    remaining = list(steps)
    while remaining:
        ready = [s for s in remaining if all(n in done for n in s.needs)]
        if not ready:
            raise ValueError("steps: " + ", ".join(s.id for s in remaining) + " depend on each other in a circle")
        done.update(s.id for s in ready)
        remaining = [s for s in remaining if s.id not in done]

    def before(s: Step) -> set[str]:
        seen: set[str] = set()
        todo = list(s.needs)
        while todo:
            n = todo.pop()
            if n not in seen:
                seen.add(n)
                todo.extend(by_id[n].needs)
        return seen

    checkpoints = [s for s in steps if s.kind == "checkpoint"]
    if not checkpoints:
        raise ValueError("steps: a routine needs a checkpoint where a person confirms the facts")
    expects = [s.expects for s in steps if s.kind == "request" and s.expects]
    if len(set(expects)) != len(expects):
        raise ValueError("steps: " + ", ".join(sorted({e for e in expects if expects.count(e) > 1})) + " is expected by two requests")
    read_by: dict[str, str] = {}
    for s in steps:
        if s.kind == "read":
            for f in s.facts:
                if f in read_by:
                    raise ValueError(f"step {s.id!r} (read): fact {f!r} is already read by step {read_by[f]!r}; a fact is read once")
                read_by[f] = s.id
    for s in steps:
        earlier = before(s)
        if s.kind == "produce" and not any(by_id[e].kind == "checkpoint" for e in earlier):
            raise ValueError(f"step {s.id!r} (produce): nothing is produced before a checkpoint; it needs one")
        if s.kind == "ask":
            read_facts = {f for e in earlier if by_id[e].kind == "read" for f in by_id[e].facts}
            missing = [f for f in s.facts if f not in read_facts]
            if missing:
                raise ValueError(f"step {s.id!r} (ask): asks about {', '.join(missing)} before any read step it needs reads them")
        if s.kind == "checkpoint" and not any(by_id[e].kind in ("read", "ask") for e in earlier):
            raise ValueError(f"step {s.id!r} (checkpoint): nothing to confirm; it needs a read or ask step")
        if s.kind == "read" and s.documents:
            asked = {by_id[e].expects for e in earlier if by_id[e].kind == "request" and by_id[e].expects}
            unknown = [d for d in s.documents if d not in asked]
            if unknown:
                raise ValueError(f"step {s.id!r} (read): reads {', '.join(unknown)}, which no request step it needs expects")


def parse(source: str, *, where: str = "<manifest>") -> Manifest:
    """The validated manifest from YAML text; ``ManifestError`` says what is wrong and where."""
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as e:
        raise ManifestError(f"{where}: not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: a manifest is a mapping of keys to values, not {type(data).__name__}")
    if data.get("manifest") not in MANIFEST_VERSIONS:
        got = data.get("manifest")
        raise ManifestError(f"{where}: 'manifest' must be {' or '.join(map(str, MANIFEST_VERSIONS))} (the format this product reads); got {got!r}")
    try:
        m = Manifest.model_validate(data)
        m.check_consistent()
    except ValidationError as e:
        lines = [f"{where}: {len(e.errors())} problem(s):"]
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(document)"
            lines.append(f"  {loc}: {err['msg']}")
        raise ManifestError("\n".join(lines)) from None
    except ValueError as e:
        raise ManifestError(f"{where}: {e}") from None
    return m


def load(path: Path, text: dict[str, Wording] | None = None) -> Playbook:
    """The playbook in a manifest file. ``text``: its wording per language; when None, from the
    pack's ``text/<lang>.json`` next to the file (``pack_text_from_dir``)."""
    m = parse(path.read_text(encoding="utf-8"), where=str(path))
    if text is None:
        text = pack_text_from_dir(path.parent, m.slug, where=str(path))
    return m.to_playbook(text)


def pack_text_from_dir(pack_dir: Path, slug: str, *, where: str) -> dict[str, Wording]:
    """A playbook's words in every language, from ``<pack_dir>/text/<lang>.json`` (docs/translations.md)."""
    import json

    from ._model import LANGUAGES

    out: dict[str, Wording] = {}
    for lang in LANGUAGES:
        f = pack_dir / "text" / f"{lang}.json"
        if not f.is_file():
            raise ManifestError(f"{where}: no wording for {lang}: {f} is missing")
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))[slug]
            out[lang] = Wording(entry["title"], entry["summary"], dict(entry["labels"]), dict(entry.get("questions", {})),
                                entry.get("factsTitle", ""))
        except (KeyError, TypeError, ValueError) as e:
            raise ManifestError(f"{where}: {f}: no usable entry for {slug!r} ({e})") from None
    return out


def json_schema() -> dict[str, Any]:
    """The manifest format as JSON Schema, for editors (``schema/playbook-manifest.schema.json``)."""
    s = Manifest.model_json_schema()
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    s["$id"] = "https://suveryn.com/schema/playbook-manifest.json"
    s["title"] = "Sūveryn playbook manifest"
    s["description"] = "A playbook as a file: identity, case types, facts, instructions and, in format 2, the routine's steps."
    return s


if __name__ == "__main__":  # python -m suveryn_playbooks.manifest: rewrite the published schema
    import json
    import sys

    out = Path(__file__).parents[2] / "schema" / "playbook-manifest.schema.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out, file=sys.stderr)
