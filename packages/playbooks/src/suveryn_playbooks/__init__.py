"""The official playbooks: content and identity, no runtime (docs/design/playbooks.md).

A playbook is a fixed list of facts to read from a case's uploaded documents, the instructions the
model gets for it, and its identity: ``id`` (``playbook/<pack>/<name>``), ``pack`` and ``version``.
The identifiers are the platform's (docs/design/platform.md, "Identifiers"): they go into the run
record, every document a playbook produces, and later the registry and the licence, so they are
chosen once and never change. The version is separate from the id: a change that changes results
is a new minor version, a change that makes an old run unreadable a new major one.

Every playbook is a **manifest file** (``manifest.py``): ``<pack>/<name>.yaml`` in this package for
the official ones (deed intake, the one public reference playbook), or in the packs directory an
appliance has installed (``packs.py``, ``SUVERYN_PACKS_DIR``: the certified content from the private
``suveryn-packs`` repository, company formation first), with the pack's wording in
``<pack>/text/<lang>.json`` beside it. A pack's ``case-types.yaml`` declares the case types it brings
(``CASE_TYPES``). ``PLAYBOOKS`` is every manifest found in both at import; the
product's objects are the ``Playbook`` dataclasses the loader makes, and nothing outside
``manifest.py`` reads YAML. A manifest that doesn't load is an error at import, not a playbook that
silently differs: an official pack ships only manifests that load, and the test suite loads them all.

``covered(playbook_id)`` is the single place the licence check lands: whether the playbook is
certified and listed in the appliance's manifest (development context §8, suveryn-tracker#35). A
playbook that isn't covered still runs: the licensing model warns and never blocks. Today every
official playbook is covered.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from ._model import LANGUAGES, CaseType, Fact, FactKind, LeafKind, Playbook, Step, StepKind, Wording
from .manifest import PACK_FILES, ManifestError, case_types_from_dir, load, read_schema
from .paths import entry, root, split
from .record import from_record, to_record

OFFICIAL_PACKS = ("be_notary",)   # package directories holding official manifests, in catalogue order


def _official() -> tuple[tuple[Playbook, ...], tuple[CaseType, ...]]:
    """The official playbooks and the case types they come with (the reference playbook's: ``sale``)."""
    out: list[Playbook] = []
    types: list[CaseType] = []
    for pack in OFFICIAL_PACKS:
        pack_dir = Path(str(files(__package__).joinpath(pack)))
        for path in sorted(pack_dir.glob("*.yaml")):
            if path.name not in PACK_FILES:
                out.append(load(path))
        types += case_types_from_dir(pack_dir)
    ids = [p.id for p in out]
    if len(set(ids)) != len(ids):
        raise ManifestError("two official manifests declare the same id: " + ", ".join(i for i in ids if ids.count(i) > 1))
    return tuple(out), tuple(types)


def _installed() -> tuple[tuple[Playbook, ...], tuple[CaseType, ...]]:
    """The official playbooks and case types, then the packs' the environment names (``packs.load_dir``,
    ``packs.case_types_dir``); every playbook's case types are declared by one of them (``packs.check``)."""
    from .packs import case_types_dir, check, configured, load_dir
    official, official_types = _official()
    packs_dir = configured()
    playbooks = official + (load_dir(packs_dir, official) if packs_dir is not None else ())
    types = official_types + (case_types_dir(packs_dir, official_types) if packs_dir is not None else ())
    check(playbooks, types)
    return playbooks, types


# Every installed playbook, and every case type an appliance offers: the official ones (core's reference
# content), then the installed packs' (suveryn-tracker#229). A type without a playbook is offered too.
PLAYBOOKS, CASE_TYPES = _installed()


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


def case_type(type_id: str) -> CaseType | None:
    """The installed case type with this id, or None (a type a stored case kept after its pack went)."""
    return next((t for t in CASE_TYPES if t.id == type_id), None)


DEED_INTAKE: Playbook = find("playbook/be-notary/deed-intake")  # type: ignore[assignment]  # the first playbook; tests and docs name it
assert DEED_INTAKE is not None, "the official pack be_notary must contain deed-intake.yaml"

__all__ = ["CASE_TYPES", "DEED_INTAKE", "LANGUAGES", "OFFICIAL_PACKS", "PLAYBOOKS", "CaseType", "Fact", "FactKind", "LeafKind", "ManifestError", "Playbook",
           "Step", "StepKind", "Wording", "by_slug", "case_type", "covered", "entry", "find", "for_case_type", "from_record", "load",
           "read_schema", "root", "split", "to_record"]
