#!/usr/bin/env bash
# Setup script to install project dependencies inside a virtual environment
# Usage: ./setup.sh

set -e

# Require Python 3.12, 3.13 or 3.14. graph-tool (needed only for the SBM community strategies) is not
# pip-installable: apt/conda ship it compiled for one interpreter — python3.12 on Ubuntu 24.04,
# python3.14 on 26.04 — so prefer the supported interpreter that can import it, and otherwise the
# newest one installed.
PY=""
GRAPH_TOOL_PY=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
    bin=$(command -v "$candidate" 2>/dev/null) || continue
    version=$("$bin" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null) || continue
    case "$version" in
        3.12 | 3.13 | 3.14)
            [ -z "$PY" ] && PY="$bin"
            if [ -z "$GRAPH_TOOL_PY" ] && "$bin" -c "import graph_tool" >/dev/null 2>&1; then
                GRAPH_TOOL_PY="$bin"
            fi
            ;;
    esac
done
[ -n "$GRAPH_TOOL_PY" ] && PY="$GRAPH_TOOL_PY"
if [ -z "$PY" ]; then
    echo "Error: Python 3.12, 3.13 or 3.14 is required but was not found." >&2
    echo "Download it from https://www.python.org/downloads/" >&2
    exit 1
fi

# Django requires SQLite 3.37+ (the default database engine). Older distributions ship
# interpreters linked against a too-old library — fail here with an explanation rather
# than at the first query with an opaque Django error.
sqlite_version=$("$PY" -c "import sqlite3; print(sqlite3.sqlite_version)" 2>/dev/null || echo "0")
if [ "$(printf '3.37.0\n%s\n' "$sqlite_version" | sort -V | head -n1)" != "3.37.0" ]; then
    echo "Error: SQLite 3.37 or newer is required, but Python is linked against $sqlite_version." >&2
    echo "Upgrade your system SQLite (or use PostgreSQL 15+ / MySQL 8.4+ / MariaDB 10.11+)." >&2
    exit 1
fi

# Create virtual environment if it does not exist.
# graph-tool (needed only for the SBM community strategies) is not pip-installable — it comes from
# apt/conda into the *system* site-packages. When the chosen Python has it, create the venv with
# --system-site-packages so it is importable inside the venv; other setups get a fully isolated one.
VENV_DIR=".venv"

# A venv built with a different interpreter cannot be reused: its packages are compiled for that
# interpreter, and with --system-site-packages it would keep borrowing system packages built for
# another one (after an OS upgrade moves python3 to a new version, numpy/SciPy/Pillow/graph-tool all
# fail to import). Detect a version mismatch up front and recreate the venv from scratch with the
# interpreter selected above.
if [ -d "$VENV_DIR" ]; then
    required_version=$("$PY" -c "import sys; print('%d.%d' % sys.version_info[:2])")
    existing_version=$("$VENV_DIR/bin/python" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || true)
    if [ "$existing_version" != "$required_version" ]; then
        echo "Existing $VENV_DIR was built with Python ${existing_version:-unknown}, but $required_version is required — recreating it."
        rm -rf "$VENV_DIR"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    VENV_OPTS=""
    if "$PY" -c "import graph_tool" >/dev/null 2>&1; then
        VENV_OPTS="--system-site-packages"
        echo "Detected system graph-tool — creating the venv with --system-site-packages so it is importable (needed for the SBM community strategies)."
    fi
    "$PY" -m venv $VENV_OPTS "$VENV_DIR"
fi

# Use the venv interpreter directly (POSIX-portable; avoids the bash-only `source`,
# so `sh setup.sh` works under dash as well as bash).
VENV_PY="$VENV_DIR/bin/python"

# Upgrade pip and install requirements
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt -r requirements_dev.txt

# The system graph-tool must still import inside the venv after the install — otherwise the SBM
# strategies fail at the first run. Say why here instead.
if "$PY" -c "import graph_tool" >/dev/null 2>&1 && ! "$VENV_PY" -c "import graph_tool" >/dev/null 2>&1; then
    echo "Warning: system graph-tool is installed but does not import inside $VENV_DIR, so the SBM strategies will fail." >&2
    if grep -q "include-system-site-packages = false" "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
        echo "         $VENV_DIR was created without --system-site-packages. Recreate it (rm -rf $VENV_DIR && sh setup.sh) or set 'include-system-site-packages = true' in $VENV_DIR/pyvenv.cfg." >&2
    else
        echo "         A package has likely installed its own numpy into $VENV_DIR over the system one graph-tool was compiled against — '$VENV_PY -m pip show numpy' should report a Location outside $VENV_DIR." >&2
    fi
fi

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
"$VENV_PY" manage.py migrate

echo ""
echo "Setup complete. Activate the environment with:"
echo "  source $VENV_DIR/bin/activate"
echo "Then start the server with:"
echo "  python manage.py runserver"
