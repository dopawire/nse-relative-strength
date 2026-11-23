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

. ./find_python.sh

# exported (set -a): send_brief.py reads the Telegram settings too
if [ -f "$HOME/.config/nse-rs/notify.env" ]; then
    set -a; . "$HOME/.config/nse-rs/notify.env"; set +a
fi

notify() {
    [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
    curl -s -m 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--if-stale" ]; then
    if "$PY" audit_data.py --stale-only >/dev/null 2>&1; then
        # prices are current — but NSE posts FII/DII between ~18:00 and 21:00,
        # often after the build: pick it up on the hourly retries
        out="$(timeout 120 "$PY" refresh_flows.py --if-behind --patch 2>&1)"
        if printf '%s' "$out" | grep -q "rs_data.json updated"; then
            printf '[%s] FII/DII caught up\n%s\n' "$(date '+%F %T')" "$out" >> run.log
            if [ "${PUBLISH_SITE:-0}" = "1" ]; then
                /bin/bash publish_site.sh >> run.log 2>&1 \
                    && echo "[$(date '+%F %T')] site published" >> run.log
            fi
        fi
        echo "[$(date '+%F %T')] cron retry: data already current — skipping" >> run.log
        exit 0
    fi
    echo "[$(date '+%F %T')] cron retry: data stale — rebuilding" >> run.log
fi

# pick up new NSE listings first (best effort: geo-blocked / no Playwright →
# they're still added unclassified so the New Listings tab shows them)
echo "[$(date '+%F %T')] refresh_classification.py" >> run.log
timeout 900 "$PY" refresh_classification.py >> run.log 2>&1 \
    || echo "[$(date '+%F %T')] listing refresh failed (rc=$?) — continuing" >> run.log

# upcoming results / corporate events (best effort)
timeout 120 "$PY" refresh_events.py >> run.log 2>&1 || true

# FII / DII cash flows (best effort: the files keep their history on failure)
echo "[$(date '+%F %T')] refresh_flows.py" >> run.log
timeout 120 "$PY" refresh_flows.py >> run.log 2>&1 \
    || echo "[$(date '+%F %T')] FII/DII refresh failed (rc=$?) — continuing" >> run.log

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

# evening brief + watchlist alerts → Telegram (no-op without a bot token;
# once per session)
"$PY" send_brief.py >> run.log 2>&1 || notify "⚠️ nse-rs brief failed — see run.log"

# optional: publish the snapshot to the public site (PUBLISH_SITE=1)
if [ "${PUBLISH_SITE:-0}" = "1" ]; then
    if /bin/bash publish_site.sh >> run.log 2>&1; then
        echo "[$(date '+%F %T')] site published" >> run.log
    else
        notify "⚠️ nse-rs site publish failed — see run.log"
    fi
fi
