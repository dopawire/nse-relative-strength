#!/usr/bin/env python3
"""
Build a Relative-Strength view (like RS.xlsx / image1.png) across all four NSE
classification levels (Macro, Sector, Industry, Basic Industry), equally
weighted, rendered as a self-contained HTML file.

Data source: Yahoo Finance chart API (free, no key, no auth).
Universe / 4-level map: nse_stock_master.csv (built straight from NSE).

Method (mirrors RS.xlsx):
  * For each constituent stock, pull daily closes from Yahoo (SYMBOL.NS).
  * Build an EQUAL-WEIGHT index per group at each level:
        each stock normalised to base-100 on the first day of the window,
        then averaged across constituents at every date.
  * Benchmark = NIFTY 500 (^CRSLDX), also normalised to base-100.
  * Relative Strength series  RS[t] = group_index[t] / bench_norm[t].
  * RS_STS%  = PERCENTRANK(RS_series, latest RS)  -> 0..100%
               (same as Excel PERCENTRANK.INC used in the sheet).
  * Sparkline = bar chart of the RS series; RS_STS% cell gets a green gradient.

The price cache grows over time: the first run pulls ~2y per symbol; each
later run only tops up the last month and appends, so daily runs are fast.

Usage:
  python3 build_rs.py            # daily run: top-up prices -> rs_view.html
  python3 build_rs.py --limit 40 # quick test on first 40 stocks
  python3 build_rs.py --refresh  # refetch full history for every symbol
  python3 build_rs.py --html-only# rebuild HTML from cached prices only
"""

import os
import io
import sys
import csv
import json
import time
import shutil
import random
import zipfile
import argparse
import datetime as dt
import threading
import concurrent.futures as cf
from collections import defaultdict, Counter

import requests

# ---- rs_engine: computation core (re-exported here for compatibility) ----
from rs_engine.config import (CACHE_DIR, WINDOW, FULL_RANGE,
                              APPEND_RANGE, MIN_BARS, EMA_PERIODS, BENCHMARK_NAME, BENCH_YSYM,
                              YH_WORKERS, IST, is_holiday)
from rs_engine.maths import (percentrank_inc, ema_flags, rs_ema_flag,
                             last_break_date, pct_off_high, adr_pct,
                             equal_weight_rs)
from rs_engine.breadth import (compute_breadth, compute_macro_breadth,
                               detect_breadth_divergence)
from rs_engine.rotation import compute_rotation
from rs_engine.snapshot import (load_previous_snapshot,
                                append_snapshot, build_ipo_watch)
from rs_engine.report import write_daily_report
from rs_engine.render import build_html

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_CSV   = os.path.join(HERE, "nse_stock_master.csv")   # NSE 4-level universe

# Cache file locations (CACHE_DIR itself lives in rs_engine.config).
PRICE_CACHE  = os.path.join(CACHE_DIR, ".yh_price_cache.json")   # {sym: {date: close}}
HIGH_CACHE   = os.path.join(CACHE_DIR, ".yh_high_cache.json")    # {sym: {date: intraday high}}
LOW_CACHE    = os.path.join(CACHE_DIR, ".yh_low_cache.json")     # {sym: {date: intraday low}}
PROVENANCE   = os.path.join(CACHE_DIR, ".yh_provenance.json")    # {date: source} for non-Yahoo bars
BUILD_LOCK   = os.path.join(CACHE_DIR, ".build.lock")
OUT_HTML     = os.path.join(HERE, "rs_view.html")
RS_DATA_JSON = os.path.join(HERE, "rs_data.json")


def migrate_legacy_caches():
    """MOVE in-repo caches (old NTFS location) into CACHE_DIR once."""
    for name in (".yh_price_cache.json", ".yh_high_cache.json",
                 ".yh_low_cache.json", ".yh_provenance.json"):
        dst = os.path.join(CACHE_DIR, name)
        src = os.path.join(HERE, name)
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy(src, dst)
            os.remove(src)               # single source of truth — no divergence
            print(f"Migrated {name} → {CACHE_DIR}")


migrate_legacy_caches()

# Yahoo Finance chart API (free, no key). NSE cash symbols use the ".NS" suffix.
YH_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
YH_HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")}

LEVELS = [("macro", "Macro"), ("sector", "Sector"),
          ("industry", "Industry"), ("basic", "Basic Industry")]


# --------------------------------------------------------------------------- #
#  Setup helpers
# --------------------------------------------------------------------------- #
def read_universe():
    """Return list of dicts {name, sym, macro, sector, industry, basic}.

    Source: nse_stock_master.csv (symbol,company,series,isin,macro,sector,
    industry,basicIndustry) — built directly from NSE.
    """
    rows = []
    with open(MASTER_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sym = (r.get("symbol") or "").strip().upper()
            if not sym:
                continue
            rows.append({
                "name":     (r.get("company") or sym).strip(),
                "sym":      sym,
                "macro":    (r.get("macro") or "").strip(),
                "sector":   (r.get("sector") or "").strip(),
                "industry": (r.get("industry") or "").strip(),
                "basic":    (r.get("basicIndustry") or "").strip(),
            })

    # Canonicalise casing per level: NSE occasionally returns an all-caps
    # outlier (e.g. "HEALTHCARE" for one stock vs "Healthcare" for 164), which
    # would otherwise split into a phantom second group. Collapse each
    # case-insensitive value to its most-common existing casing.
    for key in ("macro", "sector", "industry", "basic"):
        variants = defaultdict(Counter)
        for r in rows:
            if r[key]:
                variants[r[key].lower()][r[key]] += 1
        canon = {lk: c.most_common(1)[0][0] for lk, c in variants.items()}
        for r in rows:
            if r[key]:
                r[key] = canon[r[key].lower()]
    return rows


# --------------------------------------------------------------------------- #
#  Yahoo Finance historical fetch
# --------------------------------------------------------------------------- #
_tls = threading.local()


def write_json_atomic(path, obj):
    """Write JSON via tmp + os.replace so a crash mid-write (kill, power loss,
    disk hiccup) can never leave a truncated/corrupt cache behind."""
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def load_json_cache(path):
    """Load a JSON cache, surviving corruption: warn + return {} instead of
    crashing the whole build. The affected data is refetched on the next run."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: {path} is corrupt ({type(e).__name__}) — starting that "
              f"cache fresh; its data will be refetched.")
        return {}


def _session():
    """One requests.Session per worker thread (keep-alive, thread-safe)."""
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(YH_HEADERS)
        _tls.s = s
    return s


def yahoo_closes(ysym, rng):
    """Fetch a Yahoo ticker over `rng`. Returns (closes, highs, lows, err), each a
    {date: value} map. Highs feed the 52-week metric; highs+lows feed ADR%."""
    url = YH_URL.format(sym=requests.utils.quote(ysym), rng=rng)
    for attempt in range(4):
        try:
            r = _session().get(url, timeout=25)
        except requests.RequestException:
            time.sleep(0.8 * (attempt + 1) + random.random())
            continue
        if r.status_code == 429:                      # rate-limited: back off
            time.sleep(1.5 * (attempt + 1) + random.random())
            continue
        if r.status_code != 200:
            return None, None, None, f"HTTP {r.status_code}"
        try:
            res = (r.json().get("chart") or {}).get("result")
        except ValueError:
            return None, None, None, "bad-json"
        if not res:
            return None, None, None, "empty"
        res = res[0]
        ts = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        cl = quote.get("close") or []
        hg = quote.get("high") or []
        lw = quote.get("low") or []
        out, hi, lo = {}, {}, {}
        for i, (t, c) in enumerate(zip(ts, cl)):
            if c is None:
                continue
            day = dt.datetime.fromtimestamp(int(t), IST).strftime("%Y-%m-%d")
            out[day] = float(c)
            h = hg[i] if i < len(hg) else None
            lwv = lw[i] if i < len(lw) else None
            hi[day] = float(h) if h is not None else float(c)
            lo[day] = float(lwv) if lwv is not None else float(c)
        return (out, hi, lo, None) if out else (None, None, None, "empty")
    return None, None, None, "rate-limited"


INTRA_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             "?range=5d&interval=5m")


def intraday_day(ysym, day):
    """Return (close, high, low) for `day` (ISO) from Yahoo 5-minute bars, or
    None.  Used to repair days whose DAILY bar is null while intraday bars
    exist (Yahoo's recurring gap pattern — Aug 28 2026, Jul 28 2026, ...).
    close = last bar of the day; high/low = intraday extremes (exact)."""
    try:
        r = _session().get(INTRA_URL.format(sym=requests.utils.quote(ysym)),
                           timeout=25)
        if r.status_code != 200:
            return None
        res = (r.json().get("chart") or {}).get("result")
        if not res:
            return None
        res = res[0]
        ts = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        cl, hg, lw = (quote.get("close") or [], quote.get("high") or [],
                      quote.get("low") or [])
    except (requests.RequestException, ValueError, KeyError):
        return None
    bars = []
    for i, t in enumerate(ts):
        d = dt.datetime.fromtimestamp(int(t), IST).strftime("%Y-%m-%d")
        if d == day and i < len(cl) and cl[i] is not None:
            bars.append((cl[i],
                         hg[i] if i < len(hg) and hg[i] is not None else cl[i],
                         lw[i] if i < len(lw) and lw[i] is not None else cl[i]))
    if not bars:
        return None
    return (bars[-1][0],
            max(b[1] for b in bars),
            min(b[2] for b in bars))


def fetch_prices(universe, cache, highs, lows, fast=False):
    """Fetch daily closes + intraday highs/lows for every symbol + benchmark into
    `cache` ({sym:{date:close}}), `highs` and `lows`, benchmark under '__BENCH__'.

    By DEFAULT every run re-pulls the full FULL_RANGE window for every symbol, so any
    value Yahoo has since revised (splits, late corrections, back-filled gaps) is
    picked up and the output is reproducible. Runtime is dominated by the ~2.4k HTTP
    requests, not payload size, so this costs little over a top-up.

    `fast=True` restores the old incremental append (symbols already holding
    >= MIN_BARS of close AND high AND low history only pull APPEND_RANGE). That is
    quicker but leaves historical data un-revalidated, which silently drifts the
    market-breadth oscillator between runs."""
    def plan(sym):
        if not fast:
            return FULL_RANGE        # default: re-pull the whole window every run
        cl, hg, lw = cache.get(sym), highs.get(sym), lows.get(sym)
        need_full = (not cl or len(cl) < MIN_BARS
                     or not hg or len(hg) < MIN_BARS
                     or not lw or len(lw) < MIN_BARS)
        return FULL_RANGE if need_full else APPEND_RANGE

    jobs = [("__BENCH__", BENCH_YSYM)] + [(u["sym"], u["sym"] + ".NS") for u in universe]
    done = ok = 0
    miss = []
    total = len(jobs)

    def work(item):
        key, ysym = item
        data, hi, lo, err = yahoo_closes(ysym, plan(key))
        return key, data, hi, lo, err

    def flush():
        for path, obj in ((PRICE_CACHE, cache), (HIGH_CACHE, highs), (LOW_CACHE, lows)):
            write_json_atomic(path, obj)

    with cf.ThreadPoolExecutor(max_workers=YH_WORKERS) as ex:
        for key, data, hi, lo, err in ex.map(work, jobs):
            done += 1
            if data:
                cache.setdefault(key, {}).update(data)   # merge/append
                if hi:
                    highs.setdefault(key, {}).update(hi)
                if lo:
                    lows.setdefault(key, {}).update(lo)
                ok += 1
            else:
                miss.append((key, err))
            if done % 200 == 0:
                print(f"  {done}/{total} fetched ...")
                flush()
    flush()
    return ok, miss


# --------------------------------------------------------------------------- #
#  NSE official EOD bhavcopy (authoritative closes; Indian IPs only)
# --------------------------------------------------------------------------- #
def fetch_bhavcopy(day):
    """NSE's official end-of-day bhavcopy for one day → {SYMBOL: {close, high,
    low}}.  This is the AUTHORITATIVE closing price series (better than
    Yahoo's).  Geo-restricted to Indian IPs — returns None when blocked.
    Two URL generations are tried (current + legacy naming)."""
    d = dt.date.fromisoformat(day)
    ymd = d.strftime("%Y%m%d")
    mon = d.strftime("%b").upper()
    urls = [
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
        f"https://nsearchives.nseindia.com/content/historical/EQUITIES/"
        f"{d.year}/{mon}/cm{d.day:02d}{mon}{d.year}bhav.csv.zip",
    ]
    for url in urls:
        try:
            r = _session().get(url, timeout=30)
            if r.status_code != 200:
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            name = z.namelist()[0]
            rows = csv.DictReader(
                io.StringIO(z.read(name).decode("utf-8-sig", "ignore")))

            def fnum(row, *keys):
                for k in keys:
                    v = row.get(k)
                    if v not in (None, ""):
                        try:
                            return float(str(v).replace(",", ""))
                        except ValueError:
                            continue
                return None

            out = {}
            for row in rows:
                sym = (row.get("SYMBOL") or row.get("TckrSymb") or "").strip()
                if not sym:
                    continue
                # modern schema tags instruments; legacy uses the SERIES column
                instr = (row.get("FinInstrmTp") or "").strip()
                if instr and instr != "STK":
                    continue                   # skip ETFs, bonds, options, ...
                series = (row.get("SERIES") or row.get("SctySrs") or "").strip()
                if series and series not in ("EQ", "BE", "BZ", "SM", "ST"):
                    continue                   # skip debt/ETF/other segments
                c = fnum(row, "CLOSE_PRICE", "CLOSE", "ClsPric")
                if c is None or c <= 0:
                    continue
                if sym in out and series != "EQ":
                    continue                   # prefer the EQ row on duplicates
                out[sym] = {"close": c,
                            "high": fnum(row, "HIGH_PRICE", "HIGH", "HghPric") or c,
                            "low": fnum(row, "LOW_PRICE", "LOW", "LwPric") or c}
            return out if out else None
        except Exception:
            continue
    return None


def fetch_bhav_indices(day):
    """NSE's all-indices closing CSV for one day → {"Nifty 500": 23528.55, ...}.
    Geo-restricted to Indian IPs — returns None when blocked."""
    d = dt.date.fromisoformat(day)
    url = (f"https://nsearchives.nseindia.com/content/indices/"
           f"ind_close_all_{d.day:02d}{d.month:02d}{d.year}.csv")
    try:
        r = _session().get(url, timeout=30)
        if r.status_code != 200:
            return None
        out = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            name = (row.get("Index Name") or "").strip()
            try:
                out[name] = float(
                    str(row.get("Closing Index Value") or "").replace(",", ""))
            except ValueError:
                continue
        return out if out else None
    except Exception:
        return None


def purge_flat_carries(cache, highs, lows, have):
    """Yahoo re-serves stale flat carries on some outage days (e.g. 2025-03-18:
    thousands of bars equal to the previous close while the index moved
    +1.8% — a data-pipeline failure day).  For any date where >90% of the
    bars are flat duplicates, drop the flat bars so they can't distort
    EMA/ADR metrics; genuine movers on the day are kept.  Returns purged dates."""
    cov = {}
    for s in have:
        for d in cache.get(s, {}):
            cov[d] = cov.get(d, 0) + 1
    n = len(have) or 1
    purged = []
    for day in sorted(cov):
        if not (0.5 * n < cov[day] < 0.98 * n):
            continue
        if not is_fake_flat_day(cache, have, day):
            continue
        removed = 0
        for s in have:
            ser = cache.get(s, {})
            if day not in ser:
                continue
            prevs = [d for d in ser if d < day]
            if prevs and ser[day] == ser[prevs[-1]]:
                del ser[day]
                highs.get(s, {}).pop(day, None)
                lows.get(s, {}).pop(day, None)
                removed += 1
        if removed:
            purged.append(day)
    if purged:
        write_json_atomic(PRICE_CACHE, cache)
        write_json_atomic(HIGH_CACHE, highs)
        write_json_atomic(LOW_CACHE, lows)
        print(f"Purged flat Yahoo carry-bars on {len(purged)} day(s): {purged}")
    return purged


def repair_intraday_gap(cache, highs, lows, have, thresh, today=None, prov=None):
    """Yahoo occasionally serves null DAILY bars for sessions the market was
    open, while its intraday bars exist (Aug 28 2026 — whole market; Jul 28 —
    indices only).  For each candidate weekday that lacks broad stock coverage
    (strictly PAST days — never a session in progress), repair every missing
    symbol.  Source priority: (1) NSE official bhavcopy (authoritative, Indian
    IPs) → (2) Yahoo 5-minute bars.  Also self-heals bogus benchmark bars
    (deviates >1% from the real close).  `prov` (optional dict) is tagged with
    {date: source}.  Returns the list of repaired dates."""
    if today is None:
        today = dt.datetime.now(IST).date()
    bench = cache.get("__BENCH__", {})
    if not bench:
        return []
    # Candidates: weekdays after the last bench date, plus recent bench dates
    # whose stock coverage is thin (a stale/wrong bench bar must not silently
    # hide a gap).
    candidates = []
    d = dt.date.fromisoformat(max(bench)) + dt.timedelta(days=1)
    while d < today:
        if d.weekday() < 5:
            candidates.append(d.isoformat())
        d += dt.timedelta(days=1)
    for day in sorted(bench)[-7:]:
        if day not in candidates:
            candidates.append(day)
    repaired = []
    for day in candidates:
        if not (dt.date.fromisoformat(day) < today):
            continue                       # never a session in progress
        if is_holiday(day):
            continue                       # official NSE holiday
        cov = sum(1 for s in have if day in cache.get(s, {}))
        bench_missing = day not in bench
        if cov >= thresh and not bench_missing:
            continue                       # healthy day — nothing to do

        # (1) NSE bhavcopy: one fetch covers the whole day, official prices
        bhav = fetch_bhavcopy(day)
        if bhav:
            bench_val = None
            idx = fetch_bhav_indices(day) or {}
            for k, v in idx.items():
                if k.strip().lower() == BENCHMARK_NAME.lower():
                    bench_val = v
                    break
            filled = 0
            if bench_val and (bench_missing or abs(bench[day] / bench_val - 1) > 0.01):
                cache["__BENCH__"][day] = bench_val
                filled += 1
            for s in have:
                if day in cache.get(s, {}):
                    continue
                row = bhav.get(s)
                if not row:
                    continue
                cache.setdefault(s, {})[day] = row["close"]
                highs.setdefault(s, {})[day] = row["high"]
                lows.setdefault(s, {})[day] = row["low"]
                filled += 1
            if filled:
                repaired.append(day)
                if prov is not None:
                    prov[day] = "bhavcopy"
                print(f"Repaired {day} from NSE bhavcopy: {filled} symbols.")
                continue

        # (2) fallback: Yahoo 5m intraday bars
        probe = (intraday_day(BENCH_YSYM, day)
                 or (intraday_day(have[0] + ".NS", day) if have else None))
        if probe is None:
            continue                       # holiday, or no intraday bars at all
        i_close = probe[0]
        jobs = []
        if bench_missing or abs(bench[day] / i_close - 1) > 0.01:
            jobs.append(("__BENCH__", BENCH_YSYM))
        jobs += [(s, s + ".NS") for s in have if day not in cache.get(s, {})]
        filled = 0
        for key, ysym in jobs:
            bar = intraday_day(ysym, day)
            if not bar:
                continue
            c, h, lwv = bar
            cache.setdefault(key, {})[day] = c
            highs.setdefault(key, {})[day] = h
            lows.setdefault(key, {})[day] = lwv
            filled += 1
        if filled:
            repaired.append(day)
            if prov is not None:
                prov[day] = "intraday"
            print(f"Repaired {day} from intraday bars: {filled} symbols "
                  f"(Yahoo daily bars were null).")
    if repaired:
        write_json_atomic(PRICE_CACHE, cache)
        write_json_atomic(HIGH_CACHE, highs)
        write_json_atomic(LOW_CACHE, lows)
    return repaired


# --------------------------------------------------------------------------- #
#  Investing.com fallback scraper (parses the page's embedded JSON)
# --------------------------------------------------------------------------- #
_INV_URL = "https://www.investing.com/indices/s-p-cnx-500-historical-data"
_INV_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _scrape_investing_com():
    """Scrape recent NIFTY 500 closes from Investing.com.  Returns {date: close}
    for the last ~20 trading days, or None on any failure (network, block, parse).
    The page embeds the historical table as a JSON blob
    ("historicalData":{"data":[{...,"rowDateTimestamp":"2026-07-29T00:00:00Z",
    "last_closeRaw":"23352.59...",...}]}) — we bracket-match and json.loads it,
    which is far more robust than regexing the rendered table HTML."""
    try:
        r = _session().get(_INV_URL, headers=_INV_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None

    i = html.find('"historicalData":{"data":[')
    if i < 0:
        return None
    start = html.find("[", i)
    if start < 0:
        return None
    # Bracket-match to find the end of the JSON array (string-aware).
    depth, j, in_str, esc = 0, start, False, False
    while j < len(html):
        ch = html[j]
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    break
        j += 1
    if j >= len(html):
        return None
    try:
        data = json.loads(html[start:j + 1])
    except Exception:
        return None

    out = {}
    for row in data:
        try:
            out[row["rowDateTimestamp"][:10]] = float(row["last_closeRaw"])
        except (KeyError, TypeError, ValueError):
            continue
    return out if out else None


def is_fake_flat_day(cache, have, day, sample=300):
    """Yahoo sometimes emits flat duplicate bars on NSE holidays (100% of stock
    bars equal the previous close) and stale carries on pipeline-outage days.
    Real trading days virtually never have >90% flat closes.  Returns True when
    the day looks fake — such dates must never be filled into the benchmark."""
    flat = moved = 0
    for s in have[:sample]:
        ser = cache.get(s, {})
        if day not in ser:
            continue
        prevs = [d for d in ser if d < day]
        if not prevs:
            continue
        if ser[day] == ser[prevs[-1]]:
            flat += 1
        else:
            moved += 1
    total = flat + moved
    return total >= 100 and flat / total > 0.9


def fill_benchmark_gaps(bench, cache, have, thresh, inv=None):
    """Fill benchmark days that Yahoo missed (index symbols occasionally publish
    null OHLC while individual stocks publish fine).  Fallback chain per missing
    date: (1) Investing.com scrape (`inv`; fetched here when not supplied) →
    (2) synthetic: previous benchmark close × (1 + equal-weight mean stock return),
    requiring ≥ 100 stocks.  Only dates with broad stock coverage (≥ `thresh`)
    are considered.  Mutates `bench`; returns [(date, method), ...] filled."""
    bench_dates = set(bench.keys())
    all_dates = set()
    for s in have:
        all_dates.update(cache[s].keys())
    # Only fill RECENT gaps: the index-gap incidents (Jul 28, Aug 28) are
    # last-day events.  Old dates missing from the benchmark are mostly NSE
    # holidays that Yahoo wrongly gave bars to for many stocks — filling those
    # would inject fake trading days into the benchmark/breadth history.
    cutoff = dt.date.fromisoformat(max(bench_dates)) - dt.timedelta(days=45)
    missing = sorted(d for d in all_dates if d not in bench_dates
                     if d >= cutoff.isoformat()
                     if sum(1 for s in have if d in cache[s]) >= thresh
                     if not is_holiday(d)
                     if not is_fake_flat_day(cache, have, d))
    if not missing:
        return []
    if inv is None:
        inv = _scrape_investing_com()
    filled = []
    for d in missing:
        val, method = None, None
        # (1) Investing.com — real index close, always preferred
        if inv and d in inv:
            val, method = inv[d], "investing.com"
        # (2) Synthetic from equal-weight stock returns (last resort)
        if val is None:
            prev_dates = sorted(dd for dd in bench_dates if dd < d)
            if prev_dates:
                prev_d = prev_dates[-1]
                returns = []
                for s in have:
                    if prev_d in cache[s] and d in cache[s]:
                        p0, p1 = cache[s][prev_d], cache[s][d]
                        if p0 and p0 > 0:
                            returns.append(p1 / p0 - 1)
                if len(returns) >= 100:
                    val = round(bench[prev_d] * (1 + sum(returns) / len(returns)), 2)
                    method = "synthetic"
        if val is not None:
            bench[d] = val
            filled.append((d, method))
    return filled




# --------------------------------------------------------------------------- #
#  JSON export for the FastAPI backend
# --------------------------------------------------------------------------- #
def save_rs_json(levels, breadth, meta, path, rotation=None):
    """Write precomputed RS data so the backend can serve it without recomputing."""
    data = {
        "meta": meta,
        "breadth": breadth if breadth else {"dates": [], "osc": [], "n": 0},
        "rotation": rotation or {"dates": [], "groups": []},
        "levels": [],
    }
    gid = 0
    for key, label, items in levels:
        level_data = {"key": key, "label": label, "groups": []}
        for it in items:
            members_out = []
            for m in it["members"]:
                members_out.append({
                    "n": m["name"], "s": m["sym"],
                    "r": [round(x, 3) for x in m["rs"]],
                    "p": round(m["pct"], 4),
                    "e": m.get("ema") or [-1] * len(EMA_PERIODS),
                    "b": m.get("rse", -1),
                    "d": m.get("d"),
                    "l": round(m["ltp"], 2) if m.get("ltp") is not None else None,
                    "h": round(m["hi52"], 1) if m.get("hi52") is not None else None,
                    "a": round(m["adr"], 2) if m.get("adr") is not None else None,
                })
            level_data["groups"].append({
                "id": gid, "name": it["name"],
                "n": it["n"], "pct": round(it["pct"], 4),
                "dp": it.get("dp"),
                "r": [round(x, 3) for x in it["rs"]],
                "members": members_out,
            })
            gid += 1
        data["levels"].append(level_data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only use first N stocks (test)")
    ap.add_argument("--html-only", action="store_true", help="rebuild HTML from cache only")
    ap.add_argument("--refresh", action="store_true",
                    help="(default behaviour now; kept for compatibility)")
    ap.add_argument("--fast", action="store_true",
                    help="incremental top-up only — quicker, but leaves historical "
                         "data un-revalidated and drifts the breadth oscillator")
    args = ap.parse_args()

    # One build at a time: run_daily.sh in a terminal + the website's Update
    # Prices button both write the caches — concurrent runs interleave JSON
    # writes and corrupt them. flock is released automatically on exit.
    try:
        import fcntl
        _lock_fh = open(BUILD_LOCK, "w")
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Another build is already running (website button / terminal?). "
                 "Wait for it to finish and retry.")
    except ImportError:
        pass   # non-POSIX platform — skip the lock

    universe = read_universe()
    if args.limit:
        universe = universe[:args.limit]
    print(f"Universe: {len(universe)} stocks, "
          f"{len({u['sector'] for u in universe if u['sector']})} sectors, "
          f"{len({u['industry'] for u in universe if u['industry']})} industries, "
          f"{len({u['basic'] for u in universe if u['basic']})} basic industries.")

    # ---- price cache (keyed by NSE symbol; benchmark under '__BENCH__') ----
    cache = load_json_cache(PRICE_CACHE)
    highs = load_json_cache(HIGH_CACHE)
    lows = load_json_cache(LOW_CACHE)

    if not args.html_only:
        if args.fast:
            n_new = sum(1 for u in universe
                        if len(cache.get(u["sym"], {})) < MIN_BARS
                        or len(highs.get(u["sym"], {})) < MIN_BARS
                        or len(lows.get(u["sym"], {})) < MIN_BARS)
            print(f"Fetching from Yahoo ({BENCHMARK_NAME}=^CRSLDX + {len(universe)} "
                  f"stocks): {n_new} full-history, {len(universe)-n_new} top-up "
                  f"(--fast: history not re-validated) ...")
        else:
            print(f"Fetching from Yahoo ({BENCHMARK_NAME}=^CRSLDX + {len(universe)} "
                  f"stocks): full {FULL_RANGE} history for all (re-validates history) ...")
        ok, miss = fetch_prices(universe, cache, highs, lows, args.fast)
        print(f"Fetched/cached {ok} series; {len(miss)} failures.")
        if miss[:10]:
            print("  sample failures:", miss[:10])

    bench = cache.get("__BENCH__", {})
    if not bench:
        sys.exit("No benchmark data in cache. Run a full fetch (drop --html-only).")

    have = [u["sym"] for u in universe if cache.get(u["sym"])]
    thresh = max(1, int(0.5 * len(have)))

    # Repair null daily bars from intraday (Yahoo gap pattern) — fetch-based
    # runs only; --html-only must stay offline.  Provenance records which
    # dates came from something other than Yahoo's daily bars.
    prov = load_json_cache(PROVENANCE)
    if not args.html_only:
        _rep = repair_intraday_gap(cache, highs, lows, have, thresh, prov=prov)
        if _rep:
            write_json_atomic(PROVENANCE, prov)
        purge_flat_carries(cache, highs, lows, have)

    # Reference window = last WINDOW benchmark dates that ALSO have broad stock
    # coverage, so a benchmark day that leads the stock cache can't null out RS.
    bench_dates = sorted(bench.keys())

    # Fill benchmark gaps.  Yahoo occasionally misses a day for index symbols
    # (^CRSLDX, ^NSEI, etc.) while publishing individual stocks.
    # Fallback chain: (1) Investing.com scrape → (2) synthetic from stock returns.
    _filled = fill_benchmark_gaps(bench, cache, have, thresh)
    if _filled:
        print(f"Filled {len(_filled)} missing benchmark date(s): "
              + ", ".join(f"{d} via {m}" for d, m in _filled))
        # Persist so fills survive future --html-only runs
        write_json_atomic(PRICE_CACHE, cache)
        for d, m in _filled:
            prov[d] = m
        write_json_atomic(PROVENANCE, prov)
    covered = [d for d in bench_dates
               if sum(1 for s in have if d in cache[s]) >= thresh]
    ref_dates = (covered or bench_dates)[-WINDOW:]
    if len(ref_dates) < WINDOW:
        print(f"Warning: only {len(ref_dates)} usable days with broad coverage.")
    if ref_dates and bench_dates[-1] != ref_dates[-1]:
        print(f"Note: window ends {ref_dates[-1]} — benchmark has data through "
              f"{bench_dates[-1]} but stocks don't yet; run with --refresh.")

    # Breadth oscillator uses ALL stock dates (not just benchmark dates), since
    # it only needs advancers/decliners.  Yahoo can occasionally miss a day for
    # the benchmark index (e.g. ^CRSLDX) while still publishing individual stocks.
    _all_stock_dates = set()
    for s in have:
        _all_stock_dates.update(cache[s].keys())
    breadth_dates = sorted(d for d in _all_stock_dates
                           if sum(1 for s in have if d in cache[s]) >= thresh)

    # ---- group members and compute RS for one classification level ----
    skipped_breaks = []

    def compute(level):
        groups = defaultdict(list)
        for u in universe:
            g = u[level]
            if g:
                groups[g].append(u)
        out = []
        for gname, members in groups.items():
            series, stocks = [], []
            for u in members:
                ser = cache.get(u["sym"])
                if not ser:
                    continue
                # a corporate action inside the RS window would swamp the equal-weight
                # group index (a "+2000% day" is a demerger, not performance) — leave
                # such a stock out of the aggregate entirely.
                if last_break_date({d: ser[d] for d in ref_dates if d in ser},
                                   len(ref_dates)):
                    skipped_breaks.append(u["sym"])
                    continue
                series.append(ser)
                srs, _ = equal_weight_rs([ser], bench, ref_dates)   # single-stock RS
                if srs is not None:
                    ef, price = ema_flags(ser)
                    brk = last_break_date(ser, 252)   # restart metrics after a demerger
                    stocks.append({"name": u["name"], "sym": u["sym"],
                                   "rs": srs, "pct": percentrank_inc(srs, srs[-1]),
                                   "ema": ef, "ltp": price,
                                   "rse": rs_ema_flag(ser, bench),
                                   "hi52": pct_off_high(highs.get(u["sym"], {}), price,
                                                        since=brk),
                                   "adr": adr_pct(highs.get(u["sym"], {}),
                                                  lows.get(u["sym"], {}), since=brk)})
            if not series:
                continue
            rs, n = equal_weight_rs(series, bench, ref_dates)
            if rs is None:
                continue
            stocks.sort(key=lambda x: x["pct"], reverse=True)
            out.append({"name": gname, "n": n, "rs": rs,
                        "pct": percentrank_inc(rs, rs[-1]), "members": stocks})
        out.sort(key=lambda x: x["pct"], reverse=True)
        return out

    levels = [(key, label, compute(key)) for key, label in LEVELS]
    print("Computed RS for " +
          ", ".join(f"{len(items)} {label.lower()}" for _, label, items in levels) + ".")
    if skipped_breaks:
        uniq = sorted(set(skipped_breaks))
        print(f"Excluded {len(uniq)} stock(s) from the group index — corporate action "
              f"inside the {WINDOW}-day RS window: {uniq[:12]}")

    # market-breadth oscillator over the full cached history
    breadth = None
    try:
        bdates, bosc, bn = compute_breadth(universe, cache, breadth_dates)
        macros = compute_macro_breadth(universe, cache, breadth_dates)
        breadth = {"dates": bdates, "osc": bosc, "n": bn, "macros": macros,
                   "divergence": detect_breadth_divergence(
                       cache.get("__BENCH__", {}), bdates, bosc)}
        if bosc:
            print(f"Breadth oscillator: {len(bosc)} days "
                  f"({bdates[0]} → {bdates[-1]}), latest {bosc[-1]:+.1f} "
                  f"({len(macros)} macro charts)")
        else:
            print("Breadth oscillator: not enough history (run --refresh for more).")
    except Exception as e:
        print("breadth calc failed:", e)

    n_stocks = sum(1 for u in universe if cache.get(u["sym"]))
    level_members = set()
    for _key, _label, items in levels:
        for it in items:
            for m in it["members"]:
                level_members.add(m["sym"])
    n_window = len(level_members)
    excluded = sorted(u["sym"] for u in universe
                      if cache.get(u["sym"]) and u["sym"] not in level_members)
    if excluded:
        print(f"Window coverage: {n_window}/{n_stocks} stocks. "
              f"{len(excluded)} not in the view (no full window data today): "
              f"{excluded[:12]}{' …' if len(excluded) > 12 else ''}")

    # ---- Phase 4: ranking archive + daily deltas vs the previous snapshot ----
    prev_snap = load_previous_snapshot()
    window_end = ref_dates[-1] if ref_dates else ""
    append_snapshot(levels, window_end)
    # deltas only vs a genuinely EARLIER snapshot (same-day rebuilds show none)
    if prev_snap and prev_snap.get("end") != window_end:
        pg = prev_snap.get("g", {})
        pm = prev_snap.get("m", {})
        for key, _l, items in levels:
            for it in items:
                p = pg.get(key, {}).get(it["name"])
                it["dp"] = round((it["pct"] - p) * 100, 1) if p is not None else None
                for stock in it["members"]:
                    q = pm.get(stock["sym"])
                    stock["d"] = (round((stock["pct"] - q) * 100, 1)
                                  if q is not None else None)

    ipo = build_ipo_watch(universe, cache, set(excluded),
                          cache.get("__BENCH__", {}))
    rotation = compute_rotation(universe, cache, cache.get("__BENCH__", {}),
                                breadth_dates) if breadth_dates else \
        {"dates": [], "groups": []}
    if ipo:
        print(f"IPO watch: {len(ipo)} new listing(s) awaiting their first "
              f"{WINDOW}-day ranking: {[i['s'] for i in ipo[:8]]}")

    meta = {
        "drange": f"{ref_dates[0]} → {ref_dates[-1]}" if ref_dates else "n/a",
        "window_dates": ref_dates,
        "gen": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_stocks": n_stocks,
        "n_window": n_window,
        "excluded": excluded,
        "src": prov,
        "ipo": ipo,
    }
    page = build_html(levels, meta, breadth)
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Wrote {OUT_HTML}")
    save_rs_json(levels, breadth, meta, RS_DATA_JSON, rotation)
    print(f"Wrote {RS_DATA_JSON}")
    write_daily_report(os.path.join(HERE, "daily_report.html"),
                       meta, breadth, levels, ipo)
    print(f"Wrote {os.path.join(HERE, 'daily_report.html')}")


if __name__ == "__main__":
    main()
