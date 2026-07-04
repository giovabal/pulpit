#!/usr/bin/env bash
# Setup script to install project dependencies inside a virtual environment
# Usage: ./setup.sh

set -e

# Require Python 3.12, 3.13, or 3.14 (Pulpit supports all three; prefer the newest available)
PY=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
    bin=$(command -v "$candidate" 2>/dev/null) || continue
    version=$("$bin" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null) || continue
    case "$version" in
        3.12 | 3.13 | 3.14)
            PY="$bin"
            break
            ;;
    esac
done
if [ -z "$PY" ]; then
    echo "Error: Python 3.12, 3.13, or 3.14 is required but was not found." >&2
    echo "Download it from https://www.python.org/downloads/" >&2
    exit 1
fi

# Create virtual environment if it does not exist.
# graph-tool (needed only for the SBM community strategies) is not pip-installable — it comes from
# apt/conda into the *system* site-packages. When the chosen Python has it, create the venv with
# --system-site-packages so it is importable inside the venv; other setups get a fully isolated one.
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    VENV_OPTS=""
    if "$PY" -c "import graph_tool" >/dev/null 2>&1; then
        VENV_OPTS="--system-site-packages"
        echo "Detected system graph-tool — creating the venv with --system-site-packages so it is importable (needed for the SBM community strategies)."
    fi
    "$PY" -m venv $VENV_OPTS "$VENV_DIR"
elif "$PY" -c "import graph_tool" >/dev/null 2>&1 && grep -q "include-system-site-packages = false" "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
    echo "Warning: system graph-tool is installed, but the existing $VENV_DIR was created without --system-site-packages, so graph_tool is not importable there (the SBM strategies will fail)." >&2
    echo "         Recreate it (rm -rf $VENV_DIR && ./setup.sh) or set 'include-system-site-packages = true' in $VENV_DIR/pyvenv.cfg." >&2
fi

# Activate the environment
source "$VENV_DIR/bin/activate"

# Upgrade pip and install requirements
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements_dev.txt

# Bootstrap configuration/.env from configuration/env.example if not present
mkdir -p configuration
if [ ! -f "configuration/.env" ]; then
    if [ -f "configuration/env.example" ]; then
        cp configuration/env.example configuration/.env
        echo ""
        echo "Created configuration/.env from configuration/env.example."
        echo "Edit configuration/.env and fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE_NUMBER before running the server."
    else
        echo "Warning: configuration/env.example not found — create configuration/.env manually before running the server." >&2
    fi
fi

# Crawler and structural-analysis defaults live in webapp_engine/config/defaults.py.
# A configuration/.operations-crawl or configuration/.operations-structural file is
# only created when the user clicks "Save as defaults" in the Operations panel
# (or hand-writes one). Until then, the built-in defaults apply.

# Install dev tooling (html-validate for the static-export HTML lint)
# npm is optional — skip with a friendly note if it's not on PATH.
if command -v npm >/dev/null 2>&1; then
    npm install --no-audit --no-fund --loglevel=error
else
    echo "Note: npm not found — skipping html-validate install."
    echo "Install Node.js to enable 'npm run lint:html'."
fi

# Apply database migrations
python manage.py migrate

echo ""
echo "Setup complete. Activate the environment with:"
echo "  source $VENV_DIR/bin/activate"
echo "Then start the server with:"
echo "  python manage.py runserver"
