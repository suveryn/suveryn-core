"""The official playbooks: content and identity, no runtime (docs/design/playbooks.md).

A playbook is a fixed list of facts to read from a case's uploaded documents, the instructions the
model gets for it, and its identity: ``id`` (``playbook/<pack>/<name>``), ``pack`` and ``version``.
The identifiers are the platform's (docs/design/platform.md, "Identifiers"): they go into the run
record, every document a playbook produces, and later the registry and the licence, so they are
chosen once and never change. The version is separate from the id: a change that changes results
is a new minor version, a change that makes an old run unreadable a new major one.

Every playbook is a **manifest file** (``manifest.py``): ``<pack>/<name>.yaml`` in this package,
with the pack's wording in ``<pack>/text/<lang>.json`` beside it. ``PLAYBOOKS`` is every manifest
found in the official packs at import; the product's objects are the ``Playbook`` dataclasses the
loader makes, and nothing outside ``manifest.py`` reads YAML. A manifest that doesn't load is an
error at import, not a playbook that silently differs: an official pack ships only manifests that
load, and the test suite loads them all.

``covered(playbook_id)`` is the single place the licence check lands: whether the playbook is
certified and listed in the appliance's manifest (development context §8, suveryn-tracker#35). A
playbook that isn't covered still runs: the licensing model warns and never blocks. Today every
official playbook is covered.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from ._model import LANGUAGES, Fact, FactKind, Playbook, Step, StepKind, Wording
from .manifest import ManifestError, load

OFFICIAL_PACKS = ("be_notary",)   # package directories holding official manifests, in catalogue order


def _official() -> tuple[Playbook, ...]:
    out: list[Playbook] = []
    for pack in OFFICIAL_PACKS:
        pack_dir = Path(str(files(__package__).joinpath(pack)))
        for path in sorted(pack_dir.glob("*.yaml")):
            out.append(load(path))
    ids = [p.id for p in out]
    if len(set(ids)) != len(ids):
        raise ManifestError("two official manifests declare the same id: " + ", ".join(i for i in ids if ids.count(i) > 1))
    return tuple(out)


PLAYBOOKS: tuple[Playbook, ...] = _official()


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


DEED_INTAKE: Playbook = find("playbook/be-notary/deed-intake")  # type: ignore[assignment]  # the first playbook; tests and docs name it
assert DEED_INTAKE is not None, "the official pack be_notary must contain deed-intake.yaml"

__all__ = ["DEED_INTAKE", "LANGUAGES", "OFFICIAL_PACKS", "PLAYBOOKS", "Fact", "FactKind", "ManifestError", "Playbook",
           "Step", "StepKind", "Wording", "by_slug", "covered", "find", "for_case_type", "load"]
