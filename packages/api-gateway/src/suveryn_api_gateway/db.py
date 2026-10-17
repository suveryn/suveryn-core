"""One PostgreSQL connection per store, for the gateway's own tables (conversations, token usage).

PostgreSQL is provisioned outside suveryn-core (suveryn-appliance); a store connects with
``SUVERYN_DATABASE_URL`` and creates or upgrades its own tables (``schema``, idempotent DDL).
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


class PgStore:
    """An autocommit connection that reconnects once if PostgreSQL restarted or dropped it.

    psycopg 3 connections are thread-safe (statements are serialised), so one store serves the
    gateway's thread pool. A write of more than one statement runs inside ``transaction()``, so a
    dropped connection or an error halfway leaves nothing half-written (review finding: a case
    without its manager, which decision 6 of the cases design forbids).
    """

    schema = ""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("SUVERYN_DATABASE_URL is not set")
        self._url = database_url
        self._conn = psycopg.connect(database_url, autocommit=True)
        if self.schema:
            self._conn.execute(self.schema)

    def close(self) -> None:
        self._conn.close()

    def _reconnect(self) -> None:
        try:
            self._conn.close()
        except psycopg.Error:
            pass
        self._conn = psycopg.connect(self._url, autocommit=True)

    def _execute(self, sql: str, params=()) -> psycopg.Cursor:
        """Run one statement, reconnecting once if the connection was lost. Inside ``transaction()``
        there is no reconnecting: the statement fails and the transaction with it, nothing is
        half-written, and the caller's next call reconnects."""
        try:
            return self._conn.execute(sql, params)
        except psycopg.OperationalError:
            if self._conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                raise
            self._reconnect()
            return self._conn.execute(sql, params)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Several statements as one: all written, or none. Reconnects first if the connection was
        lost since the last statement, so a transaction never starts on a dead connection."""
        if self._conn.closed:
            self._reconnect()
        with self._conn.transaction():
            yield
