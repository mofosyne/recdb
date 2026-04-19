# sqlite3 compatibility

recdb's `RecfileConnection` implements the same interface as stdlib `sqlite3`
so application code works unchanged against either backend.

## Switching

```python
# recfile backend
import recdb
conn = recdb.connect("inventory.rec")

# SQLite — use stdlib directly, no wrapper needed
import sqlite3
conn = sqlite3.connect("inventory.db")
conn.row_factory = sqlite3.Row   # makes rows subscriptable by column name
```

From there, `execute()`, `executemany()`, `fetchone()`, `fetchall()`,
`fetchmany()`, `commit()`, `rollback()`, `close()`, and the context manager
all work identically.

## Differences to be aware of

| Behaviour                      | recdb                        | stdlib sqlite3                                       |
|--------------------------------|------------------------------|------------------------------------------------------|
| Row type                       | `dict`                       | `tuple` by default; `sqlite3.Row` with `row_factory` |
| `isinstance(row, dict)`        | `True`                       | `False` (even with `row_factory`)                    |
| `cursor.rowcount` after SELECT | `len(rows)`                  | `-1`                                                 |
| `commit()` / `rollback()`      | no-op (writes are immediate) | transactional                                        |
| Context manager `__exit__`     | commits **and closes**       | commits only                                         |

## Row access style

Use column names, not indices — this works with both recdb dicts and
`sqlite3.Row` objects:

```python
# Works with both
name = row["name"]

# Breaks with recdb (dict doesn't support index access like this)
name = row[0]
```

## The test suite as a compatibility reference

`tests/test_recdb.py` runs the same SQL operations against both backends
using a parametrised pytest fixture. If a new operation passes both, it's
safe to use in application code that may switch backends.
