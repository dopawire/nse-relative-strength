#!/usr/bin/env bash
# Publish the current data snapshot to GitHub — commits rs_data.json and
# pushes, which triggers the GitHub Pages deploy (read-only public site).
#
#   bash publish_site.sh              # commit + push today's snapshot
#   bash publish_site.sh --build      # rebuild first, then publish
#
# Requires git push access to the repo (gh auth setup-git).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

. ./find_python.sh

if [ "${1:-}" = "--build" ]; then
    "$PY" build_rs.py
fi

if [ ! -f rs_data.json ]; then
    echo "rs_data.json missing — run build_rs.py first" >&2
    exit 1
fi

gen="$("$PY" -c "import json; print(json.load(open('rs_data.json'))['meta']['gen'])")"
# the master too: the cloud fallback build (daily_build.yml) reads the
# committed universe, so new listings must be pushed for it to see them
git add rs_data.json nse_stock_master.csv
if git diff --cached --quiet; then
    echo "rs_data.json unchanged — nothing to publish"
    exit 0
fi
git commit -q -m "data snapshot $gen"
# the cloud workflow also commits snapshots — rebase onto it, keeping ours
# (-X theirs = the commit being replayed, i.e. this local snapshot)
git pull -q --rebase --autostash -X theirs
git push -q
echo "published: data snapshot $gen (Pages deploy triggered)"
