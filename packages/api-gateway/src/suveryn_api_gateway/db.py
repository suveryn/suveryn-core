"""One PostgreSQL connection per store, for the gateway's own tables (conversations, token usage).

PostgreSQL is provisioned outside suveryn-core (suveryn-appliance); a store connects with
``SUVERYN_DATABASE_URL`` and creates or upgrades its own tables (``schema``, idempotent DDL).
"""

import psycopg


class PgStore:
    """An autocommit connection that reconnects once if PostgreSQL restarted or dropped it.

    psycopg 3 connections are thread-safe (statements are serialised), so one store serves the
    gateway's thread pool.
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

    def _execute(self, sql: str, params=()) -> psycopg.Cursor:
        """Run one statement, reconnecting once if the connection was lost."""
        try:
            return self._conn.execute(sql, params)
        except psycopg.OperationalError:
            try:
                self._conn.close()
            except psycopg.Error:
                pass
            self._conn = psycopg.connect(self._url, autocommit=True)
            return self._conn.execute(sql, params)
