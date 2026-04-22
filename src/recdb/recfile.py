"""
recdb.recfile
~~~~~~~~~~~~~
Recfile backend.  Translates parsed SQL ASTs into recutils CLI calls
(recsel, recins, recset, recdel).

Used via recdb.connect() — not instantiated directly:

    conn = recdb.connect("inventory.rec")  # single-file mode
    conn = recdb.connect("./data")         # directory mode

recutils 1.9 notes:
  - recsel -S <field>  sorts ASC only; DESC is done by reversing in Python
  - recdel --force     required to delete all records of a typed set
  - recsel -R          means "print-row", NOT reverse sort — we avoid it
"""

import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import Any, Optional

from .base import BaseConnection, BaseCursor
from .exceptions import RecutilsError, RecutilsNotFoundError
from .parser import parse


def _like_to_regex(val: str) -> str:
    """Translate SQL LIKE pattern to a recsel regex. % → .* and _ → ."""
    result = ""
    for ch in val:
        if ch == "%":
            result += ".*"
        elif ch == "_":
            result += "."
        elif ch in r"\.+?{}[]|()^$":
            result += "\\" + ch
        else:
            result += ch
    return result


def _recutils_available() -> bool:
    """Return True if recsel is available on PATH."""
    return shutil.which("recsel") is not None


def _parse_recfile_python(filepath: Path, table: str | None = None) -> list[dict]:
    """
    Pure-Python read-only .rec file parser.  Used as a fallback when
    GNU recutils is not installed.

    Handles:
      - %rec: tablename   — record-type descriptor blocks
      - %type: / %mandatory: / %key: etc  — descriptor lines (skipped)
      - Key: Value        — field lines
      - +continuation     — multi-line field values
      - #comments         — ignored
      - blank lines       — record separators
    """
    records: list[dict] = []
    current: dict = {}
    last_key: str | None = None
    in_target = table is None  # if no table filter, accept everything

    with open(filepath, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")

            # %rec: block header — switch target tracking
            if line.startswith("%rec:"):
                # Flush any in-progress record on table boundary
                if current:
                    records.append(current)
                    current = {}
                    last_key = None
                table_name = line[5:].strip()
                in_target = (table is None or table_name == table)
                continue

            if not in_target:
                continue

            # Skip descriptor lines and comments
            if line.startswith("%") or line.startswith("#"):
                continue

            # Continuation line: appends to the last field value
            if line.startswith("+"):
                if last_key and last_key in current:
                    current[last_key] = current[last_key] + "\n" + line[1:].strip()
                continue

            # Blank line: record separator
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                    last_key = None
                continue

            # Field line: "Key: Value"
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                current[key] = _coerce(value.strip())
                last_key = key

    # Flush the final record (file may not end with a blank line)
    if current:
        records.append(current)

    return records


def _python_filter(records: list[dict], conditions: list[dict]) -> list[dict]:
    """Apply WHERE conditions to records using pure Python."""
    import fnmatch
    result = []
    for row in records:
        match = True
        for cond in conditions:
            col, op, val = cond["col"], cond["op"], cond["value"]
            row_val = row.get(col)
            if row_val is None:
                match = False
                break
            # Coerce for numeric comparisons
            try:
                rv, cv = float(str(row_val)), float(str(val))
            except (ValueError, TypeError):
                rv, cv = str(row_val), str(val)
            if op == "=" and rv != cv:
                match = False
            elif op == "!=" and rv == cv:
                match = False
            elif op == "<" and not rv < cv:
                match = False
            elif op == ">" and not rv > cv:
                match = False
            elif op == "<=" and not rv <= cv:
                match = False
            elif op == ">=" and not rv >= cv:
                match = False
            elif op == "LIKE":
                # Translate SQL LIKE to fnmatch: % → *, _ → ?
                pattern = str(val).replace("%", "*").replace("_", "?")
                if not fnmatch.fnmatch(str(row_val), pattern):
                    match = False
            if not match:
                break
        if match:
            result.append(row)
    return result

# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

class RecfileCursor(BaseCursor):

    def __init__(self, directory: str, default_table: Optional[str] = None,
                 single_file: Optional[str] = None):
        self._directory = Path(directory)
        self._default_table = default_table
        self._single_file = Path(single_file) if single_file else None
        self._rows: list[dict] = []
        self._pos: int = 0
        self._rowcount: int = -1
        self._description: Optional[tuple] = None

    @property
    def rowcount(self) -> int:
        return self._rowcount

    @property
    def description(self) -> Optional[tuple]:
        return self._description

    def execute(self, sql: str, parameters: tuple = ()) -> "RecfileCursor":
        ast = parse(sql, parameters)
        kind = ast["type"]

        # Allow omitting the table name when using single-file mode
        if self._default_table and kind != "CREATE_TABLE":
            if not ast.get("table"):
                ast["table"] = self._default_table

        if kind == "SELECT":
            self._rows = self._select(ast)
            self._pos = 0
            self._rowcount = len(self._rows)
            self._description = tuple(
                (col, None, None, None, None, None, None)
                for col in self._rows[0].keys()
            ) if self._rows else ()
        elif kind == "INSERT":
            self._rowcount = self._insert(ast)
            self._rows = []
        elif kind == "UPDATE":
            self._rowcount = self._update(ast)
            self._rows = []
        elif kind == "DELETE":
            self._rowcount = self._delete(ast)
            self._rows = []
        elif kind == "CREATE_TABLE":
            self._create_table(ast)
            self._rowcount = -1
            self._rows = []

        return self

    def executemany(self, sql: str, seq_of_parameters) -> "RecfileCursor":
        total = 0
        for params in seq_of_parameters:
            self.execute(sql, params)
            if self._rowcount > 0:
                total += self._rowcount
        self._rowcount = total
        return self

    # --- fetch --------------------------------------------------------------

    def fetchone(self) -> Optional[dict]:
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self) -> list[dict]:
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def fetchmany(self, size: int = 1) -> list[dict]:
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    # --- CREATE TABLE -------------------------------------------------------

    def _table_exists(self, table: str, rec_file: Path) -> bool:
        """Check whether a %rec: block for *table* already exists in rec_file."""
        if not rec_file.exists():
            return False
        if self._single_file is not None:
            # Single-file: the file exists but the block may not yet be in it
            return f"%rec: {table}" in rec_file.read_text()
        # Directory: one file per table — file existence is sufficient
        return True

    def _create_table(self, ast: dict) -> None:
        if not _recutils_available():
            raise RecutilsNotFoundError(
                "GNU recutils is required for CREATE TABLE operations. "
                "Install with: apt install recutils  or  brew install recutils"
            )

        rec_file = self._rec_path(ast["table"])

        if ast["if_not_exists"] and self._table_exists(ast["table"], rec_file):
            return

        lines = [f"%rec: {ast['table']}"]

        mandatory = [c["name"] for c in ast["columns"] if c["not_null"] or c["primary_key"]]
        if mandatory:
            lines.append(f"%mandatory: {' '.join(mandatory)}")

        for col in ast["columns"]:
            if col["rec_type"]:
                lines.append(f"%type: {col['name']} {col['rec_type']}")

        pk_cols = [c["name"] for c in ast["columns"] if c["primary_key"]]
        if pk_cols:
            lines.append(f"%key: {pk_cols[0]}")

        # Trailing blank line required — recutils needs it before first record
        header = "\n".join(lines) + "\n\n"
        if self._single_file is not None and rec_file.exists():
            # Append new %rec: block to the existing single file
            with open(rec_file, "a") as f:
                f.write(header)
        else:
            rec_file.write_text(header)

    # --- SELECT -------------------------------------------------------------

    def _select(self, ast: dict) -> list[dict]:
        rec_file = self._rec_path(ast["table"])
        if not rec_file.exists():
            return []

        if not _recutils_available():
            return self._select_python(ast, rec_file)

        cmd = ["recsel", "-t", ast["table"]]

        if ast["columns"] != ["*"]:
            cmd += ["-p", ",".join(ast["columns"])]

        expr = self._build_expr(ast["where"])
        if expr:
            cmd += ["-e", expr]

        # recsel only sorts ASC; for DESC we sort ASC then reverse in Python
        if ast.get("order_by"):
            cmd += ["-S", ast["order_by"]]

        need_py_limit = ast.get("limit") is not None and ast.get("order_dir") == "DESC"
        if ast.get("limit") is not None and not need_py_limit:
            cmd += ["-m", str(ast["limit"])]

        cmd.append(str(rec_file))
        rows = _parse_recsel_output(self._run(cmd))

        if ast.get("order_dir") == "DESC":
            rows = list(reversed(rows))
        if need_py_limit:
            rows = rows[:ast["limit"]]

        return rows

    def _select_python(self, ast: dict, rec_file: Path) -> list[dict]:
        """Pure-Python SELECT fallback used when recutils is not installed."""
        rows = _parse_recfile_python(rec_file, ast["table"])

        if ast["where"]:
            rows = _python_filter(rows, ast["where"])

        if ast.get("order_by"):
            reverse = ast.get("order_dir") == "DESC"
            rows = sorted(rows, key=lambda r: r.get(ast["order_by"], ""), reverse=reverse)

        if ast.get("limit") is not None:
            rows = rows[:ast["limit"]]

        if ast["columns"] != ["*"]:
            rows = [{col: r.get(col) for col in ast["columns"]} for r in rows]

        return rows

    # --- INSERT -------------------------------------------------------------

    def _insert(self, ast: dict) -> int:
        if not _recutils_available():
            raise RecutilsNotFoundError(
                "GNU recutils is required for INSERT operations. "
                "Install with: apt install recutils  or  brew install recutils"
            )

        rec_file = self._rec_path(ast["table"])
        if not rec_file.exists():
            rec_file.touch()

        cmd = ["recins", "-t", ast["table"]]
        for col, val in zip(ast["columns"], ast["values"]):
            cmd += ["-f", col, "-v", str(val) if val is not None else ""]
        cmd.append(str(rec_file))
        self._run(cmd)
        return 1

    # --- UPDATE -------------------------------------------------------------

    def _update(self, ast: dict) -> int:
        if not _recutils_available():
            raise RecutilsNotFoundError(
                "GNU recutils is required for UPDATE operations. "
                "Install with: apt install recutils  or  brew install recutils"
            )

        rec_file = self._rec_path(ast["table"])
        if not rec_file.exists():
            return 0

        expr = self._build_expr(ast["where"])
        for col, val in ast["assignments"]:
            cmd = ["recset", "-t", ast["table"]]
            if expr:
                cmd += ["-e", expr]
            cmd += ["-f", col, "-s", str(val) if val is not None else ""]
            cmd.append(str(rec_file))
            self._run(cmd)

        return len(self._select({
            "table": ast["table"], "columns": ["*"],
            "where": ast["where"], "order_by": None, "order_dir": "ASC", "limit": None,
        }))

    # --- DELETE -------------------------------------------------------------

    def _delete(self, ast: dict) -> int:
        if not _recutils_available():
            raise RecutilsNotFoundError(
                "GNU recutils is required for DELETE operations. "
                "Install with: apt install recutils  or  brew install recutils"
            )

        rec_file = self._rec_path(ast["table"])
        if not rec_file.exists():
            return 0

        before = self._select({
            "table": ast["table"], "columns": ["*"],
            "where": ast["where"], "order_by": None, "order_dir": "ASC", "limit": None,
        })

        cmd = ["recdel", "-t", ast["table"]]
        expr = self._build_expr(ast["where"])
        if expr:
            cmd += ["-e", expr]
        else:
            cmd.append("--force")
        cmd.append(str(rec_file))
        self._run(cmd)
        return len(before)

    # --- helpers ------------------------------------------------------------

    def _build_expr(self, conditions: list[dict]) -> str:
        if not conditions:
            return ""
        parts = []
        for c in conditions:
            col, op, val = c["col"], c["op"], c["value"]
            if op == "LIKE":
                parts.append(f"{col} ~ '{_like_to_regex(str(val))}'")
            elif op == "=":
                parts.append(f"{col} = '{val}'")
            elif op == "!=":
                parts.append(f"{col} != '{val}'")
            elif op in ("<", ">", "<=", ">="):
                parts.append(f"{col} {op} {val}")
        return " && ".join(parts)

    def _rec_path(self, table: str) -> Path:
        if self._single_file is not None:
            return self._single_file
        return self._directory / f"{table}.rec"

    def _run(self, cmd: list[str]) -> str:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RecutilsError(
                f"recutils command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
            )
        return result.stdout


# ---------------------------------------------------------------------------
# Parse recsel output
# ---------------------------------------------------------------------------

def _parse_recsel_output(output: str) -> list[dict]:
    records, current = [], {}
    for line in output.splitlines():
        if line.strip() == "":
            if current:
                records.append(current)
                current = {}
            continue
        if line.startswith("+"):
            if current:
                last_key = list(current.keys())[-1]
                current[last_key] += "\n" + line[1:].strip()
            continue
        m = re.match(r"^(\w+):\s*(.*)", line)
        if m:
            current[m.group(1)] = _coerce(m.group(2))
    if current:
        records.append(current)
    return records


def _coerce(val: str) -> Any:
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class RecfileConnection(BaseConnection):
    """
    Connection to a recfile database.  Create via recdb.connect(), not directly.

    Single-file mode:   recdb.connect("inventory.rec")
    Directory mode:     recdb.connect("./data")
    """

    def __init__(self, directory: str, default_table: Optional[str] = None,
                 single_file: Optional[str] = None):
        self._directory = directory
        self._default_table = default_table
        self._single_file = single_file
        os.makedirs(directory, exist_ok=True)

    def cursor(self) -> RecfileCursor:
        return RecfileCursor(self._directory, self._default_table,
                             single_file=self._single_file)

    def close(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

