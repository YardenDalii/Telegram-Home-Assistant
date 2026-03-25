#!/usr/bin/env bash
# setup.sh — Initialize the project virtual environment and dependencies

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"

echo "==> Setting up Home Automation Bot"
echo "    Project: $PROJECT_DIR"

# Check Python version
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11+ is required but not found."
    exit 1
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "    Python: $PY_VERSION"

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
else
    echo "==> Virtual environment already exists, skipping."
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo "==> Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo "==> Installing dependencies..."
pip install -r "$PROJECT_DIR/requirements.txt" --quiet

# Copy .env.example if .env doesn't exist
if [ ! -f "$ENV_FILE" ]; then
    echo "==> Creating .env from template..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo ""
    echo "  IMPORTANT: Edit .env and fill in your credentials before running the bot."
    echo "  Open with:  nano $ENV_FILE"
else
    echo "==> .env already exists, skipping."
fi

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env:              nano $ENV_FILE"
echo "  2. Activate venv:          source venv/bin/activate"
echo "  3. Run the bot:            python src/main.py"
echo "  4. Run tests:              pytest tests/ -v"
