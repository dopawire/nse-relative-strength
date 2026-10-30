#!/usr/bin/env bash
# Start the NSE Relative Strength web server.
# Prerequisites: rs_data.json must exist (run build_rs.py first).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

. ./find_python.sh

DATA_FILE="rs_data.json"
if [ ! -f "$DATA_FILE" ]; then
    echo "rs_data.json not found. Running build_rs.py --html-only to generate it..."
    "$PY" build_rs.py --html-only
fi

# localhost only by default: the Update/Refresh endpoints start long jobs and
# have no auth.  NSE_RS_HOST=0.0.0.0 bash run_server.sh to serve the LAN.
HOST="${NSE_RS_HOST:-127.0.0.1}"
echo "Starting NSE RS server on http://$HOST:8000"
exec "$PY" -m uvicorn backend.main:app --host "$HOST" --port 8000
