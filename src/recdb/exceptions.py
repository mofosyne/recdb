"""
recdb.exceptions
~~~~~~~~~~~~~~~~
Public exception hierarchy for recdb.

All exceptions inherit from RecDBError so callers can catch the base
class if they don't need to distinguish between error kinds::

    try:
        conn.execute("SELECT * FROM items JOIN orders ON ...")
    except recdb.UnsupportedSQLError:
        # JOIN not supported in recfile backend
        ...
    except recdb.RecDBError:
        # catch-all for any recdb error
        ...
"""


class RecDBError(Exception):
    """Base class for all recdb errors."""


class SQLParseError(RecDBError):
    """Raised when a SQL statement cannot be parsed at all.

    This usually means a syntax error or a structural mismatch (e.g.
    column count doesn't match value count in INSERT).
    """


class UnsupportedSQLError(RecDBError):
    """Raised when SQL is valid but uses a feature the recfile backend
    does not support (e.g. JOIN, OR in WHERE, subqueries).
    """


class RecutilsError(RecDBError):
    """Raised when a recutils subprocess (recsel, recins, recset, recdel)
    exits with a non-zero return code.
    """


class RecutilsNotFoundError(RecDBError):
    """Raised when GNU recutils is not found on PATH and the operation
    requires it (i.e. a write or a query that cannot be served by the
    pure-Python read-only fallback).
    """