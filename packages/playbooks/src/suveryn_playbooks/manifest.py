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
- Steps, checkpoints, products, model roles. Deed intake is one ``read`` step and one checkpoint,
  and that is all ``manifest: 1`` describes. The step graph joins as ``manifest: 2`` when the runtime
  does; a manifest names its format version so an old file is read as what it is.

The JSON Schema in ``schema/playbook-manifest.schema.json`` is generated from the model here
(``json_schema``) and kept in sync by a test; editors use it for completion and validation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ._model import Fact, FactKind, Playbook, Wording

MANIFEST_VERSION = 1

_ID = re.compile(r"^playbook/[a-z0-9-]+/[a-z0-9-]+$")
_PACK = re.compile(r"^pack/[a-z0-9-]+$")
_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+$")
_FACT_ID = re.compile(r"^[a-z][a-z0-9_]{0,49}$")   # the UI's vocabulary and the run's JSON key on it
_CASE_TYPE = re.compile(r"^[a-z][a-z0-9-]{0,49}$")


class ManifestError(ValueError):
    """A manifest that can't be loaded: the message names the file and what is wrong with it."""


class FactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_FACT_ID.pattern, description="Stable id; the UI's labels and the run's facts key on it")
    ask: str = Field(min_length=1, max_length=500, description="What the fact is, in the words the model gets (English)")
    kind: FactKind = Field(default="text", description="text, amount or date: decides which checks apply")


class Manifest(BaseModel):
    """The file as written. ``to_playbook`` makes the product's object from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: Literal[1] = Field(description="The manifest format's version; this file describes format 1")
    id: str = Field(pattern=_ID.pattern, description="playbook/<pack>/<name>; never changes once published")
    pack: str = Field(pattern=_PACK.pattern, description="pack/<profession-jurisdiction>")
    version: str = Field(pattern=_VERSION.pattern, description="major.minor, separate from the id")
    name: str = Field(min_length=1, max_length=80, description="In English: the stored result's file name")
    case_types: tuple[str, ...] = Field(min_length=1, description="Which case types the playbook fits")
    facts: tuple[FactSpec, ...] = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=4000, description="What the model is told, before the table")

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
        return v

    def check_consistent(self) -> None:
        """The checks that span fields: the id's pack segment is the pack's."""
        pack = self.pack.removeprefix("pack/")
        if not self.id.startswith(f"playbook/{pack}/"):
            raise ValueError(f"id {self.id!r} does not belong to pack {self.pack!r}")

    @property
    def slug(self) -> str:
        return self.id.rsplit("/", 1)[1]

    def to_playbook(self, text: dict[str, Wording]) -> Playbook:
        facts = tuple(Fact(f.id, f.ask, f.kind) for f in self.facts)
        return Playbook(
            id=self.id,
            pack=self.pack,
            version=self.version,
            name=self.name,
            case_types=self.case_types,
            facts=facts,
            instructions=self.instructions.rstrip("\n") + "\n\n" + table_scaffold(facts),
            text=text,
        )


TABLE_HEADER = "| id | value | source |\n|---|---|---|\n"


def table_scaffold(facts: tuple[Fact, ...]) -> str:
    """The table the model fills in: the header and an empty row per fact, in the playbook's order.
    The harness reads the answer by these rows (``suveryn_harness.facts``); a manifest never writes
    them itself."""
    return TABLE_HEADER + "".join(f"| {f.id} | | |\n" for f in facts)


def parse(source: str, *, where: str = "<manifest>") -> Manifest:
    """The validated manifest from YAML text; ``ManifestError`` says what is wrong and where."""
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as e:
        raise ManifestError(f"{where}: not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: a manifest is a mapping of keys to values, not {type(data).__name__}")
    if data.get("manifest") != MANIFEST_VERSION:
        got = data.get("manifest")
        raise ManifestError(f"{where}: 'manifest' must be {MANIFEST_VERSION} (the format this product reads); got {got!r}")
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
            out[lang] = Wording(entry["title"], entry["summary"], dict(entry["labels"]))
        except (KeyError, TypeError, ValueError) as e:
            raise ManifestError(f"{where}: {f}: no usable entry for {slug!r} ({e})") from None
    return out


def json_schema() -> dict[str, Any]:
    """The manifest format as JSON Schema, for editors (``schema/playbook-manifest.schema.json``)."""
    s = Manifest.model_json_schema()
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    s["$id"] = "https://suveryn.com/schema/playbook-manifest-1.json"
    s["title"] = "Sūveryn playbook manifest"
    s["description"] = "A playbook as a file: identity, case types, facts and instructions (manifest format 1)."
    return s


if __name__ == "__main__":  # python -m suveryn_playbooks.manifest: rewrite the published schema
    import json
    import sys

    out = Path(__file__).parents[2] / "schema" / "playbook-manifest.schema.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out, file=sys.stderr)
