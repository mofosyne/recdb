#!/usr/bin/env python3
"""
examples/inventory_demo.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs the same inventory operations against recfile and stdlib sqlite3,
demonstrating that application code is identical between the two.

    python examples/inventory_demo.py              # both
    RECDB_BACKEND=recfile python examples/...
    RECDB_BACKEND=sqlite  python examples/...
"""

import os
import sqlite3
import tempfile
import recdb


def sqlite_conn(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def section(title: str):
    print(f"\n{'─' * 58}")
    print(f"  {title}")
    print(f"{'─' * 58}")


def fmt_row(row) -> str:
    return (
        f"  {row['sku']:<10}"
        f"  {row['name']:<20}"
        f"  stock={row['stock']:<5}"
        f"  £{float(row['price']):.2f}"
        f"  [{row['category']}]"
    )


# ── This function is identical for both backends ───────────────────────────
def run(conn, label: str):
    print(f"\n{'═' * 58}")
    print(f"  {label}")
    print(f"{'═' * 58}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            name     TEXT NOT NULL,
            sku      TEXT NOT NULL,
            stock    INTEGER NOT NULL,
            price    REAL NOT NULL,
            category TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        [
            ("Widget A",    "WGT-001", 120,  9.99,  "widgets"),
            ("Widget B",    "WGT-002",  45, 14.99,  "widgets"),
            ("Gadget Pro",  "GAD-001",   8, 49.99,  "gadgets"),
            ("Gadget Lite", "GAD-002",   0, 24.99,  "gadgets"),
            ("Doohickey",   "DOO-001", 200,  2.49,  "misc"),
        ]
    )
    conn.commit()

    section("All items")
    for row in conn.execute("SELECT * FROM items").fetchall():
        print(fmt_row(row))

    section("Low stock  (stock < 10)")
    for row in conn.execute("SELECT * FROM items WHERE stock < 10").fetchall():
        print(fmt_row(row))

    section("Search  LIKE 'Widget%'")
    for row in conn.execute("SELECT * FROM items WHERE name LIKE 'Widget%'").fetchall():
        print(fmt_row(row))

    section("Top 3 by stock DESC")
    for row in conn.execute("SELECT * FROM items ORDER BY stock DESC LIMIT 3").fetchall():
        print(fmt_row(row))

    section("INSERT")
    conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("Super Thingamajig", "STJ-001", 75, 19.99, "misc")
    )
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE sku = ?", ("STJ-001",)).fetchone()
    print(f"  Inserted: {fmt_row(row)}")

    section("UPDATE  Gadget Pro stock → 50")
    conn.execute("UPDATE items SET stock = 50 WHERE sku = 'GAD-001'")
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE sku = ?", ("GAD-001",)).fetchone()
    print(f"  After: {fmt_row(row)}")

    section("DELETE  WHERE stock = 0")
    conn.execute("DELETE FROM items WHERE stock = 0")
    conn.commit()
    remaining = conn.execute("SELECT * FROM items").fetchall()
    print(f"  Remaining: {len(remaining)} items")

    conn.close()


if __name__ == "__main__":
    backend = os.environ.get("RECDB_BACKEND", "both").lower()

    with tempfile.TemporaryDirectory() as tmp:
        if backend in ("recfile", "both"):
            run(recdb.connect(os.path.join(tmp, "inventory.rec")), "RECFILE")

        if backend in ("sqlite", "both"):
            run(sqlite_conn(os.path.join(tmp, "inventory.db")), "SQLITE  (stdlib sqlite3)")
