"""
recdb
~~~~~
A recfile DB-API adapter that mirrors the sqlite3 interface.
Backend is inferred from the file extension:

    import recdb
    conn = recdb.connect("inventory.rec")   # recfile backend (GNU recutils)

For SQLite, use the stdlib directly — it already works:

    import sqlite3
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row          # makes rows dict-like

The recfile backend implements the same interface as sqlite3 so that
application code works unchanged against either.
"""

from .base import BaseConnection, BaseCursor
from .recfile import RecfileConnection

__all__ = ["connect", "RecfileConnection", "BaseConnection", "BaseCursor"]

_REC_EXTENSIONS = {".rec"}


def connect(path: str) -> "RecfileConnection":
    """
    Open a recfile database connection.

    The path should point to a ``.rec`` file.  The parent directory is
    used as the database root and the file stem becomes the default table
    name, so ``connect("data/inventory.rec")`` will query the ``inventory``
    record type inside ``data/inventory.rec``.

    :param path: Path to a ``.rec`` file.
    :returns:    A :class:`RecfileConnection` instance.
    :raises ValueError: If the path does not have a ``.rec`` extension.
    """
    from pathlib import Path
    p = Path(path)
    ext = p.suffix.lower()

    if ext not in _REC_EXTENSIONS:
        raise ValueError(
            f"recdb.connect() only opens .rec files (got {ext!r}). "
            f"For SQLite use: sqlite3.connect({str(path)!r})"
        )

    return RecfileConnection(str(p.parent), default_table=p.stem)
