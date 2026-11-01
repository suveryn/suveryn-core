"""After a deletion, let PostgreSQL drop the journal that still holds the deleted text (VM regression
03c8f74, finding 3).

PostgreSQL writes every change to its write-ahead log (the WAL, in ``pg_wal``) before the tables. A
document's text goes in when it is stored, and a deletion writes the pages it touches there again,
deleted text included. A WAL file is let go only once it is full and a checkpoint has passed it, so on
a quiet appliance the text stayed in it for hours after the document was deleted (the test found all
five test words in six WAL files after the delete and a ``VACUUM (FULL)``).

``flush_journal`` closes the current WAL file (``pg_switch_wal()``) and runs a ``CHECKPOINT``: every
WAL file before it is then no longer needed and PostgreSQL lets it go. The appliance sets
``wal_recycle = off``, so a file let go is deleted rather than renamed and kept for reuse with its old
content, and grants the database role ``pg_checkpoint`` and the right to call ``pg_switch_wal()``.
Without those rights nothing happens and the function says so (False): the WAL is then let go in the
course of normal use, as before.

It takes a few seconds and runs on a connection of its own, so nothing waits for it. What it doesn't
do: the deleted text can still be in backups until they roll over, and in the disk's free blocks until
they are written over (docs/architecture.md §6).
"""

from __future__ import annotations

import logging

import psycopg

log = logging.getLogger(__name__)


def flush_journal(database_url: str) -> bool:
    """Close the current WAL file and checkpoint, so the WAL files holding deleted text are let go.
    False when the role lacks the rights or the database can't be reached (logged, never raised)."""
    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("SELECT pg_switch_wal()")
            conn.execute("CHECKPOINT")
        return True
    except psycopg.errors.InsufficientPrivilege:
        log.warning("the journal could not be flushed after a deletion: the database role may not "
                    "checkpoint or switch the WAL (see suveryn-appliance's provisioning)")
        return False
    except psycopg.Error as e:
        log.warning("the journal could not be flushed after a deletion: %s", type(e).__name__)
        return False
