# recdb

A PEP 249-style Python DB-API adapter for **GNU recfiles** — plain-text, human-readable, `git diff`-able databases.

[Wikipedia: Recutils / Recfiles](https://en.wikipedia.org/wiki/Recutils)

## Why?

Recfiles are plain text — human-readable, diffable with `git diff`, editable with any text editor, queryable with standard Unix tools. For small projects where textual transparency matters more than performance, they're a compelling alternative to a binary database file like SQLite.

`recdb` lets you use a familiar SQL subset against recfiles, with a clean one-line migration path to SQLite when you outgrow them.

## Installation

```bash
pip install recdb
```

recdb needs at least one of the following backends to operate:

| Backend         | Install                                           | Capability              |
|-----------------|---------------------------------------------------|-------------------------|
| GNU recutils    | `apt install recutils` or `brew install recutils` | Read + write            |
| python-recutils | `pip install recdb[recutils]`                     | Read + write (fallback) |

GNU recutils is recommended — it is faster and more battle-tested. The `python-recutils` fallback is useful on platforms where installing recutils is inconvenient (e.g. Windows, CI environments). If both are installed, GNU recutils takes precedence.

## Quickstart

```python
import recdb

# ── Single-file mode — path ends in .rec ─────────────────────────────────────
conn = recdb.connect("inventory.rec")       # all tables in one file

# ── Directory mode — path has no .rec extension ───────────────────────────────
conn = recdb.connect("./data")              # items → ./data/items.rec, etc.

# ── SQLite backend (use stdlib directly — no wrapper needed) ──────────────────
import sqlite3
conn = sqlite3.connect("inventory.db")

# ── Identical API from here ───────────────────────────────────────────────────
conn.execute(
    "INSERT INTO items (name, sku, stock, price) VALUES (?, ?, ?, ?)",
    ("Widget", "WGT-001", 50, 9.99)
)
conn.commit()

cur = conn.execute("SELECT * FROM items WHERE stock > 0")
for row in cur.fetchall():
    print(row["name"], row["stock"])

conn.close()
```

Switching from either recfile mode to SQLite is a one-line change — replace `recdb.connect(...)` with `sqlite3.connect("inventory.db")` and the rest of your code stays the same.

## Context manager

```python
with recdb.connect("inventory.rec") as conn:
    conn.execute("UPDATE items SET stock = 45 WHERE sku = 'WGT-001'")
# commit() called automatically on clean exit
```

## Supported SQL

| Statement         | Example                                                             |
|-------------------|---------------------------------------------------------------------|
| `SELECT`          | `SELECT * FROM items`                                               |
| Column projection | `SELECT name, stock FROM items`                                     |
| `WHERE`           | `SELECT * FROM items WHERE stock < 10`                              |
| `ORDER BY`        | `SELECT * FROM items ORDER BY price DESC`                           |
| `LIMIT`           | `SELECT * FROM items LIMIT 5`                                       |
| `INSERT`          | `INSERT INTO items (name, sku, stock) VALUES ('X', 'X-1', 5)`       |
| `UPDATE`          | `UPDATE items SET stock = 50 WHERE sku = 'WGT-001'`                 |
| `DELETE`          | `DELETE FROM items WHERE stock = 0`                                 |
| `CREATE TABLE`    | `CREATE TABLE items (name text, sku text, stock int, price real)`   |
| Parameter binding | `cursor.execute("SELECT * FROM items WHERE sku = ?", ("WGT-001",))` |

### WHERE clause operators

`=  !=  <  >  <=  >=  LIKE  AND`

`OR`, `IN`, subqueries, `JOIN`, `GROUP BY`, `UNION`, and `HAVING` are not supported in the recfile backend and will raise `UnsupportedSQLError`. If you need any of these, it is a good signal to switch to SQLite — the migration is a one-line change.

### Joins

recdb does not support JOIN. Recfiles are designed for independent, self-contained record sets — the recutils tooling has no join primitive. If your data is naturally relational (foreign keys, many-to-many), you will be better served by SQLite from the start.

For occasional cross-table lookups, the application-side join pattern works fine:

```python
# Find all books currently checked out, then look up each borrower
checked_out = conn.execute("SELECT * FROM books WHERE checked_out_by != ''").fetchall()
for book in checked_out:
    borrower = conn.execute(
        "SELECT * FROM borrowers WHERE member_id = ?", (book["checked_out_by"],)
    ).fetchone()
    print(f"{book['title']} → {borrower['name']}")
```

## File layout

recdb supports two file layouts:

**Single-file mode** — one `.rec` file holds all tables as separate `%rec:` blocks:

```
project/
├── inventory.rec    # %rec: items block + %rec: suppliers block + ...
└── app.py
```

```python
conn = recdb.connect("inventory.rec")
conn.execute("SELECT * FROM items")
conn.execute("SELECT * FROM suppliers")
```

**Directory mode** — each table gets its own `.rec` file:

```
project/
├── data/
│   ├── items.rec
│   └── suppliers.rec
└── app.py
```

```python
conn = recdb.connect("./data")
conn.execute("SELECT * FROM items")      # → ./data/items.rec
conn.execute("SELECT * FROM suppliers")  # → ./data/suppliers.rec
```

Example `.rec` file content:

```
%rec: items
%mandatory: name sku stock price
%type: stock int
%type: price real

name: Widget A
sku: WGT-001
stock: 120
price: 9.99

name: Widget B
sku: WGT-002
stock: 5
price: 14.50

%rec: suppliers
%mandatory: name contact

name: Acme Corp
contact: acme@example.com
```

## Rows are dicts

The recfile backend returns rows as `dict`. Column access by name is always safe:

```python
row = cur.fetchone()
print(row["name"])    # works
print(row["stock"])   # works
```

See [COMPATIBILITY.md](COMPATIBILITY.md) for a full table of deviations from stdlib `sqlite3`.

## Exceptions

All recdb errors inherit from `recdb.RecDBError`:

```python
import recdb

try:
    conn.execute("SELECT * FROM items JOIN orders ON ...")
except recdb.UnsupportedSQLError:
    # JOIN not supported — switch to SQLite or use application-side join
    ...
except recdb.RecutilsNotFoundError:
    # Neither GNU recutils nor python-recutils is installed
    ...
except recdb.RecDBError:
    # Catch-all for any recdb error
    ...
```

| Exception               | Raised when                                                          |
|-------------------------|----------------------------------------------------------------------|
| `RecDBError`            | Base class for all recdb errors                                      |
| `SQLParseError`         | SQL cannot be parsed (syntax error, column/value count mismatch)     |
| `UnsupportedSQLError`   | Valid SQL that the recfile backend does not support (JOIN, OR, etc.) |
| `RecutilsError`         | A recutils subprocess exited with a non-zero return code             |
| `RecutilsNotFoundError` | Neither GNU recutils nor python-recutils is available                |

## When to switch to SQLite

recdb is a good fit when your data is:
- Small enough to read comfortably in a text editor
- Stored in git alongside the code that uses it
- Rarely queried relationally (no JOINs, or simple application-side lookups)

Switch to SQLite when you need:
- JOINs or complex relational queries
- Concurrent writers
- High write throughput
- Referential integrity enforcement

The switch is a one-line code change. That is intentional.

## Requirements

- Python 3.9+
- `sqlparse` (installed automatically)
- At least one of: GNU recutils (`apt install recutils` / `brew install recutils`) or `python-recutils` (`pip install recdb[recutils]`)

## Stability and 1.0 release

RecDB is a hobby project without a fixed release schedule. The 1.0 release will be considered when the project has been used successfully in other projects over time. Until then, minor versions may include breaking changes.

## Known users / projects

**Send a PR to add your project here — this helps track readiness for v1.0.**
