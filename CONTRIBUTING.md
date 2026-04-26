# Contributing to recdb

Thanks for your interest in contributing. This document covers the practical
side — getting set up, running tests, and submitting changes.

For architectural context and design rationale, read [DESIGN.md](DESIGN.md)
before making a significant change.

## Prerequisites

- Python 3.10+
- [`just`](https://github.com/casey/just) task runner
  - Ubuntu/Debian: `sudo apt install just`
  - macOS: `brew install just`
- GNU recutils (recommended)
  - Ubuntu/Debian: `sudo apt install recutils`
  - macOS: `brew install recutils`
- python-recutils (optional fallback, included in dev deps)
  - `pip install recdb[recutils]`

## Setup

```bash
git clone https://github.com/mofosyne/recdb
cd recdb
just setup       # creates .venv, installs recdb + dev deps
just check-recutils  # verify recutils is available
```

## Running tests

```bash
just test        # all three backends, full suite
```

Tests use `pytest` with a parametrised `conn` fixture that runs every shared
test against three backends: GNU recutils, python-recutils fallback, and
stdlib sqlite3. If you add a test using the `conn` fixture, it runs against
all three for free.

Backend-specific tests (single-file mode, directory mode, migration) live in
dedicated sections of `test_recdb.py` and run once.

## Running the demo

```bash
just demo                # all three modes
just demo-recfile        # single-file recfile only
just demo-recfile-dir    # directory mode only
just demo-sqlite         # sqlite only
```

## Project layout

```
recdb/
├── src/recdb/
│   ├── __init__.py          ← connect() / migrate() entry points
│   ├── base.py              ← BaseConnection / BaseCursor ABCs
│   ├── exceptions.py        ← RecDBError hierarchy
│   ├── parser.py            ← SQL subset → AST (recfile backend only)
│   ├── _expr.py             ← AST → recsel expression string (shared)
│   ├── recfile.py           ← RecfileConnection / RecfileCursor
│   ├── pyrecutils_backend.py ← python-recutils fallback backend
│   └── migrate.py           ← recdb.migrate() implementation
├── tests/
│   └── test_recdb.py
├── examples/
│   └── library_demo.py
├── pyproject.toml
├── justfile
├── CONTRIBUTING.md  ← you are here
├── DESIGN.md        ← architecture and rationale
├── COMPAT.md        ← sqlite3 API compatibility notes
└── SECURITY.md
```

## Making changes

**Parser changes** — edit `src/recdb/parser.py`. The parser only affects
the recfile backend; SQLite passes SQL straight through to the stdlib.

**New SQL features** — add to the parser AST, handle in `RecfileCursor`
(mapping to recutils flags or python-recutils calls via `pyrecutils_backend`),
and verify SQLite passes it through naturally. Both backends must pass the
shared test suite.

**Expression changes** — edit `src/recdb/_expr.py`. This module is shared
between the GNU recutils and python-recutils backends; changes affect both.

**New tests** — add a `def test_*` function using the `conn` fixture and it
will run against all three backends automatically. Backend-specific behaviour
goes in a dedicated section with an appropriate fixture.

**Migration** — edit `src/recdb/migrate.py`. The GNU recutils path
(`_recfile_to_sqlite_gnu`) uses `recinf` + `recsel -d`; the fallback path
(`_recfile_to_sqlite_pyrec`) uses python-recutils.

## Code style

- Raise `SQLParseError` for malformed SQL, `UnsupportedSQLError` for valid
  SQL that the recfile backend doesn't support. Never use bare `assert` for
  user-facing errors.
- Rows are always returned as `dict`, never tuples.
- No silent fallbacks — if a recutils command fails, raise `RecutilsError`
  immediately.
- Both recfile backends (GNU and python-recutils) must behave identically
  for the operations they support.

## Submitting a PR

1. Fork and create a branch from `main`.
2. Make your change with tests.
3. Run `just test` — all three backends must be green.
4. Open a PR with a short description of what changed and why.

## Building and publishing (maintainers)

```bash
just build           # produces dist/
just publish-test    # upload to TestPyPI first
just publish         # upload to PyPI
```
