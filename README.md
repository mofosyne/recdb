# recdb

A PEP 249-style Python DB-API adapter for **GNU recfiles** — plain-text, human-readable, `git diff`-able databases.

[Wikipedia: Recutils / Recfiles](https://en.wikipedia.org/wiki/Recutils)

## Why?

Recfiles are plain text — human-readable, diffable with `git diff`, editable with any text editor, queryable with standard Unix tools. For small projects where textual transparency matters more than performance, they're a compelling alternative to a binary database file like SQLite.

`recdb` lets you use a familiar SQL subset against recfiles, with a clean one-line migration path to SQLite when you outgrow them.

## Installation

```bash
pip install recdb
apt install recutils        # or: brew install recutils
```

## Quickstart

```python
# ── Recfile backend (plain text, human-readable) ──────────────────────────────
import recdb
conn = recdb.connect("inventory.rec")

# ── SQLite backend as an example of migration from Recfile ──────────────────
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

Switching from recfile to SQLite is a one-line change — replace `recdb.connect("inventory.rec")` with `sqlite3.connect("inventory.db")` and the rest of your code stays the same.

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

### WHERE clause operators support

`=  !=  <  >  <=  >=  LIKE  AND`

`OR`, `IN`, subqueries, `JOIN`, `GROUP BY`, `UNION`, and `HAVING` are not currently supported in the recfile backend (raises `AssertionError`).

## File layout

`recdb.connect()` takes a path to a single `.rec` file.

Multiple tables are supported within one file using recutils' native multi-type format — multiple `%rec:` blocks in a single file.

Example `.rec` file with two tables:

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

## Requirements

- Python 3.9+
- `sqlparse` (installed automatically via pip)
- GNU `recutils` (`recsel`, `recins`, `recset`, `recdel`) installed separately

## Stability and 1.0 release

RecDB is a hobby project without a fixed release schedule. The 1.0 release will be considered when the project has been used successfully in other projects over time. Until then, minor versions may include breaking changes.

## Known users / projects

**Send a PR to add your project here — this helps track readiness for v1.0.**
