"""
recdb.parser
~~~~~~~~~~~~
Parses a limited SQL subset into a simple AST dict consumed by the
recfile backend.  The sqlite backend passes SQL straight through so
the parser is only used for recfile.

Supported grammar (rough BNF):
    stmt        ::= select | insert | update | delete | create_table
    select      ::= SELECT cols FROM table [WHERE expr] [ORDER BY col [ASC|DESC]] [LIMIT n]
    insert      ::= INSERT INTO table (col, ...) VALUES (val, ...)
    update      ::= UPDATE table SET col=val [, col=val ...] [WHERE expr]
    delete      ::= DELETE FROM table [WHERE expr]
    create      ::= CREATE TABLE [IF NOT EXISTS] table (col type [constraints] [, ...])
    cols        ::= * | col [, col ...]
    expr        ::= col op val [AND col op val ...]   (no OR, no nesting)
    op          ::= = | != | < | > | <= | >= | LIKE

Raises SQLParseError for malformed SQL, UnsupportedSQLError for valid SQL
that the recfile backend cannot handle.
"""

import re
import sqlparse
from sqlparse.sql import Where, Identifier, IdentifierList
from sqlparse.tokens import Keyword, DML, Name, Wildcard
from typing import Any

from .exceptions import SQLParseError, UnsupportedSQLError

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse(sql: str, parameters: tuple = ()) -> dict:
    sql = sql.strip().rstrip(";")
    if parameters:
        sql = _substitute(sql, parameters)

    if re.match(r"CREATE\s+TABLE", sql, re.IGNORECASE):
        return _parse_create_table(sql)

    statements = sqlparse.parse(sql)
    if len(statements) != 1:
        raise SQLParseError("Only a single statement per execute() is supported")
    stmt = statements[0]

    kind = stmt.get_type()
    if kind not in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        raise UnsupportedSQLError(
            f"Unsupported statement type: {kind!r}. Supported: SELECT, INSERT, UPDATE, DELETE, CREATE TABLE"
        )

    if kind == "SELECT":
        return _parse_select(stmt, sql)
    if kind == "INSERT":
        return _parse_insert(stmt)
    if kind == "UPDATE":
        return _parse_update(stmt)
    if kind == "DELETE":
        return _parse_delete(stmt)
    raise SQLParseError(f"Unhandled statement type: {kind!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Parameter substitution
# ---------------------------------------------------------------------------

def _substitute(sql: str, parameters: tuple) -> str:
    parts = sql.split("?")
    if len(parts) - 1 != len(parameters):
        raise SQLParseError(
            f"Expected {len(parts)-1} parameters, got {len(parameters)}"
        )
    result = parts[0]
    for param, part in zip(parameters, parts[1:]):
        result += _quote(param) + part
    return result


def _quote(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    # Escape embedded single quotes using standard SQL doubling: ' → ''
    return "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# CREATE TABLE
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "INTEGER": "int", "INT": "int", "BIGINT": "int", "SMALLINT": "int",
    "REAL": "real", "FLOAT": "real", "DOUBLE": "real", "NUMERIC": "real", "DECIMAL": "real",
    "TEXT": None, "VARCHAR": None, "CHAR": None, "BLOB": None,
    "BOOLEAN": "bool",
}

def _parse_create_table(sql: str) -> dict:
    m = re.match(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.+)\)",
        sql, re.IGNORECASE | re.DOTALL
    )
    if not m:
        raise SQLParseError("Could not parse CREATE TABLE statement")
    table = m.group(1)
    columns = _parse_column_defs(m.group(2))
    return {
        "type": "CREATE_TABLE",
        "table": table,
        "if_not_exists": bool(re.search(r"IF\s+NOT\s+EXISTS", sql, re.IGNORECASE)),
        "columns": columns,
    }


def _parse_column_defs(body: str) -> list[dict]:
    cols = []
    for part in _split_balanced(body):
        part = part.strip()
        if re.match(r"(PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|INDEX)", part, re.IGNORECASE):
            continue
        m = re.match(r"(\w+)\s+(\w+)", part)
        if not m:
            continue
        name, sql_type = m.group(1), m.group(2).upper()
        cols.append({
            "name": name,
            "sql_type": sql_type,
            "rec_type": _TYPE_MAP.get(sql_type),
            "not_null": bool(re.search(r"NOT\s+NULL", part, re.IGNORECASE)),
            "primary_key": bool(re.search(r"PRIMARY\s+KEY", part, re.IGNORECASE)),
        })
    return cols


def _split_balanced(s: str) -> list[str]:
    """Split on commas respecting nested parentheses."""
    parts, current, depth = [], [], 0
    for ch in s:
        if ch == "(":
            depth += 1; current.append(ch)
        elif ch == ")":
            depth -= 1; current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current)); current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------

def _parse_select(stmt, raw_sql: str) -> dict:
    upper = raw_sql.upper()
    for clause in ("JOIN", "GROUP BY", "HAVING", "UNION"):
        if clause in upper:
            raise UnsupportedSQLError(f"Unsupported clause in recfile backend: {clause}")

    # ORDER BY
    order_by, order_dir = None, "ASC"
    ob_m = re.search(r"ORDER\s+BY\s+(\w+)(?:\s+(ASC|DESC))?", raw_sql, re.IGNORECASE)
    if ob_m:
        order_by = ob_m.group(1)
        order_dir = (ob_m.group(2) or "ASC").upper()

    # LIMIT
    limit = None
    lim_m = re.search(r"LIMIT\s+(\d+)", raw_sql, re.IGNORECASE)
    if lim_m:
        limit = int(lim_m.group(1))

    # Strip ORDER BY / LIMIT before passing to sqlparse so they don't confuse token walking
    clean = re.sub(r"\s+ORDER\s+BY\s+\w+(?:\s+(?:ASC|DESC))?", "", raw_sql, flags=re.IGNORECASE)
    clean = re.sub(r"\s+LIMIT\s+\d+", "", clean, flags=re.IGNORECASE).strip()
    clean_stmt = sqlparse.parse(clean)[0]
    flat = list(clean_stmt.flatten())

    try:
        from_idx = next(
            i for i, t in enumerate(flat)
            if t.ttype is Keyword and t.normalized == "FROM"
        )
    except StopIteration:
        raise SQLParseError("Could not find FROM in SELECT statement")

    return {
        "type": "SELECT",
        "table": _extract_table_after_from(flat, from_idx),
        "columns": _extract_columns(flat, from_idx),
        "where": _extract_where(clean_stmt),
        "order_by": order_by,
        "order_dir": order_dir,
        "limit": limit,
    }


def _extract_columns(flat, from_idx) -> list[str]:
    cols = []
    for t in flat[1:from_idx]:
        if t.ttype is Wildcard:
            return ["*"]
        if t.ttype is Name:
            cols.append(t.value)
        elif isinstance(t, IdentifierList):
            for ident in t.get_identifiers():
                cols.append(ident.get_name() or ident.value)
        elif isinstance(t, Identifier):
            cols.append(t.get_name() or t.value)
    return cols if cols else ["*"]


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------

def _parse_insert(stmt) -> dict:
    sql = stmt.value
    m = re.match(
        r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
        sql, re.IGNORECASE
    )
    if not m:
        raise SQLParseError("Could not parse INSERT. Expected: INSERT INTO table (cols) VALUES (vals)")
    table = m.group(1)
    columns = [c.strip().strip('"\'`') for c in m.group(2).split(",")]
    values = [_unquote(v) for v in _split_values(m.group(3))]
    if len(columns) != len(values):
        raise SQLParseError(
            f"Column count ({len(columns)}) doesn't match value count ({len(values)})"
        )
    return {"type": "INSERT", "table": table, "columns": columns, "values": values}


def _split_values(s: str) -> list[str]:
    """Split a comma-separated VALUES list, respecting quoted strings.
    Handles SQL-style escaped single quotes ('') inside quoted values."""
    vals, current = [], []
    in_quote, quote_char = False, None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_quote:
            # Check for escaped quote: two consecutive quote chars (e.g. Cat''s)
            if ch == quote_char and i + 1 < len(s) and s[i + 1] == quote_char:
                current.append(ch)
                current.append(ch)
                i += 2
                continue
            current.append(ch)
            if ch == quote_char:
                in_quote = False
        elif ch in ("'", '"'):
            in_quote, quote_char = True, ch
            current.append(ch)
        elif ch == ",":
            vals.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        vals.append("".join(current).strip())
    return vals


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

def _parse_update(stmt) -> dict:
    sql = stmt.value
    upper = sql.upper()
    for clause in ("JOIN", "FROM", "RETURNING"):
        if clause in upper:
            raise UnsupportedSQLError(f"Unsupported clause in recfile backend: {clause}")
    m = re.match(r"UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        raise SQLParseError("Could not parse UPDATE statement")
    where_str = m.group(3)
    return {
        "type": "UPDATE",
        "table": m.group(1),
        "assignments": _parse_assignments(m.group(2).strip()),
        "where": _parse_where_string(where_str) if where_str else [],
    }


def _parse_assignments(set_clause: str) -> list[tuple[str, Any]]:
    result = []
    for part in re.split(r",\s*(?=\w+\s*=)", set_clause):
        m = re.match(r"(\w+)\s*=\s*(.+)", part.strip())
        if not m:
            raise SQLParseError(f"Could not parse SET clause: {part!r}")
        result.append((m.group(1), _unquote(m.group(2).strip())))
    return result


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

def _parse_delete(stmt) -> dict:
    sql = stmt.value
    m = re.match(r"DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?$", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        raise SQLParseError("Could not parse DELETE statement")
    where_str = m.group(2)
    return {
        "type": "DELETE",
        "table": m.group(1),
        "where": _parse_where_string(where_str) if where_str else [],
    }


# ---------------------------------------------------------------------------
# WHERE parsing
# ---------------------------------------------------------------------------

def _extract_where(stmt) -> list[dict]:
    for token in stmt.tokens:
        if isinstance(token, Where):
            inner = token.value[5:].strip()
            inner = re.sub(r"\s+ORDER\s+BY\s+.*$", "", inner, flags=re.IGNORECASE)
            inner = re.sub(r"\s+LIMIT\s+\d+.*$", "", inner, flags=re.IGNORECASE)
            return _parse_where_string(inner.strip())
    return []


def _parse_where_string(where_str: str) -> list[dict]:
    # Word-boundary check so "category" doesn't trigger the OR guard
    if re.search(r"\bOR\b", where_str, re.IGNORECASE):
        raise UnsupportedSQLError("OR in WHERE clauses is not supported by the recfile backend")

    conditions = []
    for part in re.split(r"\bAND\b", where_str, flags=re.IGNORECASE):
        part = part.strip()
        # LIKE
        like_m = re.match(r"(\w+)\s+LIKE\s+(.+)", part, re.IGNORECASE)
        if like_m:
            conditions.append({
                "col": like_m.group(1),
                "op": "LIKE",
                "value": _unquote(like_m.group(2).strip()),
            })
            continue
        # Comparison
        m = re.match(r"(\w+)\s*(!=|<=|>=|=|<|>)\s*(.+)", part)
        if not m:
            raise SQLParseError(f"Could not parse WHERE condition: {part!r}")
        conditions.append({
            "col": m.group(1),
            "op": m.group(2),
            "value": _unquote(m.group(3).strip()),
        })
    return conditions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_table_after_from(flat, from_idx) -> str:
    for t in flat[from_idx + 1:]:
        if t.ttype is not None:
            val = t.value.strip().strip("`\"'")
            if val and val.upper() not in ("WHERE", "SET"):
                return val
    raise SQLParseError("Could not find table name after FROM")


def _unquote(s: str) -> Any:
    s = s.strip()
    if s.upper() == "NULL":
        return None
    if (s.startswith("'") and s.endswith("'")) or \
       (s.startswith('"') and s.endswith('"')):
        inner = s[1:-1]
        # Unescape SQL-doubled single quotes: '' -> '
        return inner.replace("''", "'")
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s
