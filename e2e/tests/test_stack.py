"""stack.py's choice of the machine's own PostgreSQL cluster (local mode), without starting anything.

    uv run pytest e2e/tests/test_stack.py
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stack  # noqa: E402


def listing(monkeypatch, text: str | None) -> None:
    def sh(*cmd, check=True, **kw):
        if text is None:
            raise FileNotFoundError(cmd[0])
        return subprocess.CompletedProcess(cmd, 0, text, "")
    monkeypatch.setattr(stack, "sh", sh)


def test_the_round_says_which(monkeypatch):
    monkeypatch.setenv("E2E_PG_VERSION", "18")
    listing(monkeypatch, "16  main 5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/x.log\n")
    assert stack.pg_version() == "18"


def test_the_cluster_on_5432_not_the_first_or_the_newest(monkeypatch):
    """The PostgreSQL project's 19 beside the 16 the tests use, on 5433 (suveryn-tracker#266's review)."""
    monkeypatch.delenv("E2E_PG_VERSION", raising=False)
    listing(monkeypatch, "14  main 5433 online postgres /var/lib/postgresql/14/main /var/log/postgresql/a.log\n"
                         "16  main 5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/b.log\n"
                         "19  main 5434 online postgres /var/lib/postgresql/19/main /var/log/postgresql/c.log\n")
    assert stack.pg_version() == "16"


def test_no_cluster_says_so(monkeypatch):
    monkeypatch.delenv("E2E_PG_VERSION", raising=False)
    for text in ["", None, "18  other 5432 down postgres /x /y\n"]:  # none, no postgresql-common, not "main"
        listing(monkeypatch, text)
        with pytest.raises(SystemExit, match="E2E_PG_VERSION"):
            stack.pg_version()
