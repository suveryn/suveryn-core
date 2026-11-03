"""Shared by every package's tests: the fictional test pack is installed as an appliance installs a pack
(``suveryn_playbooks.packs``, ``SUVERYN_PACKS_DIR``), before any test imports ``suveryn_playbooks``."""

import os
from pathlib import Path

os.environ.setdefault("SUVERYN_PACKS_DIR", str(Path(__file__).parent / "packages" / "playbooks" / "tests" / "fixtures" / "packs"))
