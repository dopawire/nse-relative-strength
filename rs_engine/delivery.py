"""Delivery % — the share of the day's traded quantity taken into demat
(NSE sec_bhavdata_full).  High delivery while price rises suggests real
buying rather than intraday churn.  EQ series only: trade-for-trade (BE/BZ)
stocks are 100% delivery by rule.

Cache: ~/.cache/nse-rs/.nse_delivery.json  {sym: {date: delivery %}}
"""
import csv
import datetime as dt
import io
import os
from concurrent.futures import ThreadPoolExecutor

from rs_engine.config import CACHE_DIR

DELIVERY_CACHE = os.path.join(CACHE_DIR, ".nse_delivery.json")
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
KEEP_SESSIONS = 300


def parse(text):
    """sec_bhavdata_full CSV → {SYMBOL: delivery %} for EQ rows."""
    out = {}
    rdr = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rdr, [])]
    try:
        i_sym, i_ser, i_pct = head.index("SYMBOL"), head.index("SERIES"), head.index("DELIV_PER")
    except ValueError:
        return out
    for row in rdr:
        if len(row) <= i_pct or row[i_ser].strip() != "EQ":
            continue
        try:
            out[row[i_sym].strip()] = float(row[i_pct].strip())
        except ValueError:
            continue
    return out


def fetch_day(session, day):
    d = dt.date.fromisoformat(day).strftime("%d%m%Y")
    try:
        r = session.get(URL.format(d=d), timeout=30)
        if r.status_code == 200 and r.text.startswith("SYMBOL"):
            return parse(r.text)
    except Exception:
        pass
    return None


def update(cache, sessions, session, workers=4):
    """Fetch the delivery file for every session in `sessions` not yet in the
    cache (an empty marker is stored under "__DAYS__").  → days added."""
    have = set(cache.get("__DAYS__", []))
    todo = [d for d in sessions if d not in have]
    if not todo:
        return []
    with ThreadPoolExecutor(workers) as ex:
        got = list(ex.map(lambda d: (d, fetch_day(session, d)), todo))
    added = []
    for day, rows in got:
        if rows is None:
            continue
        for sym, pct in rows.items():
            cache.setdefault(sym, {})[day] = pct
        added.append(day)
    days = sorted(have | set(added))[-KEEP_SESSIONS:]
    cache["__DAYS__"] = days
    cut = days[0] if days else None
    if cut:
        for sym in [s for s in cache if s != "__DAYS__"]:
            cache[sym] = {d: v for d, v in cache[sym].items() if d >= cut}
    return sorted(added)


def metrics(series, asof=None):
    """{date: %} → {"dl": latest %, "dla": 20-session average %} (None when
    there isn't enough data; the latest must be the as-of day)."""
    days = sorted(d for d in series if asof is None or d <= asof)
    if not days or (asof and days[-1] != asof):
        return {"dl": None, "dla": None}
    last = days[-20:]
    return {"dl": round(series[days[-1]], 1),
            "dla": round(sum(series[d] for d in last) / len(last), 1) if len(last) >= 10 else None}
