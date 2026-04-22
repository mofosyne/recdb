# Contributing to recdb

Thanks for your interest in contributing. This document covers the practical
side — getting set up, running tests, and submitting changes.

For architectural context and design rationale, read [DESIGN.md](DESIGN.md)
before making a significant change.

## Prerequisites

- Python 3.11+
- [`just`](https://github.com/casey/just) task runner
  - Ubuntu/Debian: `sudo apt install just`
  - macOS: `brew install just`
- GNU recutils (for the recfile backend)
  - Ubuntu/Debian: `sudo apt install recutils`
  - macOS: `brew install recutils`

## Setup

```bash
git clone https://github.com/yourname/recdb
cd recdb
just setup       # creates .venv, installs recdb + dev deps
just check-recutils  # verify recutils is available
```

## Running tests

```bash
just test            # both backends, full suite
just test-recfile    # recfile backend only
just test-sqlite     # sqlite backend only
```

Tests use `pytest` with a parametrised fixture — every test function
automatically runs against both backends. If you add a test, it will
run against both for free.

## Running the demo

```bash
just demo            # both backends
just demo-recfile
just demo-sqlite
```

## Project layout

```
recdb/
├── src/recdb/       ← importable package
│   ├── __init__.py  ← connect() entry point, backend inference
│   ├── base.py      ← BaseConnection / BaseCursor ABCs
│   ├── parser.py    ← SQL → AST (recfile backend only)
│   ├── recfile.py   ← RecfileConnection / RecfileCursor
│   └── sqlite.py    ← SQLiteConnection / SQLiteCursor
├── tests/
│   └── test_recdb.py
├── examples/
│   └── library_demo.py
├── data/
│   └── items.rec    ← sample data for manual exploration
├── pyproject.toml
├── justfile
├── CONTRIBUTING.md  ← you are here
├── DESIGN.md        ← architecture and evolution path
└── COMPAT.md        ← sqlite3 API compatibility notes
```

## Making changes

- **Parser changes** — edit `src/recdb/parser.py`. The parser only affects
  the recfile backend; SQLite passes SQL straight through.
- **New SQL features** — add to the parser AST, then handle in
  `RecfileCursor` (mapping to recutils flags) and verify SQLite passes
  it through naturally.
- **Backend behaviour** — both backends must pass the same test suite.
  The parametrised fixture in `tests/test_recdb.py` enforces this.
- **New tests** — add a plain `def test_*` function to `test_recdb.py`.
  The `conn` fixture handles both backends automatically.

## Code style

- Standard library only beyond `recdb` (no additional runtime deps
  without discussion).
- `assert` for unsupported SQL (mirrors sqlite3's behaviour on unsupported
  operations rather than raising a custom exception hierarchy).
- Rows are always returned as `dict`, never tuples.
- No silent fallbacks — if a recutils command fails, raise immediately.

## Submitting a PR

1. Fork and create a branch from `main`.
2. Make your change with tests.
3. Run `just test` — both backends must be green.
4. Open a PR with a short description of what changed and why.

## Building and publishing (maintainers)

```bash
just build           # produces dist/
just publish-test    # upload to TestPyPI first
just publish         # upload to PyPI
```
