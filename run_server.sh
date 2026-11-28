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

# The React app: build it once (needs Node 22 — or use Docker, see DEPLOY.md)
if [ ! -f frontend/dist/index.html ]; then
    echo "Building the web app (frontend/) ..."
    (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

# localhost only by default.  On 127.0.0.1 login is off unless NSE_RS_AUTH=1;
# serving the LAN (NSE_RS_HOST=0.0.0.0) always needs a login — add one with
#   python -m backend.users add YOU --admin
HOST="${NSE_RS_HOST:-127.0.0.1}"
if [ "$HOST" = "127.0.0.1" ]; then
    export NSE_RS_AUTH="${NSE_RS_AUTH:-0}"
else
    export NSE_RS_AUTH=1
fi
# plain http locally: the session cookie can't be HTTPS-only
export NSE_RS_COOKIE_SECURE="${NSE_RS_COOKIE_SECURE:-0}"
echo "Starting NSE RS server on http://$HOST:8000 (login $([ "$NSE_RS_AUTH" = 0 ] && echo off || echo on))"
exec "$PY" -m uvicorn backend.main:app --host "$HOST" --port 8000
