"""
recdb
~~~~~
A recfile DB-API adapter that mirrors the sqlite3 interface.
Backend is inferred from the file extension:

    import recdb
    conn = recdb.connect("inventory.rec")   # recfile backend (GNU recutils)

For multi-table directory mode:

    conn = recdb.connect_dir("./data")      # each table → ./data/{table}.rec

For SQLite, use the stdlib directly — it already works:

    import sqlite3
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row          # makes rows dict-like

The recfile backend implements the same interface as sqlite3 so that
application code works unchanged against either.
"""

from .base import BaseConnection, BaseCursor
from .recfile import RecfileConnection
import shutil

__all__ = ["connect", "connect_dir", "RecfileConnection", "BaseConnection", "BaseCursor"]

_REC_EXTENSIONS = {".rec"}


def connect(path: str) -> "RecfileConnection":
    """
    Open a single-file recfile database connection.

    The path should point to a ``.rec`` file.  The parent directory is
    used as the database root and the file stem becomes the default table
    name, so ``connect("data/inventory.rec")`` will query the ``inventory``
    record type inside ``data/inventory.rec``.

    For a directory of ``.rec`` files (one per table), use
    :func:`connect_dir` instead.

    :param path: Path to a ``.rec`` file.
    :returns:    A :class:`RecfileConnection` instance.
    :raises ValueError: If the path does not have a ``.rec`` extension.
    :raises RuntimeError: If GNU recutils is not installed.
    """
    from pathlib import Path
    p = Path(path)
    ext = p.suffix.lower()

    if shutil.which("recsel") is None:
        raise RuntimeError(
            "GNU recutils is required but not found in PATH. "
            "Install with: apt install recutils  or  brew install recutils"
        )

    if ext not in _REC_EXTENSIONS:
        raise ValueError(
            f"recdb.connect() only opens .rec files (got {ext!r}). "
            f"For SQLite use: sqlite3.connect({str(path)!r})\n"
            f"For a directory of .rec files use: recdb.connect_dir(directory)"
        )

    return RecfileConnection(str(p.parent), default_table=p.stem)


def connect_dir(directory: str) -> "RecfileConnection":
    """
    Open a directory-mode recfile database connection.

    Each table maps to a separate ``.rec`` file in the directory::

        conn = recdb.connect_dir("./data")
        conn.execute("SELECT * FROM items")    # → ./data/items.rec
        conn.execute("SELECT * FROM orders")   # → ./data/orders.rec

    The directory is created if it does not exist.  Table names must be
    supplied explicitly in every SQL statement — there is no default table.

    :param directory: Path to the directory containing ``.rec`` files.
    :returns:         A :class:`RecfileConnection` instance.
    :raises RuntimeError: If GNU recutils is not installed.
    """
    if shutil.which("recsel") is None:
        raise RuntimeError(
            "GNU recutils is required but not found in PATH. "
            "Install with: apt install recutils  or  brew install recutils"
        )

    return RecfileConnection(directory, default_table=None)
