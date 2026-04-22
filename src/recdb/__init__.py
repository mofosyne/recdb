"""
recdb
~~~~~
A recfile DB-API adapter that mirrors the sqlite3 interface.
The mode is inferred from the path passed to connect():

    import recdb

    # Single-file mode — path ends in .rec
    conn = recdb.connect("inventory.rec")    # all tables in one file
    conn = recdb.connect("data/library.rec")

    # Directory mode — path has no .rec extension (or is an existing directory)
    conn = recdb.connect("./data")           # each table → ./data/{table}.rec
    conn = recdb.connect("mydb")             # each table → mydb/{table}.rec

For SQLite, use the stdlib directly:

    import sqlite3
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row

The recfile backend implements the same interface as sqlite3 so that
application code works unchanged across all three.
"""

from pathlib import Path

from .base import BaseConnection, BaseCursor
from .recfile import RecfileConnection

__all__ = ["connect", "RecfileConnection", "BaseConnection", "BaseCursor"]


def connect(path: str) -> "RecfileConnection":
    """
    Open a recfile database connection.

    The mode is inferred from the path:

    - If the path ends in ``.rec`` → **single-file mode**.  All tables are
      stored as ``%rec:`` blocks inside that one file.  The file stem is used
      as the default table name when none is specified in SQL::

          conn = recdb.connect("inventory.rec")
          conn.execute("SELECT * FROM items")        # table from stem
          conn.execute("SELECT * FROM suppliers")    # explicit table name

    - Anything else → **directory mode**.  Each table maps to a separate
      ``.rec`` file inside the directory, which is created if it does not
      exist::

          conn = recdb.connect("./data")
          conn.execute("SELECT * FROM items")    # → ./data/items.rec
          conn.execute("SELECT * FROM orders")   # → ./data/orders.rec

    For SQLite use the stdlib directly: ``sqlite3.connect("inventory.db")``.

    :param path: Path to a ``.rec`` file (single-file mode) or a directory
                 (directory mode).
    :returns:    A :class:`RecfileConnection` instance.
    :raises RuntimeError: If GNU recutils is not installed.
    """

    p = Path(path)

    if p.suffix.lower() == ".rec":
        # Single-file mode
        return RecfileConnection(
            str(p.parent),
            default_table=p.stem,
            single_file=str(p),
        )
    else:
        # Directory mode
        return RecfileConnection(path, default_table=None)
