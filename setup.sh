#!/usr/bin/env bash
# Setup script to install project dependencies inside a virtual environment
# Usage: ./setup.sh

set -e

# Require Python 3.12
PY=$(command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || true)
if [ -z "$PY" ]; then
    echo "Error: Python 3.12 not found." >&2
    exit 1
fi
PY_VERSION=$("$PY" -c "import sys; print('%d.%d' % sys.version_info[:2])")
if [ "$PY_VERSION" != "3.12" ]; then
    echo "Error: Python 3.12 required, found $PY_VERSION." >&2
    exit 1
fi

# Create virtual environment if it does not exist
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    "$PY" -m venv "$VENV_DIR"
fi

# Activate the environment
source "$VENV_DIR/bin/activate"

# Upgrade pip and install requirements
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements_dev.txt

# Bootstrap .env from env.example if not present
if [ ! -f ".env" ]; then
    if [ -f "env.example" ]; then
        cp env.example .env
        echo ""
        echo "Created .env from env.example."
        echo "Edit .env and fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE_NUMBER before running the server."
    else
        echo "Warning: env.example not found — create .env manually before running the server." >&2
    fi
fi

# Bootstrap .analysis-defaults from analysis-defaults.example if not present
if [ ! -f ".analysis-defaults" ]; then
    if [ -f "analysis-defaults.example" ]; then
        cp analysis-defaults.example .analysis-defaults
        echo "Created .analysis-defaults from analysis-defaults.example."
        echo "Edit .analysis-defaults to tune crawling and analysis options."
    else
        echo "Warning: analysis-defaults.example not found — .analysis-defaults will use built-in defaults." >&2
    fi
fi

# Apply database migrations
python manage.py migrate

echo ""
echo "Setup complete. Activate the environment with:"
echo "  source $VENV_DIR/bin/activate"
echo "Then start the server with:"
echo "  python manage.py runserver"
