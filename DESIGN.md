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
few line changes and a python module import.

---

## Architecture

```
Application code
      │
      ├── recdb.connect("inventory.rec")     ← single-file mode
      │         │
      │         ▼
      │   BaseConnection (ABC)    ← documents the sqlite3-compatible interface
      │   BaseCursor (ABC)
      │         │
      │         └── RecfileConnection   ← GNU recutils subprocess calls
      │             ├── default_table = file stem (single-file mode)
      │             └── RecfileCursor
      │                 └── parser.py  ← SQL subset → AST → recutils args
      │
      ├── recdb.connect_dir("./data")        ← directory mode
      │         │
      │         │
      │         └── RecfileConnection (same class, no default_table)
      │             ├── default_table = None   (directory mode)
      │             └── RecfileCursor
      │                 └── parser.py  ← SQL subset → AST → recutils args
      │
      └── sqlite3.connect("inventory.db")   ← stdlib, used directly by callers
              conn.row_factory = sqlite3.Row
```

### Backend selection

`recdb.connect()` only accepts `.rec` files and raises `ValueError` for
anything else.

The `BaseConnection` / `BaseCursor` ABCs in `base.py` document the
interface that both `RecfileConnection` and raw `sqlite3` satisfy, so
the test suite can run the same operations against both and assert
identical results.

### The parser

The SQL parser (`parser.py`) is used **only** by the recfile backend.
SQLite receives SQL verbatim and handles it natively.

The parser uses `sqlparse` for tokenisation, then translates the AST into
recutils CLI arguments. It deliberately supports a small subset:

```
SELECT [cols] FROM table [WHERE expr] [ORDER BY col [ASC|DESC]] [LIMIT n]
INSERT INTO table (cols) VALUES (vals)
UPDATE table SET col=val [WHERE expr]
DELETE FROM table [WHERE expr]
CREATE TABLE [IF NOT EXISTS] table (col type ...)
```

Anything outside this subset raises `AssertionError` with a descriptive message. 
This is intentionally aggressive: unsupported SQL should fail immediately rather
than degrade into partial or incorrect results.

### recutils mapping

| SQL                          | recutils                                         |
|------------------------------|--------------------------------------------------|
| `SELECT ... WHERE x = 'y'`   | `recsel -e "x = 'y'"`                            |
| `SELECT ... ORDER BY x`      | `recsel -S x`                                    |
| `SELECT ... ORDER BY x DESC` | `recsel -S x` + Python `reversed()`              |
| `SELECT ... LIMIT n`         | `recsel -m n`                                    |
| `WHERE name LIKE 'A%'`       | `recsel -e "name ~ 'A.*'"`                       |
| `INSERT`                     | `recins -f col -v val`                           |
| `UPDATE ... SET x=y`         | `recset -f x -s y` (one call per field)          |
| `DELETE`                     | `recdel [-e expr] [--force]`                     |
| `CREATE TABLE`               | writes `%rec:` / `%type:` / `%mandatory:` header |

**Known recutils 1.9 limitations:**
- `recsel` sorts ascending only; DESC is emulated by reversing in Python.
- `recset` takes one field per call, so `UPDATE SET a=1, b=2` makes two
  subprocess calls.
- `recdel --force` is required to delete all records of a typed set (no
  expression).
- `-R` in recsel means "print-row", not "reverse" — we avoid it.

### Rows as dicts

The backend return rows as `dict` rather than `tuple`. This is a
deliberate deviation from stdlib `sqlite3` (which returns tuples by
default). The recfile backend has no natural tuple representation, and
named access (`row["stock"]`) is less fragile than index access (`row[2]`)
when schemas evolve. See `COMPAT.md` for the full deviation table.

---

## Decisions and tradeoffs

### Two connection modes: single-file and directory

**Single-file mode** (`recdb.connect("inventory.rec")`) points to one `.rec`
file. Multiple tables are supported within that file via recutils' native
multi-type format (multiple `%rec:` blocks). This is the recommended mode for
most projects and mirrors the `sqlite3.connect()` call exactly.

**Directory mode** (`recdb.connect_dir("./data")`) maps each table to a
separate `.rec` file in the directory — `SELECT * FROM items` reads
`./data/items.rec`, `SELECT * FROM orders` reads `./data/orders.rec`, and so
on. The directory is created if it does not exist.

Directory mode uses the same `RecfileConnection` class with `default_table=None`.
The two entry points keep the APIs unambiguous: `connect()` only accepts a
`.rec` path, and `connect_dir()` only accepts a directory path.

The tradeoffs between modes:

- Single-file is simpler and keeps everything in one place for version control.
- Directory mode is better for teams who want to diff individual tables
  separately or manage tables with very different lifecycles.
- The signal to move from either recfile mode to SQLite is when you need
  joins, transactions, or high write throughput — at that point the switch
  is a one-line change.

### `assert` instead of a custom exception hierarchy

Unsupported SQL raises `AssertionError` with a descriptive message. A
custom `UnsupportedSQLError` would be cleaner for library consumers who
want to catch it specifically, but adds an API surface to maintain. This
is worth revisiting before a 1.0 release.

### `sqlparse` as the only runtime dependency

The parser uses `sqlparse` for tokenisation rather than writing a
hand-rolled tokeniser or pulling in a heavier SQL parser. This keeps the
dependency footprint minimal. The tradeoff is that `sqlparse` is a
tokeniser/formatter, not a full parser, so some constructs require regex
fallbacks. If the SQL subset grows significantly, replacing the parser
internals with a grammar-based approach (e.g. `lark`) would be worth
considering.

### subprocess for recutils

The recfile backend shells out to `recsel`, `recins`, `recset`, `recdel`
rather than parsing `.rec` files directly in Python. This means:

- recutils must be installed separately (`apt install recutils` / `brew install recutils`).
- Each operation has subprocess overhead (~5–20ms per call).
- `UPDATE` with multiple fields makes one subprocess call per field.

For the target use case (small datasets, infrequent writes) the subprocess
overhead is acceptable. See the *Pure Python `.rec` backend* section below
for the considered alternative.

### No SQLite wrapper

Earlier versions of recdb included a `SQLiteConnection` class that wrapped
stdlib `sqlite3` to return dicts instead of tuples. It was removed because:

- It introduced subtle behavioural differences from raw `sqlite3` that could
  surprise callers (e.g. `rowcount` after SELECT, context manager semantics).
- Wrapping a stdlib module that already works correctly adds maintenance
  surface with no real benefit.
- `conn.row_factory = sqlite3.Row` already makes `sqlite3` rows
  subscriptable by column name — close enough for application code that
  uses key access rather than index access.

The `BaseConnection` / `BaseCursor` ABCs remain as interface documentation
and are used by the test suite to verify that `sqlite3` and `RecfileConnection`
behave the same way against the supported SQL subset.

---

## Potential improvements

These are known limitations worth addressing as the project matures.
They're left for future contributors rather than pre-optimised.

### Near-term

**Custom exception type**
Replace `AssertionError` with a `RecDBError` (or `UnsupportedError`)
so callers can catch recdb-specific errors without catching all
`AssertionError`s in their program.

**`OR` in WHERE clauses**
The recfile backend currently asserts on `OR`. recutils' expression
language supports `||` (logical OR), so this is a parser addition rather
than a fundamental limitation.

**`IN` operator**
`WHERE sku IN ('WGT-001', 'WGT-002')` is common and could be translated
to `recsel -e "sku = 'WGT-001' || sku = 'WGT-002'"`.

**`IS NULL` / `IS NOT NULL`**
recutils supports blank field matching; the parser just needs to handle
the SQL syntax.

**`rowcount` for UPDATE**
Currently derived via a follow-up `SELECT` after `recset`. recutils
doesn't report affected rows, but the count could be captured before
the update instead, which is slightly more correct under concurrent access.

### Medium-term

**Pure Python `.rec` backend**
Removing the subprocess dependency would make recdb installable on
systems without recutils (e.g. Windows without WSL) and eliminate
per-call subprocess overhead.

Two existing PyPI packages were evaluated as potential foundations:

- **`python-recutils` (0.2.0)** — a pure Python reimplementation of the
  GNU recutils tools. It exposes `recsel()`, `recins()`, `recset()`,
  `recdel()` as Python functions that operate on in-memory strings
  (read file → transform string → write file back). The API is close
  enough to map onto recdb's existing structure. However: it has 1 star
  on GitHub, no published releases, and shows signs of being an
  unmaintained personal project. Taking it as a dependency would expose
  users to its abandonment.

- **`recfile` (0.41)** — fails to build; appears to require `librec`
  (the GNU C library) to be installed, so it has the same system
  dependency problem as the subprocess approach, arguably worse.

**Recommendation:** if the subprocess dependency becomes a real obstacle
(e.g. Windows support is needed), write a minimal pure-Python `.rec`
parser rather than depending on either package. The `.rec` format is
simple enough — field lines (`Key: Value`), blank-line record separators,
`%rec:` / `%type:` / `%mandatory:` descriptor blocks — that a parser
covering recdb's needs is a few hundred lines. The operation model would
follow `python-recutils`: read the file to a string, transform, write back.
The `_parse_recsel_output()` function in `recfile.py` is already a partial
implementation of the reader side.

**`LIKE` case-insensitivity option**
SQL `LIKE` is case-insensitive by default in most databases. The current
implementation passes the pattern as a case-sensitive recsel regex.
Adding `ILIKE` or a connection-level flag would make this correct.

**Schema introspection**
`list_tables()` and `describe(table)` — reading `%rec:` and `%type:`
headers from `.rec` files. Useful for tooling and ORMs.

**Batch `recset` calls**
`UPDATE SET a=1, b=2` currently makes two `recset` subprocess calls.
recutils supports multiple `-f/-s` pairs in one call; the backend just
needs to build the command correctly.

**Lightweight index files**
recdb currently performs a full scan of the `.rec` file for `SELECT`
queries with a `WHERE` clause. For the intended use case (small datasets),
this is acceptable and keeps the implementation simple.

However, for larger recfiles a lightweight indexing mechanism could
significantly reduce lookup time for common queries such as:

    SELECT * FROM items WHERE sku = 'WGT-001'

One possible approach would be a sidecar index file:

    inventory.rec
    inventory.rec.idx

The index file could store a mapping of indexed fields to record
positions, for example:

```json
{
  "indexed_fields": ["sku"],
  "fields": {
    "sku": {
      "WGT-001": [0],
      "WGT-002": [3]
    }
  }
}
```

When executing a query with a simple equality predicate, the backend
could consult the index to obtain candidate record positions rather
than scanning the entire file.

This approach has several advantages:

- preserves the `.rec` file as the canonical human-readable source
- keeps indexing optional and easy to rebuild
- avoids introducing a full database engine
- maintains compatibility with manual editing and Git workflows

Index maintenance could be handled by rebuilding the index after any
write operation (`INSERT`, `UPDATE`, `DELETE`). Given the small dataset
sizes recdb targets, rebuilding the index is often simpler and safer
than attempting incremental updates.

This optimisation is intentionally not implemented in the current
version because:

- it adds complexity to a deliberately minimal project
- many datasets will never grow large enough to benefit
- the recommended upgrade path for larger datasets is switching to
  SQLite

Future contributors interested in improving query performance without
changing recdb’s core philosophy may find this a reasonable extension.

### Longer-term

**Migration helper**
`recdb.migrate("inventory.rec", "inventory.db")` — copy all data from
one backend to the other. Makes the "graduated to SQLite" transition
explicit and safe.

**`executescript()`**
Run multiple SQL statements from a string. The recfile backend would need
to split on `;` and execute each. Useful for schema setup from a `.sql`
file shared between backends.

**Connection pooling / thread safety**
The recfile backend is currently not thread-safe (concurrent writes to
the same `.rec` file via multiple connections would corrupt data). For
the target use case this is acceptable; for anything web-facing, a
file lock or serialisation layer would be needed.
