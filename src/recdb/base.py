"""
recdb.base
~~~~~~~~~~
Abstract base classes that define the interface RecfileConnection implements.

This mirrors the sqlite3 / PEP 249 DB-API 2.0 interface so that application
code can swap between recdb and stdlib sqlite3 with minimal changes.

The sqlite3 equivalents are noted in comments for reference — they are NOT
wrapped here.  For sqlite3 use the stdlib directly:

    import sqlite3
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row   # makes rows subscriptable by name
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseCursor(ABC):
    """
    Mirrors sqlite3.Cursor.

    Key differences from raw sqlite3:
    - fetchone() / fetchall() / fetchmany() return dicts (sqlite3 returns
      tuples by default, or sqlite3.Row with row_factory = sqlite3.Row)
    - rowcount after SELECT returns len(rows) (sqlite3 returns -1)
    """

    @property
    @abstractmethod
    def rowcount(self) -> int:
        """Rows affected/returned by the last execute()."""

    @property
    @abstractmethod
    def description(self) -> Optional[tuple]:
        """Column descriptions after a SELECT, None otherwise."""

    @abstractmethod
    def execute(self, sql: str, parameters: tuple = ()) -> "BaseCursor":
        """Execute a single SQL statement."""

    @abstractmethod
    def executemany(self, sql: str, seq_of_parameters) -> "BaseCursor":
        """Execute the same statement for each parameter tuple."""

    @abstractmethod
    def fetchone(self) -> Optional[dict]:
        """Return the next row as a dict, or None if exhausted."""

    @abstractmethod
    def fetchall(self) -> list[dict]:
        """Return all remaining rows as a list of dicts."""

    @abstractmethod
    def fetchmany(self, size: int = 1) -> list[dict]:
        """Return up to *size* rows as a list of dicts."""

    def __iter__(self):
        return iter(self.fetchall())


class BaseConnection(ABC):
    """
    Mirrors sqlite3.Connection.

    commit() and rollback() are no-ops on the recfile backend — writes
    are immediate.  They exist so application code written against sqlite3
    works unchanged.
    """

    @abstractmethod
    def cursor(self) -> BaseCursor:
        """Return a new cursor object."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""

    @abstractmethod
    def commit(self) -> None:
        """Commit any pending transaction (no-op for recfile)."""

    @abstractmethod
    def rollback(self) -> None:
        """Roll back any pending transaction (no-op for recfile)."""

    def execute(self, sql: str, parameters: tuple = ()) -> BaseCursor:
        """Shorthand: cursor().execute(sql, parameters)."""
        cur = self.cursor()
        cur.execute(sql, parameters)
        return cur

    def executemany(self, sql: str, seq_of_parameters) -> BaseCursor:
        """Shorthand: cursor().executemany(sql, seq_of_parameters)."""
        cur = self.cursor()
        cur.executemany(sql, seq_of_parameters)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False
