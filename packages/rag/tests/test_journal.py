"""After a deletion the WAL holding the deleted text is let go (VM regression 03c8f74, finding 3). Against a real
PostgreSQL, skipped unless SUVERYN_TEST_DATABASE_URL is set."""

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
from suveryn_rag.journal import flush_journal  # noqa: E402

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


def _wal_file() -> str:
    with psycopg.connect(URL, autocommit=True) as c:
        return c.execute("SELECT pg_walfile_name(pg_current_wal_lsn())").fetchone()[0]


def test_the_flush_closes_the_wal_file_the_deletion_was_written_to():
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS journal_probe (t text)")
        c.execute("INSERT INTO journal_probe VALUES ('kwartelkoning'); DELETE FROM journal_probe")
    before = _wal_file()
    assert flush_journal(URL)
    assert _wal_file() != before  # a new file: the old one is no longer needed after the checkpoint


def test_without_the_rights_it_says_so_and_raises_nothing():
    role = f"nopriv_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'x'")
    try:
        url = psycopg.conninfo.make_conninfo(URL, user=role, password="x")
        assert flush_journal(url) is False
        assert flush_journal("postgresql://nobody@/nothing?host=/nonexistent&port=1") is False  # down
    finally:
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP ROLE {role}")


def test_with_the_appliances_grants_it_works():
    """What suveryn-appliance's provisioning grants the database role: pg_checkpoint and pg_switch_wal()."""
    role = f"granted_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'x'")
        c.execute(f"GRANT pg_checkpoint TO {role}")
        c.execute(f"GRANT EXECUTE ON FUNCTION pg_switch_wal() TO {role}")
    try:
        assert flush_journal(psycopg.conninfo.make_conninfo(URL, user=role, password="x"))
    finally:
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"REVOKE pg_checkpoint FROM {role}; REVOKE EXECUTE ON FUNCTION pg_switch_wal() FROM {role}; DROP ROLE {role}")
