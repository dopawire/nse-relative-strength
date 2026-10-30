#!/usr/bin/env bash
# Daily NSE Relative-Strength build (Yahoo data). Logs to run.log.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"   # run from wherever this script lives

. ./find_python.sh

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }
{
  echo "----------------------------------------------------------------"
  echo "[$(ts)] build_rs.py start"
  "$PY" build_rs.py
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "[$(ts)] done -> rs_view.html"
  else
    echo "[$(ts)] FAILED (exit $rc)"
  fi
} >> run.log 2>&1
