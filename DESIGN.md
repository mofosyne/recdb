# recdb — Design & Architecture

This document covers why recdb is built the way it is, the tradeoffs
that were consciously made, and where the project could reasonably evolve.
Read this before making a significant architectural change.

---

## Purpose

recdb exists for a specific niche: small projects where **textual
transparency matters more than performance**. A `.rec` file is plain text —
human-readable, diffable with `git diff`, editable with any text editor,
queryable with standard Unix tools (`grep`, `recsel`, `awk`). For
configuration-adjacent data, audit logs, or small inventory/catalogue
systems, that's a genuine advantage over a binary `.db` file.

The design goal is that switching from recfile to SQLite (or back) is a
one-line change, and nothing else in the application changes.

---

## Architecture

```
Application code
      │
      ├── recdb.connect("inventory.rec")     ← single-file mode
      ├── recdb.connect("./data")            ← directory mode
      │         │
      │         ▼
      │   BaseConnection (ABC)    ← documents the sqlite3-compatible interface
      │   BaseCursor (ABC)
      │         │
      │         └── RecfileConnection / RecfileCursor
      │                 │
      │                 ├── parser.py          SQL subset → AST
      │                 ├── _expr.py           AST → recsel expression string
      │                 │
      │                 ├── GNU recutils       primary backend (subprocess)
      │                 │   recsel / recins / recset / recdel
      │                 │
      │                 └── pyrecutils_backend.py   fallback (pure Python)
      │                     python-recutils package
      │
      └── sqlite3.connect("inventory.db")   ← stdlib, used directly by callers
              conn.row_factory = sqlite3.Row
```

### Backend selection

`recdb.connect()` infers the mode from the path extension:

- Path ends in `.rec` → **single-file mode**. All tables are stored as
  `%rec:` blocks inside that one file. The file stem is the default table
  name when SQL omits it.
- Any other path → **directory mode**. Each table maps to a separate `.rec`
  file inside the directory, which is created if it does not exist.

Both modes use the same `RecfileConnection` class, distinguished by two
constructor parameters: `single_file` (the fixed path used for all
operations) and `default_table` (the table assumed when SQL omits it).
Directory mode leaves both as `None`.

At operation time, `RecfileCursor` tries GNU recutils first. If `recsel` is
not on PATH it falls back to the `python-recutils` package. If neither is
available, `RecutilsNotFoundError` is raised.

### The parser

The SQL parser (`parser.py`) is used **only** by the recfile backend.
SQLite receives SQL verbatim and handles it natively.

The parser uses `sqlparse` for tokenisation, then translates the AST into
recutils CLI arguments (or the equivalent `python-recutils` function calls).
The expression builder lives in `_expr.py` and is imported by both backends
so the recsel expression syntax is generated in exactly one place.

Supported SQL:

```
SELECT [cols] FROM table [WHERE expr] [ORDER BY col [ASC|DESC]] [LIMIT n]
INSERT INTO table (cols) VALUES (vals)
UPDATE table SET col=val [, col=val ...] [WHERE expr]
DELETE FROM table [WHERE expr]
CREATE TABLE [IF NOT EXISTS] table (col type ...)
```

Unsupported constructs raise `UnsupportedSQLError`. Malformed SQL raises
`SQLParseError`. Both inherit from `RecDBError`.

### recutils mapping

| SQL                          | GNU recutils                                     | python-recutils                             |
|------------------------------|--------------------------------------------------|---------------------------------------------|
| `SELECT ... WHERE x = 'y'`   | `recsel -e "x = 'y'"`                            | `recsel(content, expression="x = 'y'")`     |
| `SELECT ... ORDER BY x`      | `recsel -S x`                                    | `recsel(content, sort="x")`                 |
| `SELECT ... ORDER BY x DESC` | `recsel -S x` + Python `reversed()`              | same                                        |
| `SELECT ... LIMIT n`         | `recsel -m n`                                    | slice result list                           |
| `WHERE name LIKE 'A%'`       | `recsel -e "name ~ 'A.*'"`                       | same expression                             |
| `INSERT`                     | `recins -f col -v val`                           | `recins(content, fields={...})`             |
| `UPDATE ... SET x=y`         | `recset -f x -s y` (one call per field)          | `recset(content, field=x, set_or_create=y)` |
| `DELETE`                     | `recdel [-e expr]`                               | `recdel(content, expression=expr)`          |
| `DELETE` (no WHERE)          | `recdel --force`                                 | `recdel(content, indexes="0-999999")`       |
| `CREATE TABLE`               | writes `%rec:` / `%type:` / `%mandatory:` header | same via file write                         |

**Known recutils 1.9 limitations:**
- `recsel` sorts ascending only; DESC is emulated by reversing in Python.
- `recset` takes one field per call, so `UPDATE SET a=1, b=2` makes two
  subprocess calls (same number of `recset()` calls in the Python backend).
- `recdel` with no expression is a no-op in `python-recutils` — the
  delete-all case uses `indexes="0-999999"` instead.
- `-R` in recsel means "print-row", not "reverse" — we avoid it.
- `UPDATE` rowcount is derived from a follow-up `recsel` after `recset`
  completes. Under concurrent access this could be inaccurate; for the
  single-user recfile use case it is acceptable.

### Rows as dicts

Both backends return rows as `dict` rather than `tuple`. This is a
deliberate deviation from stdlib `sqlite3` (which returns tuples by
default). The recfile backend has no natural tuple representation, and
named access (`row["stock"]`) is less fragile than index access (`row[2]`)
when schemas evolve. See `COMPAT.md` for the full deviation table.

---

## Decisions and tradeoffs

### Two connection modes: single-file and directory

`recdb.connect()` infers the mode from the path extension — `.rec` for
single-file, anything else for directory. This keeps the API to a single
entry point with no ambiguity.

Single-file is simpler and keeps everything in one place for version
control. Directory mode is better for teams who want to diff individual
tables separately or manage tables with very different lifecycles. The
signal to move from either to SQLite is when you need joins, transactions,
or high write throughput.

### Two recfile backends: GNU recutils and python-recutils

GNU recutils (the subprocess backend) is the primary path. It is faster,
more battle-tested, and handles edge cases in the `.rec` format that
`python-recutils` may not. The `python-recutils` package is an optional
fallback for environments where installing recutils is inconvenient (e.g.
Windows, some CI setups).

The fallback is implemented as a separate module (`pyrecutils_backend.py`)
that the cursor dispatches to when `shutil.which("recsel")` returns `None`.
Both backends share `_expr.py` for expression building so the recsel
expression syntax is generated identically.

The `python-recutils` package is beta quality and has limited uptake. It is
treated as a convenience rather than a fully supported path — users who hit
edge cases are expected to install GNU recutils.

**Version constraint:** `python-recutils` currently requires Python 3.12+.
This is why recdb's own `requires-python` is `>=3.12` and the CI matrix
only tests 3.12. If `python-recutils` drops this constraint in a future
release, recdb could reasonably be tested against 3.10 and 3.11 again —
the core recdb code uses only `str | None` union syntax (3.10+) and no
3.12-specific features.

### Custom exception hierarchy

All recdb errors inherit from `RecDBError` so callers can catch the base
class without catching unrelated `Exception`s:

```
RecDBError
├── SQLParseError         — malformed SQL
├── UnsupportedSQLError   — valid SQL, unsupported feature (JOIN, OR, etc.)
├── RecutilsError         — subprocess non-zero exit
└── RecutilsNotFoundError — neither backend available
```

This mirrors how `sqlite3` raises `sqlite3.Error` subclasses, making it
straightforward to write code that handles both backends gracefully.

### No SQLite wrapper

Earlier versions included a `SQLiteConnection` class that wrapped stdlib
`sqlite3`. It was removed because it introduced subtle behavioural
differences from raw `sqlite3` and added maintenance surface with no real
benefit. `conn.row_factory = sqlite3.Row` already makes rows subscriptable
by column name. The `BaseConnection` / `BaseCursor` ABCs remain as interface
documentation and are used by the test suite to verify that `sqlite3` and
`RecfileConnection` behave the same way across the supported SQL subset.

### No JOIN support

JOIN requires either holding two tables in memory and performing an
application-level join, or a tool that the recutils ecosystem doesn't
provide. More importantly: if your data is naturally relational enough to
need joins, recfiles are probably the wrong storage format. The migration
to SQLite is a one-line change — that's the right answer, not a JOIN
implementation.

For occasional cross-table lookups, the application-side pattern works well
and is demonstrated in `examples/library_demo.py`.

### `sqlparse` as the only mandatory runtime dependency

The parser uses `sqlparse` for tokenisation rather than writing a
hand-rolled tokeniser or pulling in a heavier SQL parser. This keeps the
mandatory dependency footprint to one package. The tradeoff is that
`sqlparse` is a tokeniser/formatter rather than a full parser, so some
constructs require regex fallbacks inside `parser.py` — UPDATE, DELETE,
WHERE, and CREATE TABLE are all parsed with `re.match` after `sqlparse`
hands back the token stream. This is fragile at the edges but has proven
sufficient for the supported SQL subset. If the subset grows significantly
(e.g. adding subqueries, OR, IN), replacing the parser internals with a
grammar-based approach (e.g. `lark`) would be worth considering.

---

## Potential improvements

### Near-term

**`OR` in WHERE clauses**
The recfile backend raises `UnsupportedSQLError` on `OR`. recutils'
expression language supports `||` (logical OR), so this is a parser
addition rather than a fundamental limitation.

**`IN` operator**
`WHERE sku IN ('WGT-001', 'WGT-002')` is common and could be translated
to `recsel -e "sku = 'WGT-001' || sku = 'WGT-002'"`.

**`IS NULL` / `IS NOT NULL`**
recutils supports blank field matching; the parser just needs to handle
the SQL syntax.

**Batch `recset` calls**
`UPDATE SET a=1, b=2` currently makes two `recset` subprocess calls.
recutils supports multiple `-f/-s` pairs in one invocation:
`recset -t table -e expr -f a -s 1 -f b -s 2 file.rec`.
The fix is in `RecfileCursor._update` — accumulate all `-f/-s` pairs
into a single `cmd` list rather than looping with one call per field.
The python-recutils backend (`pyrecutils_backend.update`) has the same
pattern and would need the same fix.

**`rowcount` for UPDATE**
Currently derived via a follow-up `recsel` after `recset` completes.
Capturing the count with a `recsel` *before* the update would be more
correct — count what matches the WHERE clause, apply the change, return
that number. As-is, the count reflects the post-update state which is
usually the same but technically wrong if another writer races in between.
Low priority for the single-user use case.

### Medium-term

**Schema introspection**
`list_tables()` and `describe(table)` — reading `%rec:` and `%type:`
headers from `.rec` files. Useful for tooling and ORMs.

**`LIKE` case-insensitivity**
SQL `LIKE` is case-insensitive by default in most databases. The current
implementation passes the pattern as a case-sensitive recsel regex. Adding
`ILIKE` or a connection-level flag would make this more correct.

**`executescript()`**
Run multiple SQL statements from a string. The recfile backend would need
to split on `;` and execute each. Useful for schema setup from a `.sql`
file shared between backends.

### Longer-term

**Migration helper** *(implemented in v0.2.0)*
`recdb.migrate(src, dst)` copies all data between recfile and SQLite in
either direction, inferring direction from file extensions. Schema is
inferred from `%type:` descriptors or SQLite's `PRAGMA table_info`.
Best-effort — foreign keys, indexes, and constraints are not migrated.

**Connection pooling / thread safety**
The recfile backend is not thread-safe — concurrent writes to the same
`.rec` file via multiple connections would corrupt data. For the target
use case this is acceptable; for anything web-facing, a file lock or
serialisation layer would be needed.
