"""
recdb.pyrecutils_backend
~~~~~~~~~~~~~~~~~~~~~~~~
Read/write fallback backend using the ``python-recutils`` PyPI package.
Used automatically when GNU recutils (recsel, recins, …) is not on PATH.

All operations follow the same read-modify-write pattern:
    content = file.read_text()
    content = recins(content, ...)   # or recset / recdel
    file.write_text(content)

Values from python-recutils are always strings; _coerce() is applied
on the way out to restore int/float types.

Limitations vs. the GNU recutils backend:
  - Expression language is python-recutils' own evaluator, not recsel's.
    Complex expressions may behave differently at the edges.
  - No support for %auto fields or recutils validators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._expr import build_expr as _build_expr

try:
    from recutils.recsel import recsel as _ru_recsel
    from recutils.recins import recins as _ru_recins
    from recutils.recset import recset as _ru_recset
    from recutils.recdel import recdel as _ru_recdel
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

def available() -> bool:
    """Return True if python-recutils is importable."""
    return _AVAILABLE


# ---------------------------------------------------------------------------
# Coercion — values from python-recutils are always strings
# ---------------------------------------------------------------------------

def _coerce(val: str) -> Any:
    try:
        return int(val)
    except (ValueError, TypeError):
        pass
    try:
        return float(val)
    except (ValueError, TypeError):
        pass
    return val


def _record_to_dict(record) -> dict:
    return {f.name: _coerce(f.value) for f in record.fields}


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------

def select(rec_file: Path, table: str, ast: dict) -> list[dict]:
    """Execute a SELECT against rec_file using python-recutils."""
    content = rec_file.read_text(encoding="utf-8")

    expr = _build_expr(ast["where"])
    sort_field = ast.get("order_by")

    result = _ru_recsel(
        content,
        record_type=table,
        expression=expr or None,
        sort=sort_field,
    )

    rows = [_record_to_dict(r) for r in result.records]

    if ast.get("order_dir") == "DESC":
        rows = list(reversed(rows))

    if ast.get("limit") is not None:
        rows = rows[: ast["limit"]]

    if ast["columns"] != ["*"]:
        rows = [{col: r.get(col) for col in ast["columns"]} for r in rows]

    return rows


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------

def insert(rec_file: Path, table: str, ast: dict) -> int:
    """Execute an INSERT against rec_file using python-recutils."""
    content = rec_file.read_text(encoding="utf-8") if rec_file.exists() else ""
    fields = {
        col: str(val) if val is not None else ""
        for col, val in zip(ast["columns"], ast["values"])
    }
    content = _ru_recins(content, record_type=table, fields=fields)
    rec_file.write_text(content, encoding="utf-8")
    return 1


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

def update(rec_file: Path, table: str, ast: dict) -> int:
    """Execute an UPDATE against rec_file using python-recutils.

    recset operates on one field at a time, so multiple assignments
    require multiple passes — same as the GNU recutils backend.
    """
    content = rec_file.read_text(encoding="utf-8")
    expr = _build_expr(ast["where"]) or None

    for col, val in ast["assignments"]:
        content = _ru_recset(
            content,
            record_type=table,
            field=col,
            set_or_create=str(val) if val is not None else "",
            expression=expr,
        )

    rec_file.write_text(content, encoding="utf-8")

    # Count affected rows by re-selecting with the same WHERE
    result = _ru_recsel(content, record_type=table, expression=expr)
    return len(result.records)


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

def delete(rec_file: Path, table: str, ast: dict) -> int:
    """Execute a DELETE against rec_file using python-recutils."""
    content = rec_file.read_text(encoding="utf-8")
    expr = _build_expr(ast["where"]) or None

    # Count rows before deletion
    before = _ru_recsel(content, record_type=table, expression=expr)
    count = len(before.records)

    if expr:
        content = _ru_recdel(content, record_type=table, expression=expr)
    else:
        # No WHERE clause — delete all records.
        # recdel with no selection criteria is a no-op, so use index range.
        content = _ru_recdel(content, record_type=table, indexes="0-999999")

    rec_file.write_text(content, encoding="utf-8")
    return count


# ---------------------------------------------------------------------------
# CREATE TABLE
# ---------------------------------------------------------------------------

def create_table(rec_file: Path, table: str, ast: dict) -> None:
    """Write a %rec: header block for *table* into rec_file.

    In single-file mode the header is appended; in directory mode the
    file is created fresh.  The caller has already handled IF NOT EXISTS.
    """
    lines = [f"%rec: {table}"]

    mandatory = [c["name"] for c in ast["columns"] if c["not_null"] or c["primary_key"]]
    if mandatory:
        lines.append(f"%mandatory: {' '.join(mandatory)}")

    for col in ast["columns"]:
        if col["rec_type"]:
            lines.append(f"%type: {col['name']} {col['rec_type']}")

    pk_cols = [c["name"] for c in ast["columns"] if c["primary_key"]]
    if pk_cols:
        lines.append(f"%key: {pk_cols[0]}")

    header = "\n".join(lines) + "\n\n"

    if rec_file.exists():
        # Append new %rec: block (single-file multi-table)
        with open(rec_file, "a", encoding="utf-8") as f:
            f.write(header)
    else:
        rec_file.write_text(header, encoding="utf-8")


