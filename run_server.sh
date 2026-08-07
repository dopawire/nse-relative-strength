#!/usr/bin/env bash
# Start the NSE Relative Strength web server.
# Prerequisites: rs_data.json must exist (run build_rs.py first).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

DATA_FILE="rs_data.json"
if [ ! -f "$DATA_FILE" ]; then
    echo "rs_data.json not found. Running build_rs.py --html-only to generate it..."
    "$PY" build_rs.py --html-only
fi

echo "Starting NSE RS server on http://localhost:8000"
exec "$PY" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
