#!/usr/bin/env python3
"""
examples/library_demo.py
~~~~~~~~~~~~~~~~~~~~~~~~
A small library system demonstrating recdb with two related tables
(books and borrowers) across three connection modes:

    recfile      — single .rec file, both tables as %rec: blocks
    recfile-dir  — directory mode, one .rec file per table
    sqlite       — stdlib sqlite3, same application code

Usage
-----
    python examples/library_demo.py                    # all three modes
    DBTYPE=recfile      python examples/library_demo.py
    DBTYPE=recfile-dir  python examples/library_demo.py   # directory mode
    DBTYPE=sqlite       python examples/library_demo.py

    # Write data to a real directory you can inspect afterwards:
    DBPATH=/tmp/library python examples/library_demo.py

The application code inside run() is identical for all three — that's
the point.  Each mode produces the same printed output.
"""

import os
import sqlite3
import tempfile
import recdb

# ── Seed data ──────────────────────────────────────────────────────────────

BOOKS = [
    # (isbn,           title,                              author,             year, copies)
    ("978-0-7432-7356-5", "The Road",                     "Cormac McCarthy",  2006, 3),
    ("978-0-14-028329-7", "Slaughterhouse-Five",          "Kurt Vonnegut",    1969, 2),
    ("978-0-06-112008-4", "To Kill a Mockingbird",        "Harper Lee",       1960, 4),
    ("978-0-14-303943-3", "Norwegian Wood",               "Haruki Murakami",  1987, 2),
    ("978-0-7432-7357-2", "Blood Meridian",               "Cormac McCarthy",  1985, 1),
    ("978-0-14-028335-8", "Cat's Cradle",                 "Kurt Vonnegut",    1963, 3),
]

BORROWERS = [
    # (member_id, name,              email,                        books_out)
    ("M001", "Alice Nguyen",    "alice@example.com",          0),
    ("M002", "Bob Okafor",      "bob@example.com",            0),
    ("M003", "Clara Johansson", "clara@example.com",          0),
    ("M004", "David Kim",       "david@example.com",          0),
]

# ── Schema ─────────────────────────────────────────────────────────────────

CREATE_BOOKS = """
    CREATE TABLE IF NOT EXISTS books (
        isbn    TEXT NOT NULL,
        title   TEXT NOT NULL,
        author  TEXT NOT NULL,
        year    INTEGER NOT NULL,
        copies  INTEGER NOT NULL
    )
"""

CREATE_BORROWERS = """
    CREATE TABLE IF NOT EXISTS borrowers (
        member_id TEXT NOT NULL,
        name      TEXT NOT NULL,
        email     TEXT NOT NULL,
        books_out INTEGER NOT NULL
    )
"""

INSERT_BOOK = """
    INSERT INTO books (isbn, title, author, year, copies)
    VALUES (?, ?, ?, ?, ?)
"""

INSERT_BORROWER = """
    INSERT INTO borrowers (member_id, name, email, books_out)
    VALUES (?, ?, ?, ?)
"""

# ── Formatting helpers ──────────────────────────────────────────────────────

W = 66

def section(title: str):
    print(f"\n{'─' * W}")
    print(f"  {title}")
    print(f"{'─' * W}")

def fmt_book(row) -> str:
    return (
        f"  {str(row['isbn']):<22}"
        f"  {str(row['title']):<36}"
        f"  {str(row['author']):<20}"
        f"  {int(row['year'])}"
        f"  copies={int(row['copies'])}"
    )

def fmt_borrower(row) -> str:
    return (
        f"  {str(row['member_id']):<6}"
        f"  {str(row['name']):<20}"
        f"  {str(row['email']):<28}"
        f"  books_out={int(row['books_out'])}"
    )

# ── Application logic — identical for all three connection modes ────────────

def run(conn, label: str):
    print(f"\n{'═' * W}")
    print(f"  {label}")
    print(f"{'═' * W}")

    # ── Setup ───────────────────────────────────────────────────────────────
    conn.execute(CREATE_BOOKS)
    conn.execute(CREATE_BORROWERS)
    conn.executemany(INSERT_BOOK, BOOKS)
    conn.executemany(INSERT_BORROWER, BORROWERS)
    conn.commit()

    # ── Basic selects ───────────────────────────────────────────────────────
    section("All books")
    for row in conn.execute("SELECT * FROM books").fetchall():
        print(fmt_book(row))

    section("All borrowers")
    for row in conn.execute("SELECT * FROM borrowers").fetchall():
        print(fmt_borrower(row))

    # ── Filtered queries ────────────────────────────────────────────────────
    section("Books by Cormac McCarthy")
    for row in conn.execute(
        "SELECT * FROM books WHERE author = 'Cormac McCarthy'"
    ).fetchall():
        print(fmt_book(row))

    section("Books published before 1970")
    for row in conn.execute(
        "SELECT * FROM books WHERE year < 1970"
    ).fetchall():
        print(fmt_book(row))

    section("Books LIKE '%Wood%'")
    for row in conn.execute(
        "SELECT * FROM books WHERE title LIKE '%Wood%'"
    ).fetchall():
        print(fmt_book(row))

    section("Top 3 books by year DESC")
    for row in conn.execute(
        "SELECT * FROM books ORDER BY year DESC LIMIT 3"
    ).fetchall():
        print(fmt_book(row))

    # ── Simulated checkout: Alice borrows The Road ──────────────────────────
    section("Checkout: Alice borrows 'The Road'")
    conn.execute(
        "UPDATE borrowers SET books_out = 1 WHERE member_id = 'M001'"
    )
    conn.execute(
        "UPDATE books SET copies = 2 WHERE isbn = '978-0-7432-7356-5'"
    )
    conn.commit()

    alice = conn.execute(
        "SELECT * FROM borrowers WHERE member_id = 'M001'"
    ).fetchone()
    road  = conn.execute(
        "SELECT * FROM books WHERE isbn = '978-0-7432-7356-5'"
    ).fetchone()
    print(fmt_borrower(alice))
    print(fmt_book(road))

    # ── Manual join: borrowers with books out, look up books_out > 0 ────────
    # recdb doesn't support JOIN — application-side join shown explicitly
    section("Active borrowers (books_out > 0)  — application-side join")
    active = conn.execute(
        "SELECT * FROM borrowers WHERE books_out > 0"
    ).fetchall()
    for b in active:
        books_out = int(b["books_out"])
        print(f"  {b['name']} has {books_out} book(s) checked out")

    # ── INSERT a new book ────────────────────────────────────────────────────
    section("INSERT new book: Breakfast of Champions")
    conn.execute(INSERT_BOOK, (
        "978-0-385-33420-6", "Breakfast of Champions",
        "Kurt Vonnegut", 1973, 2
    ))
    conn.commit()
    new_book = conn.execute(
        "SELECT * FROM books WHERE isbn = '978-0-385-33420-6'"
    ).fetchone()
    print(f"  Added: {fmt_book(new_book)}")

    # ── Query all Vonnegut after insert ─────────────────────────────────────
    section("All Vonnegut titles (after insert)")
    for row in conn.execute(
        "SELECT * FROM books WHERE author = 'Kurt Vonnegut' ORDER BY year"
    ).fetchall():
        print(fmt_book(row))

    # ── Return: Alice returns The Road ──────────────────────────────────────
    section("Return: Alice returns 'The Road'")
    conn.execute(
        "UPDATE borrowers SET books_out = 0 WHERE member_id = 'M001'"
    )
    conn.execute(
        "UPDATE books SET copies = 3 WHERE isbn = '978-0-7432-7356-5'"
    )
    conn.commit()

    # ── DELETE books with only 1 copy (low-stock cull) ──────────────────────
    section("DELETE books with copies = 1")
    before = conn.execute("SELECT * FROM books").fetchall()
    conn.execute("DELETE FROM books WHERE copies = 1")
    conn.commit()
    after = conn.execute("SELECT * FROM books").fetchall()
    print(f"  Before: {len(before)} books   After: {len(after)} books")
    print("  Remaining:")
    for row in after:
        print(fmt_book(row))

    conn.close()


# ── Entry point ─────────────────────────────────────────────────────────────

def sqlite_conn(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    db_type   = os.environ.get("DBTYPE", "both").lower()
    db_path = os.environ.get("DBPATH", None)

    def go(tmp: str):
        if db_type in ("recfile", "both"):
            run(
                recdb.connect(os.path.join(tmp, "library.rec")),
                "RECFILE  (single file — library.rec)"
            )

        if db_type in ("recfile-dir", "both"):
            run(
                recdb.connect(os.path.join(tmp, "library_dir")),
                "RECFILE DIR  (library_dir/books.rec + library_dir/borrowers.rec)"
            )

        if db_type in ("sqlite", "both"):
            run(
                sqlite_conn(os.path.join(tmp, "library.db")),
                "SQLITE  (stdlib sqlite3)"
            )

    if db_path:
        os.makedirs(db_path, exist_ok=True)
        go(db_path)
        print(f"\n  Data written to: {db_path}")
        print(f"  Inspect with:   cat {db_path}/library.rec")
        print(f"                  cat {db_path}/library_dir/books.rec")
        print(f"                  cat {db_path}/library_dir/borrowers.rec")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            go(tmp)
