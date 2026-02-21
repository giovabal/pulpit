#!/usr/bin/env bash
# Setup script to install project dependencies inside a virtual environment
# Usage: ./setup.sh

set -e

# Create virtual environment if it does not exist
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Activate the environment
source "$VENV_DIR/bin/activate"

# Upgrade pip and install requirements
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements_dev.txt

echo "Environment ready. Activate with 'source $VENV_DIR/bin/activate'"
