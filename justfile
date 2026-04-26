# recdb — development task runner
# Install just: https://github.com/casey/just
# Ubuntu:  sudo apt install just
# macOS:   brew install just

venv   := ".venv"
python := venv + "/bin/python"
pip    := venv + "/bin/pip"
pytest := venv + "/bin/pytest"

# Show available recipes
default:
    @just --list

# Create venv and install recdb + dev deps in editable mode (run this first)
setup:
    @echo "Creating virtual environment..."
    python3 -m venv {{venv}}
    @echo "Installing recdb in editable mode with dev extras..."
    {{pip}} install --upgrade pip -q
    {{pip}} install -e ".[dev]" -q
    @echo ""
    @echo "Done. To activate manually: source {{venv}}/bin/activate"

# Run the full test suite (all three backends)
test:
    {{pytest}} -v

# Run the library demo against all three modes
demo:
    {{python}} examples/library_demo.py

# Run the demo — single-file recfile only
demo-recfile:
    DBTYPE=recfile {{python}} examples/library_demo.py

# Run the demo — directory mode only
demo-recfile-dir:
    DBTYPE=recfile-dir {{python}} examples/library_demo.py

# Run the demo — sqlite only
demo-sqlite:
    DBTYPE=sqlite {{python}} examples/library_demo.py

# Check recutils is installed (recommended for recfile backend)
check-recutils:
    @which recsel recins recset recdel > /dev/null 2>&1 \
        && echo "✓ recutils is installed" \
        || (echo "✗ recutils not found — install it:" \
            && echo "    Ubuntu/Debian: sudo apt install recutils" \
            && echo "    macOS:         brew install recutils" \
            && echo "  (python-recutils fallback is available via dev deps)")

# Build a distribution for PyPI
build:
    {{pip}} install build -q
    {{python}} -m build
    @echo "Built: dist/"

# Upload to TestPyPI (test before real upload)
publish-test:
    {{pip}} install twine -q
    {{python}} -m twine upload --repository testpypi dist/*

# Upload to PyPI
publish:
    {{pip}} install twine -q
    {{python}} -m twine upload dist/*

# Remove venv and build artifacts
clean:
    rm -rf {{venv}} dist build src/*.egg-info
    @echo "Cleaned."

# Remove venv, caches, and temp test databases
clean-all: clean
    rm -rf .pytest_cache __pycache__ src/recdb/__pycache__ tests/__pycache__
    @echo "All clean."
