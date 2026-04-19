# recdb

A PEP 249-style Python DB-API adapter that supports **recfile** behind an python module style interface.
This is intended as an alternative to **SQLite** where human-readable flat file databases is preferred.

## Why?

Recfiles are plain text — human-readable, diffable with `git diff`, editable
with any text editor, queryable with standard Unix tools. For small projects
where textual transparency matters more than performance, they're a compelling
alternative to binary database files.

`recdb` lets you use a simple SQL subset against recfiles while keeping a clean
migration path to SQLite when you outgrow them.

## Installation

```bash
pip install sqlparse       # only dependency beyond stdlib
apt install recutils       # required for the recfile backend
```

## Quickstart

```python
from recdb import connect

# ── Recfile backend (text files, human-readable) ─────────────────────────────
conn = connect("recfile", "./data")       # directory of .rec files

# ── SQLite backend (drop-in swap) ────────────────────────────────────────────
conn = connect("sqlite", "inventory.db")

# ── Identical API from here ──────────────────────────────────────────────────
conn.execute(
    "INSERT INTO items (name, sku, stock, price) VALUES (?, ?, ?, ?)",
    ("Widget", "WGT-001", 50, 9.99)
)
conn.commit()

cur = conn.execute("SELECT * FROM items WHERE stock > 0")
for row in cur.fetchall():
    print(row)  # dict: {'name': 'Widget', 'sku': 'WGT-001', ...}

conn.close()
```

## Context manager

```python
with connect("recfile", "./data") as conn:
    conn.execute("UPDATE items SET stock = 45 WHERE sku = 'WGT-001'")
# commit() called automatically on clean exit
```

## Supported SQL

| Statement                | Example                                                             |
|--------------------------|---------------------------------------------------------------------|
| `SELECT`                 | `SELECT * FROM items`                                               |
| `SELECT` with projection | `SELECT name, stock FROM items`                                     |
| `SELECT` with `WHERE`    | `SELECT * FROM items WHERE stock < 10`                              |
| `INSERT`                 | `INSERT INTO items (name, sku, stock) VALUES ('X', 'X-1', 5)`       |
| `UPDATE`                 | `UPDATE items SET stock = 50 WHERE sku = 'WGT-001'`                 |
| `DELETE`                 | `DELETE FROM items WHERE stock = 0`                                 |
| Parameter binding        | `cursor.execute("SELECT * FROM items WHERE sku = ?", ("WGT-001",))` |

### WHERE clause

- Operators: `=  !=  <  >  <=  >=`
- `AND` between conditions is supported
- `OR`, subqueries, and nesting are **not** supported in the recfile backend
  (AssertionError raised)

### Unsupported (recfile backend raises `AssertionError`)

`JOIN`, `GROUP BY`, `ORDER BY`, `LIMIT`, `UNION`, `HAVING`, subqueries.

## Recfile schema

Each table maps to a `.rec` file in your data directory. You can add type
hints and constraints using standard recutils directives:

```
%rec: items
%mandatory: name sku stock price
%type: stock int
%type: price real

name: Widget A
sku: WGT-001
stock: 120
price: 9.99
```

## File layout

```
recdb/
├── src/recdb/
│   ├── __init__.py     # connect() entry point
│   ├── base.py         # BaseConnection / BaseCursor ABCs
│   ├── parser.py       # SQL → AST translator (used by recfile backend)
│   ├── recfile.py      # RecfileConnection / RecfileCursor
├── data/
│   └── items.rec       # sample inventory data
└── inventory_demo.py   # demo: runs both backends side by side
```

## Running the demo

```bash
python inventory_demo.py          # runs both backends
RECDB_BACKEND=recfile python inventory_demo.py
RECDB_BACKEND=sqlite  python inventory_demo.py
```
