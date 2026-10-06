#!/usr/bin/env bash
# Install the daily cron entries for the NSE RS pipeline (idempotent):
#   30 18 * * 1-5  cron_daily.sh            build + audit after market close
#   30 19 * * 1-5  cron_daily.sh --if-stale retry once if Yahoo published late
#   0  * * * 1-5   cron_daily.sh --if-stale hourly evening catch-up — the
#                  machine is often off at 18:30, so retry until a session is
#                  covered (stale-gated: no-op while current, and before 16:00)
#   @reboot        cron_daily.sh --if-stale same catch-up after boot
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MARK="# nse-rs daily build (managed by install_cron.sh)"

existing="$(crontab -l 2>/dev/null || true)"
# drop any previous nse-rs block (lines referencing cron_daily.sh or the mark)
cleaned="$(grep -vF -e "cron_daily.sh" -e "$MARK" <<<"$existing" | sed '/^$/d' || true)"

{
    [ -n "$cleaned" ] && echo "$cleaned"
    echo "$MARK"
    echo "30 18 * * 1-5 /bin/bash $DIR/cron_daily.sh"
    echo "30 19 * * 1-5 /bin/bash $DIR/cron_daily.sh --if-stale"
    echo "0 * * * 1-5 /bin/bash $DIR/cron_daily.sh --if-stale"
    echo "@reboot sleep 300 && /bin/bash $DIR/cron_daily.sh --if-stale"
} | crontab -

echo "installed (system TZ: $(date +%Z)):"
crontab -l | tail -5
