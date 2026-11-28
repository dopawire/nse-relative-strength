#!/bin/sh
# First run: seed the data volume with the snapshot baked into the image
# (the nse_*.csv tables, the pick log, rs_data.json) — never overwrites.
# Optional: NSE_RS_ADMIN_USER + NSE_RS_ADMIN_PASSWORD create the first admin
# when there are no users yet.
set -eu
DATA="${NSE_RS_DATA_DIR:-/data}"
mkdir -p "$DATA" "${NSE_RS_CACHE_DIR:-/cache}"
for f in /app/nse_*.csv /app/nse_picks.jsonl /app/rs_data.json; do
    [ -e "$f" ] || continue
    [ -e "$DATA/$(basename "$f")" ] || cp "$f" "$DATA/"
done
if [ -n "${NSE_RS_ADMIN_USER:-}" ] && [ -n "${NSE_RS_ADMIN_PASSWORD:-}" ] \
   && [ ! -s "${NSE_RS_USERS:-$DATA/users.json}" ]; then
    NSE_RS_PASSWORD="$NSE_RS_ADMIN_PASSWORD" python -m backend.users add "$NSE_RS_ADMIN_USER" --admin
fi
exec "$@"
