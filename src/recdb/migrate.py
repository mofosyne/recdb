"""
recdb.migrate
~~~~~~~~~~~~~
Best-effort data migration between recfile and SQLite.

    recdb.migrate("inventory.rec", "inventory.db")   # recfile → sqlite
    recdb.migrate("./data",        "inventory.db")   # directory → sqlite
    recdb.migrate("inventory.db",  "inventory.rec")  # sqlite → recfile
    recdb.migrate("inventory.db",  "./data")          # sqlite → directory

Direction is inferred from the file extensions, consistent with connect():
  - .rec or no extension → recfile (single-file or directory mode)
  - .db / .sqlite / .sqlite3 → SQLite

Schema is inferred from the data:
  - Column names come from field names across all records of each table
    (recfile) or from the existing schema (SQLite).
  - Column types come from %type: descriptors (recfile → SQLite) or from
    SQLite's declared types (SQLite → recfile).
  - Tables with no records are skipped.

This is intentionally best-effort. It handles the common case of moving
data in or out of recfiles cleanly. Edge cases (conflicting field names
across records, exotic recutils types, SQLite-specific constraints) are
not handled — review the output after migration.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

_SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}

# recutils type → SQLite type
_REC_TO_SQL: dict[str, str] = {
    "int":   "INTEGER",
    "real":  "REAL",
    "bool":  "INTEGER",   # no native bool in SQLite
    "date":  "TEXT",
    "line":  "TEXT",
    "url":   "TEXT",
    "email": "TEXT",
}

# SQLite type → recutils type (TEXT columns get no %type: entry)
_SQL_TO_REC: dict[str, str] = {
    "INTEGER": "int",
    "INT":     "int",
    "REAL":    "real",
    "FLOAT":   "real",
    "NUMERIC": "real",
}


def migrate(src: str, dst: str) -> dict[str, int]:
    """
    Copy all data from *src* to *dst*, inferring direction from extensions.

    Returns a dict mapping table name → number of rows migrated.

    :param src: Source path (recfile, recfile directory, or SQLite database).
    :param dst: Destination path.
    :raises ValueError: If source and destination appear to be the same type.
    :raises FileNotFoundError: If a SQLite source does not exist, or no .rec
                               files are found at a recfile source.
    :raises ImportError: If python-recutils is not installed (required for
                         recfile → SQLite migration).
    """
    src_p, dst_p = Path(src), Path(dst)
    src_is_sqlite = src_p.suffix.lower() in _SQLITE_EXTENSIONS
    dst_is_sqlite = dst_p.suffix.lower() in _SQLITE_EXTENSIONS

    if src_is_sqlite == dst_is_sqlite:
        raise ValueError(
            "Cannot infer migration direction — source and destination appear "
            "to be the same type. One must be a recfile path and the other "
            "a SQLite path (.db / .sqlite / .sqlite3)."
        )

    if src_is_sqlite:
        return _sqlite_to_recfile(src_p, dst_p)
    else:
        return _recfile_to_sqlite(src_p, dst_p)


# ---------------------------------------------------------------------------
# recfile → SQLite
# ---------------------------------------------------------------------------

def _recfile_to_sqlite(src: Path, dst: Path) -> dict[str, int]:
    """Migrate recfile(s) at *src* into a SQLite database at *dst*.

    Prefers GNU recutils (recsel + recinf) via subprocess.  Falls back to
    python-recutils if recutils is not on PATH.
    """
    if shutil.which("recsel") is not None:
        return _recfile_to_sqlite_gnu(src, dst)
    else:
        return _recfile_to_sqlite_pyrec(src, dst)


def _recfile_to_sqlite_gnu(src: Path, dst: Path) -> dict[str, int]:
    """recfile → SQLite using GNU recutils (recsel + recinf) subprocesses."""
    rec_files = _collect_rec_files(src)
    if not rec_files:
        raise FileNotFoundError(f"No .rec files found at {src}")

    counts: dict[str, int] = {}
    con = sqlite3.connect(dst)

    try:
        for rec_file in rec_files:
            # recinf lists all record types in the file
            tables = _recinf_tables(rec_file)
            # Untyped file — treat the whole file as one table named after the stem
            if not tables:
                tables = [rec_file.stem]

            for table in tables:
                type_map, records = _recsel_d(rec_file, table)
                if not records:
                    continue

                _sqlite_insert_records(con, table, type_map, records)
                counts[table] = counts.get(table, 0) + len(records)

        con.commit()
    finally:
        con.close()

    return counts


def _recfile_to_sqlite_pyrec(src: Path, dst: Path) -> dict[str, int]:
    """recfile → SQLite using python-recutils (fallback when recutils absent)."""
    try:
        from recutils.parser import parse as _ru_parse
    except ImportError:
        raise ImportError(
            "Neither GNU recutils nor python-recutils is available. "
            "Install one with: apt install recutils  or  pip install recdb[recutils]"
        )

    rec_files = _collect_rec_files(src)
    if not rec_files:
        raise FileNotFoundError(f"No .rec files found at {src}")

    counts: dict[str, int] = {}
    con = sqlite3.connect(dst)

    try:
        for rec_file in rec_files:
            content = rec_file.read_text(encoding="utf-8")
            for rs in _ru_parse(content):
                if not rs.records:
                    continue

                table = rs.record_type or rec_file.stem
                type_map = _parse_type_map_pyrec(rs)
                records = [
                    {f.name: f.value for f in r.fields} for r in rs.records
                ]

                _sqlite_insert_records(con, table, type_map, records)
                counts[table] = counts.get(table, 0) + len(records)

        con.commit()
    finally:
        con.close()

    return counts


def _collect_rec_files(src: Path) -> list[Path]:
    """Return the list of .rec files to migrate from src."""
    if src.suffix.lower() == ".rec":
        return [src]
    if src.exists():
        return sorted(src.glob("*.rec"))
    return []



def _union_columns(records: list[dict]) -> list[str]:
    """Return all field names across all records, preserving first-seen order."""
    seen: set[str] = set()
    cols: list[str] = []
    for record in records:
        for key in record:
            if key not in seen:
                cols.append(key)
                seen.add(key)
    return cols


def _sqlite_insert_records(
    con: sqlite3.Connection,
    table: str,
    type_map: dict[str, str],
    records: list[dict],
) -> None:
    """Create *table* in *con* (if needed) and insert all *records*."""
    all_cols = _union_columns(records)
    col_defs = ", ".join(f'"{c}" {type_map.get(c, "TEXT")}' for c in all_cols)
    con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({col_defs})')

    quoted_cols = ", ".join(f'"{c}"' for c in all_cols)
    placeholders = ", ".join("?" * len(all_cols))
    insert_sql = f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({placeholders})'

    for record in records:
        values = tuple(_coerce(record.get(c), type_map.get(c)) for c in all_cols)
        con.execute(insert_sql, values)


# ---------------------------------------------------------------------------
# GNU recutils subprocess helpers
# ---------------------------------------------------------------------------

def _recinf_tables(rec_file: Path) -> list[str]:
    """Return all record type names in *rec_file* via recinf."""
    result = subprocess.run(
        ["recinf", str(rec_file)], capture_output=True, text=True
    )
    tables = []
    for line in result.stdout.splitlines():
        parts = line.split()
        # recinf output: "N typename"
        if len(parts) == 2 and parts[0].isdigit():
            tables.append(parts[1])
    return tables


def _recsel_d(rec_file: Path, table: str) -> tuple[dict[str, str], list[dict]]:
    """Run `recsel -d -t table` and parse descriptor + records."""
    result = subprocess.run(
        ["recsel", "-d", "-t", table, str(rec_file)],
        capture_output=True, text=True,
    )
    type_map: dict[str, str] = {}
    records: list[dict] = []
    current: dict = {}

    for line in result.stdout.splitlines():
        if line.startswith("%type:"):
            parts = line[6:].strip().split(None, 1)
            if len(parts) == 2:
                col, rec_type = parts
                type_map[col] = _REC_TO_SQL.get(rec_type.lower(), "TEXT")
            continue
        if line.startswith("%"):
            continue  # %rec:, %mandatory:, %key: etc.
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()

    if current:
        records.append(current)

    return type_map, records


# ---------------------------------------------------------------------------
# python-recutils helper
# ---------------------------------------------------------------------------

def _parse_type_map_pyrec(rs) -> dict[str, str]:
    """Extract field → SQLite type from a python-recutils RecordSet descriptor."""
    type_map: dict[str, str] = {}
    if rs.descriptor:
        for f in rs.descriptor.fields:
            if f.name == "%type":
                parts = f.value.split(None, 1)
                if len(parts) == 2:
                    col, rec_type = parts
                    type_map[col] = _REC_TO_SQL.get(rec_type.lower(), "TEXT")
    return type_map


# ---------------------------------------------------------------------------
# SQLite → recfile
# ---------------------------------------------------------------------------

def _sqlite_to_recfile(src: Path, dst: Path) -> dict[str, int]:
    import recdb

    if not src.exists():
        raise FileNotFoundError(f"SQLite database not found: {src}")

    src_con = sqlite3.connect(src)
    src_con.row_factory = sqlite3.Row
    dst_con = recdb.connect(str(dst))
    counts: dict[str, int] = {}

    try:
        tables = [
            row[0] for row in src_con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]

        for table in tables:
            cols_info = src_con.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()
            if not cols_info:
                continue

            col_parts = []
            for col in cols_info:
                name     = col["name"]
                sql_type = (col["type"] or "TEXT").upper().split("(")[0].strip()
                rec_type = _SQL_TO_REC.get(sql_type)
                not_null = bool(col["notnull"])
                col_parts.append(
                    f"{name} {rec_type or 'text'}"
                    + (" NOT NULL" if not_null else "")
                )

            dst_con.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_parts)})"
            )

            rows = src_con.execute(f'SELECT * FROM "{table}"').fetchall()
            if not rows:
                continue

            col_names = [col["name"] for col in cols_info]
            placeholders = ", ".join("?" * len(col_names))
            insert_sql = (
                f"INSERT INTO {table} ({', '.join(col_names)}) "
                f"VALUES ({placeholders})"
            )

            for row in rows:
                dst_con.execute(insert_sql, tuple(row[c] for c in col_names))

            counts[table] = len(rows)

        dst_con.commit()

    finally:
        src_con.close()
        dst_con.close()

    return counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce(val: str, sql_type: str | None) -> Any:
    """Coerce a string value to the appropriate Python type for SQLite."""
    if sql_type == "INTEGER":
        try:
            return int(val)
        except (ValueError, TypeError):
            return val
    if sql_type == "REAL":
        try:
            return float(val)
        except (ValueError, TypeError):
            return val
    return val
