"""After a deletion the WAL holding the deleted text is let go (VM regression 03c8f74, finding 3). Against a real
PostgreSQL, skipped unless SUVERYN_TEST_DATABASE_URL is set.

The test role needs more than the other tests' (VM regression 9c97d76, finding 8): to checkpoint and switch the WAL
(a superuser, or ``pg_checkpoint`` and EXECUTE on ``pg_switch_wal()``), and for the two tests that make roles,
CREATEROLE with ``pg_checkpoint`` WITH ADMIN OPTION and ``pg_switch_wal()`` WITH GRANT OPTION. A superuser has all of
it. Each test without its rights is skipped and says which it lacks."""

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
from suveryn_rag.journal import flush_journal  # noqa: E402

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


def _rights() -> dict[str, bool]:
    if not URL:
        return {}
    try:
        return _read_rights()
    except psycopg.Error:
        return {}  # the database can't be reached: each test is skipped with its reason


def _read_rights() -> dict[str, bool]:
    with psycopg.connect(URL, autocommit=True) as c:
        su, createrole = c.execute("SELECT rolsuper, rolcreaterole FROM pg_roles WHERE rolname = current_user").fetchone()
        flush = su or c.execute("SELECT pg_has_role(current_user, 'pg_checkpoint', 'member')"
                                " AND has_function_privilege('pg_switch_wal()', 'execute')").fetchone()[0]
        grant = su or (createrole and c.execute(
            "SELECT pg_has_role(current_user, 'pg_checkpoint', 'usage WITH ADMIN OPTION')"
            " AND has_function_privilege('pg_switch_wal()', 'execute WITH GRANT OPTION')").fetchone()[0])
    return {"flush": bool(flush), "roles": bool(su or createrole), "grant": bool(grant)}


RIGHTS = _rights()
can_flush = pytest.mark.skipif(not RIGHTS.get("flush"), reason="the test role may not checkpoint or switch the WAL")
can_make_roles = pytest.mark.skipif(not RIGHTS.get("roles"), reason="the test role lacks CREATEROLE")
can_grant = pytest.mark.skipif(not RIGHTS.get("grant"), reason="the test role may not grant pg_checkpoint and pg_switch_wal()")


def _wal_file() -> str:
    with psycopg.connect(URL, autocommit=True) as c:
        return c.execute("SELECT pg_walfile_name(pg_current_wal_lsn())").fetchone()[0]


@can_flush
def test_the_flush_closes_the_wal_file_the_deletion_was_written_to():
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS journal_probe (t text)")
        c.execute("INSERT INTO journal_probe VALUES ('kwartelkoning'); DELETE FROM journal_probe")
    before = _wal_file()
    assert flush_journal(URL)
    assert _wal_file() != before  # a new file: the old one is no longer needed after the checkpoint


@can_make_roles
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


@can_grant
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
