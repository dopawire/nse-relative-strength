#!/usr/bin/env bash
# Daily automated build + audit (cron entry point).
#
#   18:30 IST weekdays — build after the market closes and Yahoo settles
#   19:30 IST weekdays — retry once if the 18:30 run missed the session
#                       (Yahoo sometimes publishes late)
#
# Installed by install_cron.sh.  Optional Telegram failure alerts: put
# TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in ~/.config/nse-rs/notify.env
# (free Bot API; set TELEGRAM_NOTIFY_OK=1 to also get success pings).
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

[ -f "$HOME/.config/nse-rs/notify.env" ] && . "$HOME/.config/nse-rs/notify.env"

notify() {
    [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
    curl -s -m 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--if-stale" ]; then
    if "$PY" audit_data.py --stale-only >/dev/null 2>&1; then
        echo "[$(date '+%F %T')] cron retry: data already current — skipping" >> run.log
        exit 0
    fi
    echo "[$(date '+%F %T')] cron retry: data stale — rebuilding" >> run.log
fi

bash run_daily.sh
build_rc=$?
"$PY" audit_data.py >> run.log 2>&1
audit_rc=$?

if [ $build_rc -ne 0 ] || [ $audit_rc -ne 0 ]; then
    notify "⚠️ nse-rs daily issue (build=$build_rc audit=$audit_rc) — see run.log"
    exit 1
fi
if [ "${TELEGRAM_NOTIFY_OK:-0}" = "1" ]; then
    notify "✅ nse-rs daily build + audit OK ($(date '+%F %T'))"
fi
