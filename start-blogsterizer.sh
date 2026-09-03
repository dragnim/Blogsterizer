#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

PYTHON_CMD="${PYTHON_CMD:-python3}"
"$PYTHON_CMD" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || {
    echo "The Blogsterizer requires Python 3.11 or later." >&2
    exit 1
}

if [ ! -d .venv ]; then
    "$PYTHON_CMD" -m venv .venv
fi

. .venv/bin/activate
if [ ! -f .venv/.blogsterizer-0.5.0-installed ]; then
    python -m pip install -e .
    : > .venv/.blogsterizer-0.5.0-installed
fi

python -m uvicorn app.main:app --reload
