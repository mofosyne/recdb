"""
tests/test_recdb.py
~~~~~~~~~~~~~~~~~~~
Test suite for recdb.

Structure
---------
- ``conn`` fixture is parametrised over both backends so every shared test
  runs against recfile AND stdlib sqlite3.
- Tests that assert behaviour specific to one backend are marked with
  ``pytest.mark`` or placed in dedicated sections.
- Row access always uses key names (``row["stock"]``), never index
  (``row[0]``), since that's the common subset of recdb dicts and
  sqlite3.Row objects.

Run with:  just test
"""

import sqlite3
import pytest
import recdb

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

SEED = [
    ("Widget A",    "WGT-001", 120,  9.99,  "widgets"),
    ("Widget B",    "WGT-002",  45, 14.99,  "widgets"),
    ("Gadget Pro",  "GAD-001",   8, 49.99,  "gadgets"),
    ("Gadget Lite", "GAD-002",   0, 24.99,  "gadgets"),
    ("Doohickey",   "DOO-001", 200,  2.49,  "misc"),
]

CREATE = """
    CREATE TABLE IF NOT EXISTS items (
        name     TEXT NOT NULL,
        sku      TEXT NOT NULL,
        stock    INTEGER NOT NULL,
        price    REAL NOT NULL,
        category TEXT
    )
"""

INSERT = "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)"


def sqlite_conn(path: str):
    """Open a raw sqlite3 connection configured to match recdb's interface."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row   # makes rows subscriptable by column name
    return conn


@pytest.fixture(params=["recfile", "sqlite"])
def conn(request, tmp_path):
    """
    Parametrised fixture — runs every test against both backends.
    recfile uses recdb.connect(); sqlite uses stdlib sqlite3 directly.
    """
    if request.param == "recfile":
        c = recdb.connect(str(tmp_path / "items.rec"))
    else:
        c = sqlite_conn(str(tmp_path / "inventory.db"))

    c.execute(CREATE)
    c.executemany(INSERT, SEED)
    c.commit()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# SELECT — shared (both backends)
# ---------------------------------------------------------------------------

def test_select_all(conn):
    rows = conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 5
    # Key access works for both dict (recdb) and sqlite3.Row (stdlib)
    assert rows[0]["name"] is not None

def test_select_projection(conn):
    rows = conn.execute("SELECT name, stock FROM items").fetchall()
    assert len(rows) == 5
    assert rows[0]["name"] is not None
    assert rows[0]["stock"] is not None

def test_select_where_eq(conn):
    rows = conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Widget A"

def test_select_where_lt(conn):
    rows = conn.execute("SELECT * FROM items WHERE stock < 10").fetchall()
    assert len(rows) == 2
    assert {rows[0]["sku"], rows[1]["sku"]} == {"GAD-001", "GAD-002"}

def test_select_where_and(conn):
    rows = conn.execute(
        "SELECT * FROM items WHERE category = 'widgets' AND stock > 50"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["sku"] == "WGT-001"

def test_select_like_prefix(conn):
    rows = conn.execute("SELECT * FROM items WHERE name LIKE 'Widget%'").fetchall()
    assert len(rows) == 2

def test_select_like_contains(conn):
    rows = conn.execute("SELECT * FROM items WHERE name LIKE '%adget%'").fetchall()
    assert len(rows) == 2

def test_select_order_asc(conn):
    rows = conn.execute("SELECT * FROM items ORDER BY stock").fetchall()
    stocks = [r["stock"] for r in rows]
    assert stocks == sorted(stocks)

def test_select_order_desc(conn):
    rows = conn.execute("SELECT * FROM items ORDER BY stock DESC").fetchall()
    stocks = [r["stock"] for r in rows]
    assert stocks == sorted(stocks, reverse=True)

def test_select_limit(conn):
    rows = conn.execute("SELECT * FROM items LIMIT 2").fetchall()
    assert len(rows) == 2

def test_select_order_and_limit(conn):
    rows = conn.execute("SELECT * FROM items ORDER BY stock DESC LIMIT 3").fetchall()
    assert len(rows) == 3
    assert rows[0]["stock"] >= rows[1]["stock"] >= rows[2]["stock"]

# ---------------------------------------------------------------------------
# INSERT — shared
# ---------------------------------------------------------------------------

def test_insert(conn):
    conn.execute(INSERT, ("Thingamajig", "THG-001", 30, 5.00, "misc"))
    conn.commit()
    rows = conn.execute("SELECT * FROM items WHERE sku = 'THG-001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Thingamajig"

def test_executemany(conn):
    conn.executemany(INSERT, [
        ("Bulk A", "BLK-001", 10, 1.00, "bulk"),
        ("Bulk B", "BLK-002", 20, 2.00, "bulk"),
        ("Bulk C", "BLK-003", 30, 3.00, "bulk"),
    ])
    conn.commit()
    rows = conn.execute("SELECT * FROM items WHERE category = 'bulk'").fetchall()
    assert len(rows) == 3

# ---------------------------------------------------------------------------
# UPDATE — shared
# ---------------------------------------------------------------------------

def test_update_single_field(conn):
    conn.execute("UPDATE items SET stock = 999 WHERE sku = 'WGT-001'")
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchone()
    assert row["stock"] == 999

def test_update_multiple_fields(conn):
    conn.execute("UPDATE items SET stock = 5, price = 99.99 WHERE sku = 'WGT-002'")
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE sku = 'WGT-002'").fetchone()
    assert row["stock"] == 5
    assert row["price"] == 99.99

# ---------------------------------------------------------------------------
# DELETE — shared
# ---------------------------------------------------------------------------

def test_delete_with_where(conn):
    conn.execute("DELETE FROM items WHERE stock = 0")
    conn.commit()
    assert len(conn.execute("SELECT * FROM items WHERE stock = 0").fetchall()) == 0

def test_delete_all(conn):
    conn.execute("DELETE FROM items")
    conn.commit()
    assert len(conn.execute("SELECT * FROM items").fetchall()) == 0

# ---------------------------------------------------------------------------
# Cursor behaviour — shared
# ---------------------------------------------------------------------------

def test_fetchone(conn):
    row = conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchone()
    assert row is not None
    assert row["sku"] == "WGT-001"

def test_fetchmany(conn):
    rows = conn.execute("SELECT * FROM items").fetchmany(2)
    assert len(rows) == 2
    assert rows[0]["name"] is not None   # key access, not isinstance check

def test_parameter_binding(conn):
    rows = conn.execute("SELECT * FROM items WHERE sku = ?", ("GAD-001",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Gadget Pro"

def test_apostrophe_in_value(conn):
    """Values containing single quotes must round-trip correctly."""
    conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("O'Brien's Widget", "OBR-001", 5, 9.99, "misc")
    )
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE sku = 'OBR-001'").fetchone()
    assert row is not None
    assert row["name"] == "O'Brien's Widget"


def test_unsupported_join_raises(conn):
    with pytest.raises(Exception):
        conn.execute("SELECT * FROM items JOIN other ON items.sku = other.sku")

# ---------------------------------------------------------------------------
# recdb-specific behaviour
# (stdlib sqlite3 behaves differently here — documented in COMPAT.md)
# ---------------------------------------------------------------------------

@pytest.fixture
def recfile_conn(tmp_path):
    c = recdb.connect(str(tmp_path / "items.rec"))
    c.execute(CREATE)
    c.executemany(INSERT, SEED)
    c.commit()
    yield c
    c.close()


def test_rows_are_dicts(recfile_conn):
    """recdb always returns plain dicts. sqlite3 returns sqlite3.Row."""
    rows = recfile_conn.execute("SELECT * FROM items").fetchall()
    assert all(isinstance(r, dict) for r in rows)

def test_rowcount_select(recfile_conn):
    """recdb returns len(rows) for SELECT. sqlite3 returns -1."""
    cur = recfile_conn.execute("SELECT * FROM items")
    assert cur.rowcount == 5

def test_rowcount_delete(recfile_conn):
    """recdb reports rows deleted. sqlite3 also does, so this could be shared —
    kept here to make the recdb contract explicit."""
    cur = recfile_conn.execute("DELETE FROM items WHERE category = 'widgets'")
    assert cur.rowcount == 2

def test_context_manager_closes(tmp_path):
    """recdb's context manager commits and closes. sqlite3's only commits."""
    path = str(tmp_path / "ctx.rec")
    with recdb.connect(path) as c:
        c.execute("CREATE TABLE IF NOT EXISTS t (x TEXT NOT NULL)")
        c.execute("INSERT INTO t (x) VALUES (?)", ("hello",))
    # Re-open and verify data was committed
    c2 = recdb.connect(path)
    assert len(c2.execute("SELECT * FROM t").fetchall()) == 1
    c2.close()

def test_connect_autodetects_mode(tmp_path):
    """connect() infers single-file vs directory from the path extension."""
    # .rec extension → single-file mode
    sf = recdb.connect(str(tmp_path / "inventory.rec"))
    assert sf._single_file is not None
    sf.close()

    # no .rec extension → directory mode
    dm = recdb.connect(str(tmp_path / "mydb"))
    assert dm._single_file is None
    dm.close()

def test_connect_infers_table_from_stem(tmp_path):
    """The file stem becomes the default table name."""
    c = recdb.connect(str(tmp_path / "products.rec"))
    assert isinstance(c, recdb.RecfileConnection)
    c.close()


# ---------------------------------------------------------------------------
# Directory mode — connect() with a non-.rec path
# ---------------------------------------------------------------------------

CREATE_ITEMS = """
    CREATE TABLE IF NOT EXISTS items (
        name     TEXT NOT NULL,
        sku      TEXT NOT NULL,
        stock    INTEGER NOT NULL,
        price    REAL NOT NULL,
        category TEXT
    )
"""

CREATE_SUPPLIERS = """
    CREATE TABLE IF NOT EXISTS suppliers (
        name    TEXT NOT NULL,
        contact TEXT NOT NULL
    )
"""


@pytest.fixture
def dir_conn(tmp_path):
    """Directory-mode connection — tables live in separate .rec files."""
    c = recdb.connect(str(tmp_path / "db"))
    c.execute(CREATE_ITEMS)
    c.executemany(INSERT, SEED)
    c.commit()
    yield c
    c.close()


def test_dir_connect_creates_directory(tmp_path):
    """connect() creates the directory if it does not exist (directory mode)."""
    d = tmp_path / "newdir"
    assert not d.exists()
    conn = recdb.connect(str(d))
    assert d.exists()
    conn.close()


def test_dir_select_all(dir_conn, tmp_path):
    rows = dir_conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 5


def test_dir_select_where(dir_conn):
    rows = dir_conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Widget A"


def test_dir_insert(dir_conn):
    dir_conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("New Item", "NEW-001", 10, 5.00, "misc")
    )
    dir_conn.commit()
    rows = dir_conn.execute("SELECT * FROM items WHERE sku = 'NEW-001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "New Item"


def test_dir_update(dir_conn):
    dir_conn.execute("UPDATE items SET stock = 999 WHERE sku = 'WGT-001'")
    dir_conn.commit()
    row = dir_conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchone()
    assert row["stock"] == 999


def test_dir_delete(dir_conn):
    dir_conn.execute("DELETE FROM items WHERE stock = 0")
    dir_conn.commit()
    rows = dir_conn.execute("SELECT * FROM items WHERE stock = 0").fetchall()
    assert len(rows) == 0


def test_dir_multiple_tables(tmp_path):
    """Each table maps to a separate .rec file in the directory."""
    db_dir = str(tmp_path / "multidb")
    conn = recdb.connect(db_dir)

    conn.execute(CREATE_ITEMS)
    conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("Widget A", "WGT-001", 50, 9.99, "widgets")
    )

    conn.execute(CREATE_SUPPLIERS)
    conn.execute(
        "INSERT INTO suppliers (name, contact) VALUES (?, ?)",
        ("Acme Corp", "acme@example.com")
    )
    conn.commit()

    items = conn.execute("SELECT * FROM items").fetchall()
    suppliers = conn.execute("SELECT * FROM suppliers").fetchall()

    assert len(items) == 1
    assert items[0]["name"] == "Widget A"
    assert len(suppliers) == 1
    assert suppliers[0]["name"] == "Acme Corp"

    # Verify separate .rec files were created
    from pathlib import Path
    assert (Path(db_dir) / "items.rec").exists()
    assert (Path(db_dir) / "suppliers.rec").exists()

    conn.close()


def test_dir_context_manager(tmp_path):
    """connect() works as a context manager in directory mode."""
    db_dir = str(tmp_path / "ctx_db")
    with recdb.connect(db_dir) as conn:
        conn.execute(CREATE_ITEMS)
        conn.execute(
            "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
            ("Widget A", "WGT-001", 50, 9.99, "widgets")
        )

    # Re-open and verify data persisted
    conn2 = recdb.connect(db_dir)
    rows = conn2.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 1
    conn2.close()


def test_dir_order_by(dir_conn):
    rows = dir_conn.execute("SELECT * FROM items ORDER BY stock DESC").fetchall()
    stocks = [r["stock"] for r in rows]
    assert stocks == sorted(stocks, reverse=True)


def test_dir_no_default_table(tmp_path):
    """directory mode has no default table — table name must be explicit in SQL."""
    conn = recdb.connect(str(tmp_path / "db"))
    conn.execute(CREATE_ITEMS)
    # This should work fine — table name is in the SQL
    rows = conn.execute("SELECT * FROM items").fetchall()
    assert rows == []
    conn.close()


# ---------------------------------------------------------------------------
# Single-file multi-table — connect() with multiple %rec: blocks
# ---------------------------------------------------------------------------

CREATE_SUPPLIERS = """
    CREATE TABLE IF NOT EXISTS suppliers (
        name    TEXT NOT NULL,
        contact TEXT NOT NULL
    )
"""


def test_single_file_multiple_tables(tmp_path):
    """connect() stores all tables as %rec: blocks in one .rec file."""
    rec_path = str(tmp_path / "db.rec")
    conn = recdb.connect(rec_path)

    conn.execute(CREATE_ITEMS)
    conn.execute(CREATE_SUPPLIERS)
    conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("Widget A", "WGT-001", 50, 9.99, "widgets")
    )
    conn.execute(
        "INSERT INTO suppliers (name, contact) VALUES (?, ?)",
        ("Acme Corp", "acme@example.com")
    )
    conn.commit()

    items = conn.execute("SELECT * FROM items").fetchall()
    suppliers = conn.execute("SELECT * FROM suppliers").fetchall()

    assert len(items) == 1
    assert items[0]["name"] == "Widget A"
    assert len(suppliers) == 1
    assert suppliers[0]["name"] == "Acme Corp"

    # The critical assertion: everything lives in ONE file
    from pathlib import Path
    assert Path(rec_path).exists(), "single .rec file should exist"
    assert not (tmp_path / "items.rec").exists(), "items.rec should NOT exist"
    assert not (tmp_path / "suppliers.rec").exists(), "suppliers.rec should NOT exist"

    content = Path(rec_path).read_text()
    assert "%rec: items" in content
    assert "%rec: suppliers" in content

    conn.close()


def test_single_file_if_not_exists_idempotent(tmp_path):
    """CREATE TABLE IF NOT EXISTS is idempotent on a single-file connection."""
    conn = recdb.connect(str(tmp_path / "db.rec"))
    conn.execute(CREATE_ITEMS)
    conn.execute(CREATE_ITEMS)  # second call should be a no-op, not raise
    conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("Widget A", "WGT-001", 50, 9.99, "widgets")
    )
    conn.commit()
    rows = conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 1
    conn.close()


# ---------------------------------------------------------------------------
# python-recutils fallback backend
# (run with recsel hidden from PATH to force the fallback)
# ---------------------------------------------------------------------------

@pytest.fixture
def no_recutils(monkeypatch):
    """Hide GNU recutils from PATH so the python-recutils fallback is used."""
    monkeypatch.setenv("PATH", "")


@pytest.fixture
def pyrecutils_conn(tmp_path, no_recutils):
    """Recfile connection exercising the python-recutils backend."""
    import recdb
    c = recdb.connect(str(tmp_path / "items.rec"))
    c.execute(CREATE)
    c.executemany(INSERT, SEED)
    c.commit()
    yield c
    c.close()


def test_pyrecutils_select_all(pyrecutils_conn):
    rows = pyrecutils_conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 5


def test_pyrecutils_select_where_eq(pyrecutils_conn):
    rows = pyrecutils_conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Widget A"


def test_pyrecutils_select_where_lt(pyrecutils_conn):
    rows = pyrecutils_conn.execute("SELECT * FROM items WHERE stock < 10").fetchall()
    assert len(rows) == 2


def test_pyrecutils_select_like(pyrecutils_conn):
    rows = pyrecutils_conn.execute("SELECT * FROM items WHERE name LIKE 'Widget%'").fetchall()
    assert len(rows) == 2


def test_pyrecutils_select_order_desc(pyrecutils_conn):
    rows = pyrecutils_conn.execute("SELECT * FROM items ORDER BY stock DESC").fetchall()
    stocks = [r["stock"] for r in rows]
    assert stocks == sorted(stocks, reverse=True)


def test_pyrecutils_select_limit(pyrecutils_conn):
    rows = pyrecutils_conn.execute("SELECT * FROM items LIMIT 2").fetchall()
    assert len(rows) == 2


def test_pyrecutils_insert(pyrecutils_conn):
    pyrecutils_conn.execute(
        "INSERT INTO items (name, sku, stock, price, category) VALUES (?, ?, ?, ?, ?)",
        ("New Thing", "NEW-001", 5, 1.99, "misc")
    )
    row = pyrecutils_conn.execute("SELECT * FROM items WHERE sku = 'NEW-001'").fetchone()
    assert row is not None
    assert row["name"] == "New Thing"


def test_pyrecutils_update(pyrecutils_conn):
    pyrecutils_conn.execute("UPDATE items SET stock = 999 WHERE sku = 'WGT-001'")
    row = pyrecutils_conn.execute("SELECT * FROM items WHERE sku = 'WGT-001'").fetchone()
    assert row["stock"] == 999


def test_pyrecutils_delete_where(pyrecutils_conn):
    pyrecutils_conn.execute("DELETE FROM items WHERE stock = 0")
    rows = pyrecutils_conn.execute("SELECT * FROM items WHERE stock = 0").fetchall()
    assert len(rows) == 0


def test_pyrecutils_delete_all(pyrecutils_conn):
    pyrecutils_conn.execute("DELETE FROM items")
    rows = pyrecutils_conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 0


def test_pyrecutils_multiple_tables(tmp_path, no_recutils):
    """python-recutils backend handles multiple tables in a single .rec file."""
    import recdb
    conn = recdb.connect(str(tmp_path / "db.rec"))
    conn.execute("CREATE TABLE IF NOT EXISTS items (name TEXT NOT NULL, stock INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS suppliers (name TEXT NOT NULL)")
    conn.execute("INSERT INTO items (name, stock) VALUES (?, ?)", ("Widget", 10))
    conn.execute("INSERT INTO suppliers (name) VALUES (?)", ("Acme",))
    conn.commit()

    items = conn.execute("SELECT * FROM items").fetchall()
    suppliers = conn.execute("SELECT * FROM suppliers").fetchall()
    assert len(items) == 1
    assert len(suppliers) == 1
    assert items[0]["name"] == "Widget"
    assert suppliers[0]["name"] == "Acme"
    conn.close()
