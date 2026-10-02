#!/usr/bin/env bash
# Install the daily cron entries for the NSE RS pipeline (idempotent):
#   30 18 * * 1-5  cron_daily.sh            build + audit after market close
#   30 19 * * 1-5  cron_daily.sh --if-stale retry once if Yahoo published late
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MARK="# nse-rs daily build (managed by install_cron.sh)"

existing="$(crontab -l 2>/dev/null || true)"
if grep -qF "nse-rs daily build" <<<"$existing"; then
    echo "cron entries already installed:"
    grep -A3 "nse-rs daily build" <<<"$existing"
    exit 0
fi

{
    [ -n "$existing" ] && echo "$existing"
    echo "$MARK"
    echo "30 18 * * 1-5 /bin/bash $DIR/cron_daily.sh"
    echo "30 19 * * 1-5 /bin/bash $DIR/cron_daily.sh --if-stale"
} | sed '/^$/d' | crontab -

echo "installed (system TZ: $(date +%Z)):"
crontab -l | tail -3
