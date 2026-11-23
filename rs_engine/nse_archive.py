"""NSE's official daily file (sec_bhavdata_full) kept for the last ~300
sessions: close, high, low, traded quantity and delivery % per stock.

Yahoo's adjusted history is mostly right but not always:

  * a split / bonus is sometimes applied to only PART of the history —
    TRENT's 1:2 bonus (4-Jun-2026) was adjusted back to 1-Jan-2026 only,
    leaving a fake −33% day on 1-Jan; SILVERTUC got a fake −90%;
  * some stocks' history starts months after they began trading on NSE
    (≈220 stocks begin on 18-Aug-2026 at Yahoo).

rebase() rebuilds every stock's archived sessions from NSE's official
prices, keeping Yahoo's adjustment factor only across genuine corporate
actions — so returns match NSE's except where a split / bonus is adjusted
for, stale or wrong Yahoo bars disappear, and missing history is filled.
It runs every build and is idempotent.

Cache: ~/.cache/nse-rs/.nse_archive.json  {sym: {date: [c, h, l, qty, deliv%|null]}}
"""
import csv
import datetime as dt
import io
import math
import os
from concurrent.futures import ThreadPoolExecutor

from rs_engine.config import CACHE_DIR

ARCHIVE = os.path.join(CACHE_DIR, ".nse_archive.json")
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
KEEP_SESSIONS = 300
SERIES = ("EQ", "BE", "BZ")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse(text):
    """sec_bhavdata_full CSV → {SYMBOL: [close, high, low, qty, deliv%|None]}.
    Delivery % only for EQ — trade-for-trade (BE/BZ) is 100% by rule."""
    out = {}
    rdr = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rdr, [])]
    try:
        ix = {k: head.index(k) for k in ("SYMBOL", "SERIES", "CLOSE_PRICE", "HIGH_PRICE",
                                         "LOW_PRICE", "TTL_TRD_QNTY", "DELIV_PER")}
    except ValueError:
        return out
    for row in rdr:
        if len(row) < len(head):
            continue
        ser = row[ix["SERIES"]].strip()
        if ser not in SERIES:
            continue
        c = _num(row[ix["CLOSE_PRICE"]].strip())
        if not c:
            continue
        out[row[ix["SYMBOL"]].strip()] = [
            c, _num(row[ix["HIGH_PRICE"]].strip()), _num(row[ix["LOW_PRICE"]].strip()),
            _num(row[ix["TTL_TRD_QNTY"]].strip()),
            _num(row[ix["DELIV_PER"]].strip()) if ser == "EQ" else None]
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


def update(arc, sessions, session, workers=6):
    """Download every session in `sessions` not yet archived; trim to the
    last KEEP_SESSIONS.  → sorted list of days added."""
    have = set(arc.get("__DAYS__", []))
    todo = [d for d in sessions if d not in have]
    added = []
    if todo:
        with ThreadPoolExecutor(workers) as ex:
            got = list(ex.map(lambda d: (d, fetch_day(session, d)), todo))
        for day, rows in got:
            if rows is None:
                continue
            for sym, v in rows.items():
                arc.setdefault(sym, {})[day] = v
            added.append(day)
    days = sorted(have | set(added))[-KEEP_SESSIONS:]
    arc["__DAYS__"] = days
    if days:
        cut = days[0]
        for sym in [s for s in arc if s != "__DAYS__"]:
            arc[sym] = {d: v for d, v in arc[sym].items() if d >= cut}
            if not arc[sym]:
                del arc[sym]
    return sorted(added)


CA_STEP = 0.07       # a corporate-action factor must be at least a 7% step
STABLE = 0.01        # ...and Yahoo's factor must hold steady on either side


def _median(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def corporate_actions(ser, a, days):
    """Days in `days` where Yahoo's adjustment factor f = ours / NSE raw
    steps cleanly (steady on both sides) by ≥ 7% AND NSE's raw price made the
    bigger move — a split / bonus Yahoo adjusted for.  → {day: k}, k = the
    factor applied to the days before it.  A factor step where OUR price made
    the bigger move is Yahoo applying an adjustment on the wrong day; a
    one-day blip is a bad bar — neither counts."""
    f = {d: ser[d] / a[d][0] for d in days if ser.get(d)}
    fd = sorted(f)
    ca = {}
    for i in range(1, len(fd)):
        p, d = fd[i - 1], fd[i]
        k = f[p] / f[d]
        if abs(math.log(k)) < CA_STEP:
            continue
        after = fd[i + 1:i + 3]
        before = fd[max(0, i - 3):i - 1]
        if not all(abs(f[x] / f[d] - 1) <= STABLE for x in after):
            continue
        if not all(abs(f[x] / f[p] - 1) <= STABLE for x in before):
            continue
        ro, rr = ser[d] / ser[p], a[d][0] / a[p][0]
        if abs(math.log(rr)) > abs(math.log(ro)):
            ca[d] = k
    return ca, f


def rebase(cache, highs, lows, arc, syms, volumes=None, sessions=None):
    """Rebuild each stock's archived sessions from NSE's official prices,
    keeping only Yahoo's genuine corporate-action adjustments (see
    corporate_actions); older Yahoo history is joined on at the first
    archived day.  Fixes partial split adjustments, stale or wrong bars, and
    fills sessions Yahoo lacks.  Idempotent.
    → {"changed": {sym: max % change}, "added": {sym: n}, "ca": {sym: {day: k}}}"""
    ok = set(sessions) if sessions else None
    out = {"changed": {}, "added": {}, "ca": {}}
    for s in syms:
        ser, a = cache.get(s), arc.get(s)
        if not ser or not a:
            continue
        days = [d for d in sorted(a) if a[d][0] and (ok is None or d in ok)]
        overlap = [d for d in days if ser.get(d)]
        if len(overlap) < 3:
            continue
        ca, f = corporate_actions(ser, a, overlap)
        # scale from the days AFTER the last corporate action (a median that
        # straddles one would rescale the whole series on every run)
        tail = [d for d in overlap if not ca or d >= max(ca)][-5:]
        F = _median([f[d] for d in tail])
        factor = {}
        for d in reversed(days):
            factor[d] = F
            if d in ca:
                F *= ca[d]
        # older Yahoo history: join at the first archived days
        older = [d for d in ser if d < days[0]]
        if older:
            head = [d for d in overlap if not ca or d < min(ca)][:5] or overlap[:1]
            j = _median([factor[d] / f[d] for d in head])
            if abs(j - 1) > 1e-9:
                for st in (cache, highs, lows):
                    v = st.get(s)
                    if v:
                        for d in [d for d in v if d < days[0]]:
                            v[d] *= j
                if volumes is not None and volumes.get(s):
                    v = volumes[s]
                    for d in [d for d in v if d < days[0]]:
                        v[d] = v[d] / j
        worst, n_new = 0.0, 0
        for d in days:
            c, h, lo, q, _ = a[d]
            k = factor[d]
            new = c * k
            if d in ser and ser[d]:
                worst = max(worst, abs(new / ser[d] - 1))
            else:
                n_new += 1
            ser[d] = new
            if h and lo:
                highs.setdefault(s, {})[d] = h * k
                lows.setdefault(s, {})[d] = lo * k
            if volumes is not None and q is not None and k:
                volumes.setdefault(s, {})[d] = q / k
        # sessions the stock didn't trade (suspension / no trades): Yahoo
        # carries a price forward, sometimes a stale one (SEYAIND 14-Nov-2025:
        # 22.79 vs NSE's last close 20.6) — carry NSE's last close instead
        last = None
        di = 0
        for d in sorted(x for x in ser if days[0] < x < days[-1]):
            while di < len(days) and days[di] < d:
                last = days[di]
                di += 1
            if d in a or last is None or (ok is not None and d not in ok):
                continue
            v = a[last][0] * factor[last]
            if ser[d]:
                worst = max(worst, abs(v / ser[d] - 1))
            ser[d] = v
            highs.setdefault(s, {})[d] = v
            lows.setdefault(s, {})[d] = v
            if volumes is not None:
                volumes.setdefault(s, {})[d] = 0
        if worst > 0.005:
            out["changed"][s] = round(worst * 100, 1)
        if n_new:
            out["added"][s] = n_new
        if ca:
            out["ca"][s] = {d: round(k, 4) for d, k in ca.items()}
    return out


def delivery_metrics(rows, asof):
    """{date: row} → {"dl": delivery % on `asof`, "dla": 20-session average}."""
    days = sorted(d for d in rows or {} if d <= asof and rows[d][4] is not None)
    if not days or days[-1] != asof:
        return {"dl": None, "dla": None}
    last = days[-20:]
    return {"dl": round(rows[asof][4], 1),
            "dla": round(sum(rows[d][4] for d in last) / len(last), 1) if len(last) >= 10 else None}
