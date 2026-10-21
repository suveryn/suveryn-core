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

    # Inside a transaction a lost connection isn't replaced: the statement fails and the transaction
    # with it. Any other state (IDLE, or UNKNOWN for a connection PostgreSQL closed) gets a new one.
    _IN_TRANSACTION = (psycopg.pq.TransactionStatus.INTRANS, psycopg.pq.TransactionStatus.INERROR,
                       psycopg.pq.TransactionStatus.ACTIVE)

    def _lost(self) -> bool:
        return self._conn.closed or self._conn.broken

    def _execute(self, sql: str, params=()) -> psycopg.Cursor:
        """Run one statement, reconnecting once if the connection was lost. Inside ``transaction()``
        there is no reconnecting: the statement fails and the transaction with it, nothing is
        half-written, and the caller's next call reconnects.

        A connection PostgreSQL closed (a restart) reports ``closed`` and its transaction status as
        UNKNOWN, not IDLE: it is replaced too. Before, it never was, and every request failed until
        the gateway restarted (Pod check of 7c48279). While PostgreSQL is still down, the new
        connection fails, and so does the statement (``OperationalError``, answered 503); the next
        call tries again."""
        if self._lost():
            self._reconnect()
        try:
            return self._conn.execute(sql, params)
        except psycopg.OperationalError:
            if not self._lost() and self._conn.info.transaction_status in self._IN_TRANSACTION:
                raise
            self._reconnect()
            return self._conn.execute(sql, params)

    def alive(self) -> bool:
        """Whether the database answers now (reconnecting if it can): for /health."""
        try:
            self._execute("SELECT 1")
            return True
        except psycopg.Error:
            return False

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Several statements as one: all written, or none. Reconnects first if the connection was
        lost since the last statement, so a transaction never starts on a dead connection."""
        if self._lost():
            self._reconnect()
        with self._conn.transaction():
            yield
