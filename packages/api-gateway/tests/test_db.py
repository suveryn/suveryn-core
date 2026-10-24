"""The gateway's stores after PostgreSQL drops their connection (Pod check of f0ff96c): a restart left every
store answering "the connection is closed" until the gateway restarted, and /health said ready. Against a real
PostgreSQL, skipped unless SUVERYN_TEST_DATABASE_URL is set."""

import os

import psycopg
import pytest
from suveryn_api_gateway.db import PgStore
from suveryn_api_gateway.routes.common import Database

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


def drop(store: PgStore) -> None:
    """What a PostgreSQL restart does to the store's connection: the server ends it."""
    pid = store._conn.info.backend_pid
    with psycopg.connect(URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))


@needs_db
def test_a_store_reconnects_after_postgresql_ended_its_connection():
    s = PgStore(URL)
    try:
        drop(s)
        assert s._execute("SELECT 1").fetchone() == (1,)  # the first statement after it works
        drop(s)
        with pytest.raises(psycopg.OperationalError):
            s._conn.execute("SELECT 1")  # the dead connection, as the failed request saw it
        assert s._conn.closed or s._conn.broken
        assert s._execute("SELECT 2").fetchone() == (2,)  # and the next request still gets through
    finally:
        s.close()


@needs_db
def test_a_transaction_on_a_lost_connection_starts_on_a_new_one():
    s = PgStore(URL)
    try:
        drop(s)
        with pytest.raises(psycopg.OperationalError):
            s._conn.execute("SELECT 1")
        with s.transaction():
            assert s._conn.execute("SELECT 3").fetchone() == (3,)
    finally:
        s.close()


@needs_db
def test_health_says_failed_while_the_database_doesnt_answer(monkeypatch):
    s = PgStore(URL)
    db = Database("conversations", store=s)
    try:
        assert db.status().status == "ready"
        monkeypatch.setattr(s, "_url", "postgresql://nobody@/nothing?host=/nonexistent&port=1")  # PostgreSQL down
        drop(s)
        status = db.status()
        assert status.status == "failed" and "can't be reached" in (status.detail or "")
    finally:
        s.close()
