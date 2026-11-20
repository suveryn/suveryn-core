"""Packs from a directory (docs/design/playbooks.md, "Where playbooks live"): the certified pack
content an appliance has installed, loaded beside the official playbooks built into this package.

Core keeps one public reference playbook, deed intake. Certified content (``pack/be-notary`` and the
packs after it) lives in the private ``suveryn-packs`` repository and reaches an appliance as a signed
bundle, by the same path as the models, into a directory this module reads: one folder per pack,
named as the pack's id segment (``be-notary/`` for ``pack/be-notary``), holding the manifests and the
pack's words::

    <packs dir>/be-notary/company-formation.yaml
    <packs dir>/be-notary/text/{en,nl,fr}.json

``SUVERYN_PACKS_DIR`` names the directory; unset or missing, there are no packs beyond the official
ones. Every manifest is validated as an official one is, and an id that is already official or in
another pack is refused: an appliance never has two playbooks under one id. A pack that doesn't load
is an error at import, as an official one would be: the signed bundle ships only manifests that load.

``python -m suveryn_playbooks <dir>`` checks a directory and prints what it holds (``__main__.py``);
the packs repository's CI runs it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ._model import CaseType, Playbook
from .manifest import PACK_FILES, ManifestError, case_types_from_dir, load

ENV = "SUVERYN_PACKS_DIR"


def load_dir(path: Path, taken: tuple[Playbook, ...] = ()) -> tuple[Playbook, ...]:
    """Every playbook in the packs under ``path``, in folder and file order. ``taken``: playbooks whose ids
    the directory may not repeat (the official ones). ``ManifestError`` names the file and what is wrong."""
    out: list[Playbook] = []
    ids = {p.id: "the official playbooks" for p in taken}
    if not path.is_dir():
        raise ManifestError(f"{path}: not a directory of packs")
    for pack_dir in sorted(d for d in path.iterdir() if d.is_dir() and not d.name.startswith(".")):
        manifests = sorted(p for p in pack_dir.glob("*.yaml") if p.name not in PACK_FILES)
        if not manifests:
            continue
        for m in manifests:
            p = load(m)
            if p.pack != f"pack/{pack_dir.name}":
                raise ManifestError(f"{m}: pack {p.pack!r} in folder {pack_dir.name!r}; a pack's folder is named as its id (pack/<folder>)")
            if p.id in ids:
                raise ManifestError(f"{m}: id {p.id!r} is already one of {ids[p.id]}")
            ids[p.id] = f"pack folder {pack_dir.name!r}"
            out.append(p)
    return tuple(out)


def case_types_dir(path: Path, taken: tuple[CaseType, ...] = ()) -> tuple[CaseType, ...]:
    """The case types the packs under ``path`` declare (each pack's ``case-types.yaml``), in folder order.
    ``taken``: types the directory may not declare again (the official ones): a type has one source."""
    out: list[CaseType] = []
    by = {t.id: "the official case types" for t in taken}
    for pack_dir in sorted(d for d in path.iterdir() if d.is_dir() and not d.name.startswith(".")):
        for t in case_types_from_dir(pack_dir):
            if t.pack != f"pack/{pack_dir.name}":
                raise ManifestError(f"{pack_dir}: case types of {t.pack!r} in folder {pack_dir.name!r}; a pack's folder is named as its id")
            if t.id in by:
                raise ManifestError(f"{pack_dir}: case type {t.id!r} is already declared by {by[t.id]}")
            by[t.id] = f"pack folder {pack_dir.name!r}"
            out.append(t)
    return tuple(out)


def check(playbooks: tuple[Playbook, ...], types: tuple[CaseType, ...]) -> None:
    """Every case type a playbook fits is declared by an installed source; ``ManifestError`` names the first that isn't."""
    known = {t.id for t in types}
    for p in playbooks:
        for t in p.case_types:
            if t not in known:
                raise ManifestError(f"{p.id}: case type {t!r} is declared by no installed pack (case-types.yaml)")


def configured() -> Path | None:
    """The packs directory the environment names, or None."""
    value = os.environ.get(ENV, "").strip()
    return Path(value) if value else None


def main(argv: list[str], official: tuple[Playbook, ...], official_types: tuple[CaseType, ...] = ()) -> int:
    if len(argv) != 1:
        print("usage: python -m suveryn_playbooks <packs directory>", file=sys.stderr)
        return 2
    try:
        found = load_dir(Path(argv[0]), official)
        types = case_types_dir(Path(argv[0]), official_types)
        check(found, official_types + types)
    except ManifestError as e:
        print(e, file=sys.stderr)
        return 1
    for p in found:
        kinds = ", ".join(f"{s.kind}" for s in p.steps)
        print(f"{p.id} {p.version}: {len(p.facts)} facts, steps {kinds}; words in {', '.join(sorted(p.text))}")
    print(f"{len(found)} playbook(s) load; case types: {', '.join(t.id for t in types) or 'none'}")
    return 0

