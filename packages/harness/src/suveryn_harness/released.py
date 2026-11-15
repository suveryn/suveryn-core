"""The released codes: never renamed, never removed (docs/design/names.md, *Released*).

A code is stored: with a document that couldn't be read, with a run that failed. An old case, and an older backup
that is restored, must still be read by a newer sūveryn, so a code that has left Sūveryn Labs stays in the
registry under its name for good. ``messages-released.json`` lists those codes, and a test fails when one of them
is no longer in the registry (``tests/test_messages.py``).

A core is released when an appliance that leaves Sūveryn Labs pins it, a pilot included. In the change in core that
is to be pinned:

    uv run python -m suveryn_harness.released     # adds every code of the registry to the list

Standard library only, like ``messages.py``.
"""

import json
import sys
from pathlib import Path

FILE = Path(__file__).with_name("messages-released.json")
REGISTRY = Path(__file__).with_name("messages.json")


def released() -> list[str]:
    return json.loads(FILE.read_text(encoding="utf-8"))["codes"]


def release() -> int:
    """Add every code of the registry to the list: added to, never taken from. How many are on it then."""
    listed = json.loads(FILE.read_text(encoding="utf-8"))
    listed["codes"] = sorted(set(listed["codes"]) | set(json.loads(REGISTRY.read_text(encoding="utf-8"))["codes"]))
    FILE.write_text(json.dumps(listed, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(listed["codes"])


if __name__ == "__main__":
    if sys.argv[1:]:
        sys.exit("usage: python -m suveryn_harness.released   (it takes no arguments)")
    print(f"{release()} released codes in {FILE.name}")
