"""The worker container's clock (replaces the host crontab).  IST, weekdays:

    18:30          cron_daily.sh            listings, events, FII/DII, build, audit, brief
    every hour,
    19:30          cron_daily.sh --if-stale rebuild if the session was missed;
                                            otherwise pick up late FII/DII figures
    02:15 daily    backup of the data volume (14 kept)
    at start       cron_daily.sh --if-stale after 5 minutes (catch up after a restart)

Standard library only; one job at a time (build_rs.py also holds a lock).
"""
import datetime as dt
import os
import subprocess
import sys
import tarfile
import time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("NSE_RS_DATA_DIR", "/data")
CACHE = os.environ.get("NSE_RS_CACHE_DIR", "/cache")
KEEP_BACKUPS = int(os.environ.get("NSE_RS_KEEP_BACKUPS", "14"))


def log(msg):
    print(f"[{dt.datetime.now(IST):%Y-%m-%d %H:%M:%S}] scheduler: {msg}", flush=True)


def run(*args):
    log("run cron_daily.sh " + " ".join(args))
    rc = subprocess.call(["/bin/bash", os.path.join(APP, "cron_daily.sh"), *args], cwd=APP)
    log(f"cron_daily.sh exited {rc}")


def backup(now):
    """tar.gz of the data volume + the NSE archive (the price caches are rebuilt
    from Yahoo / NSE, the archive takes 300 downloads to refill)."""
    out = os.path.join(DATA, "backups")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"nse-rs-{now:%Y%m%d-%H%M}.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        for name in sorted(os.listdir(DATA)):
            if name in ("backups",) or name.endswith(".tmp"):
                continue
            tar.add(os.path.join(DATA, name), arcname=f"data/{name}")
        arc = os.path.join(CACHE, ".nse_archive.json")
        if os.path.exists(arc):
            tar.add(arc, arcname="cache/.nse_archive.json")
    olds = sorted(f for f in os.listdir(out) if f.startswith("nse-rs-") and f.endswith(".tar.gz"))
    for f in olds[:-KEEP_BACKUPS]:
        os.remove(os.path.join(out, f))
    log(f"backup → {path}")


def due(now):
    """Jobs for this minute."""
    jobs = []
    weekday = now.weekday() < 5
    if weekday and (now.hour, now.minute) == (18, 30):
        jobs.append(("daily",))
    elif weekday and (now.minute == 0 or (now.hour, now.minute) == (19, 30)):
        jobs.append(("--if-stale",))
    if (now.hour, now.minute) == (2, 15):
        jobs.append(("backup",))
    return jobs


def main():
    log(f"started (TZ IST, app {APP}, data {DATA})")
    start = time.time()
    caught_up = False
    while True:
        now = dt.datetime.now(IST).replace(second=0, microsecond=0)
        for job in due(now):
            try:
                if job == ("backup",):
                    backup(now)
                elif job == ("daily",):
                    run()
                else:
                    run(*job)
            except Exception as e:          # never let one failure stop the clock
                log(f"job {job} failed: {e}")
        if not caught_up and time.time() - start > 300:
            caught_up = True
            run("--if-stale")
        # sleep to the start of the next minute
        nxt = (dt.datetime.now(IST) + dt.timedelta(minutes=1)).replace(second=0, microsecond=0)
        time.sleep(max(1.0, (nxt - dt.datetime.now(IST)).total_seconds()))


if __name__ == "__main__":
    sys.exit(main())
