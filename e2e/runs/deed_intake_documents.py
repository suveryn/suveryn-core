"""The documents of the deed-intake run (deed-intake.json): the fictional trap deed with its planted instruction."""

from pathlib import Path

import trap_deed


def build_documents(folder: Path) -> None:
    trap_deed.build(folder / "akte-testdorp.pdf", injected=True)
