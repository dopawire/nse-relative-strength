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
import sys
import csv
import json
import time
import math
import html
import random
import argparse
import datetime as dt
import threading
import concurrent.futures as cf
from collections import defaultdict, Counter

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_CSV   = os.path.join(HERE, "nse_stock_master.csv")   # NSE 4-level universe
PRICE_CACHE  = os.path.join(HERE, ".yh_price_cache.json")   # {sym: {date: close}}
HIGH_CACHE   = os.path.join(HERE, ".yh_high_cache.json")    # {sym: {date: intraday high}}
LOW_CACHE    = os.path.join(HERE, ".yh_low_cache.json")     # {sym: {date: intraday low}}
OUT_HTML     = os.path.join(HERE, "rs_view.html")
RS_DATA_JSON = os.path.join(HERE, "rs_data.json")

# Yahoo Finance chart API (free, no key). NSE cash symbols use the ".NS" suffix.
YH_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
YH_HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")}

WINDOW         = 26            # trading days in the RS window (matches the sheet)
FULL_RANGE     = "2y"         # first-fetch history: ~500 bars (200-EMA + breadth warm-up)
APPEND_RANGE   = "1mo"        # incremental daily top-up (covers holidays/long weekends)
MIN_BARS       = 200          # below this a cached symbol is refetched with FULL_RANGE
EMA_PERIODS    = [20, 50, 100, 150, 200]   # per-stock EMAs + "price above EMA" filter
ADR_PERIOD     = 20            # Average Daily Range lookback (Qullamaggie's 20-day ADR%)
# A single-day move beyond this is a corporate action (demerger/split/bonus) or a data
# error, NOT trading: NSE circuit limits make genuine >40% daily moves essentially
# impossible. Metrics restart after such a break so pre-event prices can't leak in
# (e.g. ABFRL's pre-demerger 268.95 must not count as its 52-week high).
CORP_ACTION_JUMP = 0.40
BENCHMARK_NAME = "NIFTY 500"
BENCH_YSYM     = "^CRSLDX"     # Yahoo ticker for NIFTY 500 (NIFTY 50 = ^NSEI)
YH_WORKERS     = 8            # concurrent Yahoo fetches
IST            = dt.timezone(dt.timedelta(hours=5, minutes=30))   # NSE trading day

# 4-level NSE classification -> tabs. (csv column, tab label)
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
            l = lw[i] if i < len(lw) else None
            hi[day] = float(h) if h is not None else float(c)
            lo[day] = float(l) if l is not None else float(c)
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


def repair_intraday_gap(cache, highs, lows, have, thresh, today=None):
    """Yahoo occasionally serves null DAILY bars for sessions the market was
    open, while its intraday bars exist (Aug 28 2026 — whole market; Jul 28 —
    indices only).  For each candidate weekday that lacks broad stock coverage
    (strictly PAST days — never a session in progress), fill every missing
    symbol from its 5m bars.  Also self-heals bogus benchmark bars: if the
    cached bench close deviates >1% from the index's intraday close, replace
    it.  Returns the list of repaired dates."""
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
        cov = sum(1 for s in have if day in cache.get(s, {}))
        bench_missing = day not in bench
        if cov >= thresh and not bench_missing:
            continue                       # healthy day — nothing to do
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
        with cf.ThreadPoolExecutor(max_workers=YH_WORKERS) as ex:
            for key, ysym in jobs:
                bar = intraday_day(ysym, day)
                if not bar:
                    continue
                c, h, l = bar
                cache.setdefault(key, {})[day] = c
                highs.setdefault(key, {})[day] = h
                lows.setdefault(key, {})[day] = l
                filled += 1
        if filled:
            repaired.append(day)
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
#  RS maths
# --------------------------------------------------------------------------- #
def percentrank_inc(arr, x):
    """Excel PERCENTRANK.INC(array, x)."""
    a = sorted(v for v in arr if v is not None)
    n = len(a)
    if n < 2:
        return 0.0
    # test the top end FIRST: on a perfectly flat series a[0] == a[-1], and Excel
    # scores x as 1.0 (it is >= the max), not 0.0.
    if x >= a[-1]:
        return 1.0
    if x <= a[0]:
        return 0.0
    for i in range(n - 1):
        if a[i] == x:
            return i / (n - 1)
        if a[i] < x < a[i + 1]:
            frac = (x - a[i]) / (a[i + 1] - a[i])
            return (i + frac) / (n - 1)
    return 1.0


def ema_flags(closes_by_date):
    """For a stock's {date: close}, return (flags, price) where flags is a list
    (aligned with EMA_PERIODS) of: 1 = last price >= EMA, 0 = below, -1 = not
    enough history. EMA is seeded with the SMA of the first `period` closes
    (standard method) so long series give an accurate 200-day EMA."""
    dates = sorted(closes_by_date)
    closes = [closes_by_date[d] for d in dates]
    if not closes:
        return [-1] * len(EMA_PERIODS), None
    price = closes[-1]
    flags = []
    for period in EMA_PERIODS:
        if len(closes) < period:
            flags.append(-1)
            continue
        k = 2.0 / (period + 1)
        e = sum(closes[:period]) / period          # SMA seed
        for c in closes[period:]:
            e = c * k + e * (1 - k)
        flags.append(1 if price >= e else 0)
    return flags, price


def rs_ema_flag(ser, bench_series, period=21):
    """TradingView-style RS line = stock_close / benchmark_close.  Return 1 when
    the latest ratio is >= its EMA(`period`), 0 when below, -1 when there isn't
    enough shared history (< period common dates).  Same SMA-seeded EMA as
    ema_flags, so long series are accurate."""
    dates = [d for d in sorted(ser) if d in bench_series]
    if len(dates) < period:
        return -1
    ratios = [ser[d] / bench_series[d] for d in dates]
    k = 2.0 / (period + 1)
    e = sum(ratios[:period]) / period            # SMA seed
    for r in ratios[period:]:
        e = r * k + e * (1 - k)
    return 1 if ratios[-1] >= e else 0


def last_break_date(closes_by_date, lookback):
    """Date of the most recent corporate-action-style discontinuity within the last
    `lookback` sessions, or None. Prices before that date describe a different
    security (post-demerger/split) and must not be mixed with prices after it."""
    dates = sorted(closes_by_date)[-lookback:]
    brk = None
    for i in range(1, len(dates)):
        a, c = closes_by_date[dates[i - 1]], closes_by_date[dates[i]]
        if a > 0:
            r = c / a
            if r > 1 + CORP_ACTION_JUMP or r < 1 - CORP_ACTION_JUMP:
                brk = dates[i]          # keep the LAST one
    return brk


def pct_off_high(highs_by_date, price, lookback=252, since=None):
    """% `price` (latest close) sits BELOW the trailing 52-week high (≈252 trading
    days). The high is the max of daily INTRADAY highs — matching how screeners /
    TradingView report the 52-week high — not the highest close. 0 = at a new high;
    20 = 20% off. None if no high history cached (run --refresh to populate)."""
    if price is None or not highs_by_date:
        return None
    dates = sorted(highs_by_date)[-lookback:]
    if since:
        dates = [d for d in dates if d >= since]   # ignore pre-corporate-action prices
    highs = [highs_by_date[d] for d in dates]
    if not highs:
        return None
    hi = max(highs)
    if hi <= 0:
        return None
    return (hi - price) / hi * 100.0


def adr_pct(highs_by_date, lows_by_date, period=ADR_PERIOD, since=None):
    """Average Daily Range % over the last `period` sessions — the volatility gauge
    swing traders screen on (Qullamaggie's formula):

        ADR% = 100 * ( average(High / Low over N days) - 1 )

    e.g. 5 means the stock swings ~5% between its high and low on a typical day.
    None if there isn't enough paired high/low history.

    Zero-range bars (high == low) are SKIPPED, and the window walks further back to
    still average `period` real sessions. Such bars are not volatility data: on an NSE
    holiday Yahoo emits a phantom carry-forward bar (H=L=C=previous close) for stocks
    even though the index has no bar at all — 2026-06-26 did this to 96% of the
    universe — and for an untraded/circuit-locked day there is simply no range to
    measure. Averaging those zeroes in understates ADR for essentially every stock."""
    dates = sorted(d for d in highs_by_date if d in lows_by_date)
    if since:
        dates = [d for d in dates if d >= since]   # ignore pre-corporate-action bars
    ratios = []
    for d in reversed(dates):
        h, l = highs_by_date[d], lows_by_date[d]
        if h and l and l > 0 and h > l:
            ratios.append(h / l)
            if len(ratios) >= period:
                break
    if len(ratios) < max(2, period // 2):
        return None
    return (sum(ratios) / len(ratios) - 1.0) * 100.0


def equal_weight_rs(members_series, bench_series, ref_dates):
    """
    members_series: list of {date:close} for constituents.
    bench_series:    {date:close} for NIFTY 50.
    ref_dates:       ordered list of the WINDOW dates to evaluate on.
    Returns (rs_series, n_used) or (None, 0).
    """
    d0 = ref_dates[0]
    # benchmark normalised to base 100
    if d0 not in bench_series:
        return None, 0
    bench_base = bench_series[d0]
    bench_norm = []
    for d in ref_dates:
        if d not in bench_series:
            return None, 0
        bench_norm.append(bench_series[d] / bench_base * 100.0)

    # equal-weight index of constituents present on the base date
    valid = [s for s in members_series if d0 in s and s[d0]]
    if not valid:
        return None, 0
    ewi = []
    for d in ref_dates:
        vals = []
        for s in valid:
            if d in s and s[d0]:
                vals.append(s[d] / s[d0] * 100.0)
        if not vals:
            return None, 0
        ewi.append(sum(vals) / len(vals))

    rs = [ewi[i] / bench_norm[i] for i in range(len(ref_dates))]
    return rs, len(valid)


# --------------------------------------------------------------------------- #
#  Market-breadth oscillator (Zanger / McClellan style)
# --------------------------------------------------------------------------- #
def compute_breadth(universe, cache, covered_dates):
    """McClellan-style breadth oscillator from daily advancers vs decliners.

      RANA[d]  = (advances - declines) / (advances + declines) * 1000
      osc[d]   = EMA19(RANA) - EMA39(RANA)
    Oscillates around zero; extreme highs/lows precede reversals.
    Returns (dates, osc_values, n_stocks) with the EMA warm-up trimmed.
    """
    series = [cache[u["sym"]] for u in universe if cache.get(u["sym"])]
    rana, rdates = [], []
    for i in range(1, len(covered_dates)):
        prev, cur = covered_dates[i - 1], covered_dates[i]
        adv = dec = 0
        for s in series:
            a = s.get(prev); b = s.get(cur)
            if a is None or b is None:
                continue
            if b > a:
                adv += 1
            elif b < a:
                dec += 1
        if adv + dec == 0:
            continue
        rana.append((adv - dec) / (adv + dec) * 1000.0)
        rdates.append(cur)
    if len(rana) < 2:
        return [], [], len(series)

    def ema(vals, span):
        k = 2.0 / (span + 1); out = []; e = vals[0]
        for v in vals:
            e = v * k + e * (1 - k)
            out.append(e)
        return out

    e19, e39 = ema(rana, 19), ema(rana, 39)
    osc = [a - b for a, b in zip(e19, e39)]
    warm = min(39, max(0, len(osc) // 4))   # drop EMA warm-up
    return rdates[warm:], osc[warm:], len(series)


def render_breadth_svg(dates, osc, n_stocks):
    if not osc or len(osc) < 2:
        return ('<div class="brdempty">Not enough price history cached for the breadth '
                'oscillator. Run <code>python3 build_rs.py --refresh</code> to pull ~6+ '
                'months, then reopen.</div>')
    n = len(osc)
    # width scales with time so ~2 years breathe (horizontal scroll); ~4.2px/day
    L, R, T, B = 52, 44, 18, 46   # R roomy so the right-side y-labels aren't clipped
    ph = 300
    pw = max(640.0, 4.2 * (n - 1))
    W, H = L + pw + R, T + ph + B
    amax = max(abs(min(osc)), abs(max(osc)))
    ymax = max(20.0, math.ceil(amax / 10.0) * 10.0)

    def X(i): return L + pw * i / (n - 1)
    def Y(v): return T + ph * (1 - (v + ymax) / (2 * ymax))

    p = []
    # overbought / oversold zones
    if 40 < ymax:
        p.append(f'<rect x="{L}" y="{T}" width="{pw:.1f}" height="{Y(40)-T:.1f}" fill="#eaf7f0"/>')
        p.append(f'<rect x="{L}" y="{Y(-40):.1f}" width="{pw:.1f}" '
                 f'height="{T+ph-Y(-40):.1f}" fill="#fdeceb"/>')
    # horizontal gridlines + y-scale on BOTH ends (left stays visible at scroll start)
    step = 20 if ymax <= 80 else 40
    v = -ymax
    while v <= ymax + 0.1:
        y = Y(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw:.1f}" y2="{y:.1f}" '
                 f'stroke="{"#9aa6b2" if v==0 else "#edf1f4"}" '
                 f'stroke-width="{1.4 if v==0 else 1}"/>')
        p.append(f'<text x="{L-7}" y="{y+3:.1f}" font-size="10" fill="#7a8794" '
                 f'text-anchor="end">{int(v):+d}</text>')
        p.append(f'<text x="{L+pw+6:.1f}" y="{y+3:.1f}" font-size="10" '
                 f'fill="#7a8794">{int(v):+d}</text>')
        v += step
    # dashed +/-40 reversal guides
    for g in (40, -40):
        if abs(g) < ymax:
            p.append(f'<line x1="{L}" y1="{Y(g):.1f}" x2="{L+pw:.1f}" y2="{Y(g):.1f}" '
                     f'stroke="#c0392b" stroke-width="1" stroke-dasharray="4 4" opacity="0.45"/>')

    # ---- time axis: month gridlines + labels (spaced), year boundaries + labels ----
    first_idx, order = {}, []
    for i, d in enumerate(dates):
        ym = d[:7]
        if ym not in first_idx:
            first_idx[ym] = i
            order.append(ym)
    last_label_x = -1e9
    prev_year = None
    for k, ym in enumerate(order):
        i0 = first_idx[ym]
        i1 = (first_idx[order[k + 1]] - 1) if k + 1 < len(order) else n - 1
        span = i1 - i0 + 1
        mx = X(i0)
        year = ym[:4]
        is_year_start = year != prev_year
        prev_year = year
        # month gridline (year boundary is a touch stronger)
        p.append(f'<line x1="{mx:.1f}" y1="{T}" x2="{mx:.1f}" y2="{T+ph}" '
                 f'stroke="{"#d3dae1" if is_year_start else "#eef1f4"}" '
                 f'stroke-width="{1.3 if is_year_start else 1}"/>')
        # month label at the month's midpoint; skip tiny partial edge months and
        # anything that would collide with the previous label
        midx = X((i0 + i1) / 2)
        mon = dt.date.fromisoformat(ym + "-01").strftime("%b")
        if span >= 6 and (midx - last_label_x) >= 24:
            p.append(f'<text x="{midx:.1f}" y="{T+ph+16}" font-size="10" fill="#7a8794" '
                     f'text-anchor="middle">{mon}</text>')
            last_label_x = midx
        # year label under the first month of each year (and the very first month)
        if is_year_start:
            p.append(f'<text x="{mx:.1f}" y="{T+ph+34}" font-size="11" font-weight="700" '
                     f'fill="#46505c" text-anchor="middle">{year}</text>')

    # oscillator line, coloured green above zero / red below
    for i in range(1, n):
        col = "#1e7a4d" if (osc[i-1] + osc[i]) / 2 >= 0 else "#c0392b"
        p.append(f'<line x1="{X(i-1):.1f}" y1="{Y(osc[i-1]):.1f}" '
                 f'x2="{X(i):.1f}" y2="{Y(osc[i]):.1f}" stroke="{col}" stroke-width="1.6"/>')
    # last point marker
    lx, ly = X(n - 1), Y(osc[-1])
    p.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="#111"/>')
    # interactive crosshair + hover dot (moved by JS)
    p.append(f'<line id="brdcross" x1="0" y1="{T}" x2="0" y2="{T+ph}" '
             f'stroke="#5a6672" stroke-width="1" stroke-dasharray="3 3" '
             f'style="visibility:hidden"/>')
    p.append('<circle id="brddot" r="3.5" fill="#111" stroke="#fff" '
             'stroke-width="1.5" style="visibility:hidden"/>')

    svg = (f'<svg id="brdsvg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" class="brdsvg">{"".join(p)}</svg>')
    # data + geometry for the hover layer
    cfg = json.dumps({"dates": dates, "osc": [round(o, 2) for o in osc],
                      "L": L, "T": T, "pw": pw, "ph": ph, "ymax": ymax, "W": W, "H": H})
    script = (
        '<script>(function(){'
        f'var C={cfg};'
        'var svg=document.getElementById("brdsvg"),cross=document.getElementById("brdcross"),'
        'dot=document.getElementById("brddot"),tip=document.getElementById("brdtip"),'
        'scroll=document.getElementById("brdscroll");'
        'var n=C.osc.length;'
        'function X(i){return C.L+C.pw*i/(n-1);}'
        'function Y(v){return C.T+C.ph*(1-(v+C.ymax)/(2*C.ymax));}'
        'function fmt(s){var m=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];'
        'var a=s.split("-");return a[2]+" "+m[+a[1]-1]+" "+a[0];}'
        'function move(e){'
        'var r=svg.getBoundingClientRect(),sx=C.W/r.width;'
        'var x=(e.clientX-r.left)*sx;'
        'var i=Math.round((x-C.L)/C.pw*(n-1));if(i<0)i=0;if(i>n-1)i=n-1;'
        'var px=X(i),py=Y(C.osc[i]);'
        'cross.setAttribute("x1",px);cross.setAttribute("x2",px);cross.style.visibility="visible";'
        'dot.setAttribute("cx",px);dot.setAttribute("cy",py);dot.style.visibility="visible";'
        'var val=C.osc[i];'
        'tip.innerHTML="<b>"+fmt(C.dates[i])+"</b><span>"+(val>=0?"+":"")+val.toFixed(1)+"</span>";'
        'tip.style.visibility="visible";'
        'var cx=(e.clientX-scroll.getBoundingClientRect().left)+scroll.scrollLeft;'
        'tip.style.left=cx+"px";tip.style.top=(py*(r.height/C.H)-34)+"px";'
        '}'
        'function hide(){cross.style.visibility="hidden";dot.style.visibility="hidden";'
        'tip.style.visibility="hidden";}'
        'svg.addEventListener("mousemove",move);svg.addEventListener("mouseleave",hide);'
        '})();</script>')
    return (f'<div class="brdscroll" id="brdscroll">{svg}'
            f'<div class="brdtip" id="brdtip"></div></div>{script}')


# --------------------------------------------------------------------------- #
#  HTML rendering
# --------------------------------------------------------------------------- #
def sparkline_svg(series, w=150, h=34):
    if not series:
        return ""
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1.0
    n = len(series)
    hi_idx = max(range(n), key=lambda i: series[i])   # highest bar -> bright
    gap = 1.5
    bw = (w - gap * (n - 1)) / n
    bars = []
    for i, v in enumerate(series):
        bh = 3 + (v - lo) / rng * (h - 4)
        x = i * (bw + gap)
        y = h - bh
        color = "#1e7a4d" if i == hi_idx else "#a9dcc0"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                    f'height="{bh:.1f}" fill="{color}" rx="0.6"/>')
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'preserveAspectRatio="none">{"".join(bars)}</svg>')


def green_bg(pct):
    """pct in 0..1 -> white..green background like the sheet's gradient."""
    r = round(255 + (46 - 255) * pct)
    g = round(255 + (158 - 255) * pct)
    b = round(255 + (110 - 255) * pct)
    text = "#0a3d24" if pct < 0.55 else "#ffffff"
    return f"background:rgb({r},{g},{b});color:{text};"


EMA_HEAD_JS = "".join(f'<th class=\\"eh\\">{p}</th>' for p in EMA_PERIODS)


def render_rows(items, gid, members_out):
    """items: list of dicts {name, n, rs, pct, members}. Pre-sorted desc by pct.

    Each group is its own <tbody> holding a clickable header row plus an EMPTY
    hidden sub-row. The constituent stock rows are NOT emitted here — instead the
    member data for each group is stashed in `members_out[gid]` (embedded as JSON)
    and the sub-table is built lazily in the browser on expand/filter. This keeps
    the initial DOM tiny (just the group headers) so the page loads instantly
    instead of choking on ~9,500 inline SVG sparklines.

    Returns the next free gid so ids stay unique across all level tabs."""
    out = []
    for it in items:
        spark = sparkline_svg(it["rs"])
        bg = green_bg(it["pct"])
        nm = html.escape(it["name"])
        gidv = f"g{gid}"
        members_out[gidv] = [
            {"n": m["name"], "s": m["sym"], "p": round(m["pct"], 4),
             "r": [round(x, 3) for x in m["rs"]],
             "e": m.get("ema") or [-1] * len(EMA_PERIODS),
             "b": m.get("rse", -1),
             "l": (round(m["ltp"], 2) if m.get("ltp") else None),
             "h": (round(m["hi52"], 1) if m.get("hi52") is not None else None),
             "a": (round(m["adr"], 2) if m.get("adr") is not None else None)}
            for m in it["members"]
        ]
        out.append(
            f'<tbody class="gb" data-gid="{gidv}" data-pct="{it["pct"]:.6f}" data-name="{nm}">'
            f'<tr class="grp">'
            f'<td class="nm"><input type="checkbox" class="gpick" '
            f'title="select all stocks in this group"><span class="car">&#9656;</span>{nm}'
            f'<span class="cnt">{it["n"]}</span></td>'
            f'<td class="sp">{spark}</td>'
            f'<td class="pc" style="{bg}">{it["pct"]*100:.0f}%</td></tr>'
            f'<tr class="sub hide"><td colspan="3" class="subcell"></td></tr>'
            f'</tbody>'
        )
        gid += 1
    return "\n".join(out), gid


def build_html(levels, meta, breadth=None):
    """levels: ordered list of (key, label, items) — one grouping tab each."""
    if breadth and breadth.get("osc"):
        svg = render_breadth_svg(breadth["dates"], breadth["osc"], breadth["n"])
        last = breadth["osc"][-1]
        span = (f'{breadth["dates"][0]} → {breadth["dates"][-1]}'
                if breadth["dates"] else "")
        brd_html = (
            f'<div class="brdhead">NSE Market Breadth Oscillator'
            f'<span> &middot; McClellan-style: 19- vs 39-day EMA of ratio-adjusted '
            f'(advancers &minus; decliners) across {breadth["n"]} stocks &middot; {span}</span></div>'
            f'{svg}'
            f'<div class="brdcap">Latest reading <b>{last:+.1f}</b>. '
            f'Extreme lows (&approx; &minus;40 and below) flag oversold / possible bottoms; '
            f'extreme highs (&approx; +40 and above) flag overbought &mdash; reversal warnings, '
            f'the way Dan Zanger reads advance&ndash;decline breadth.</div>'
            f'<blockquote class="brdq">Zanger: &ldquo;I use one custom oscillator in particular '
            f'which uses market breadth advance-decline data to give me a heads up on trend '
            f'strength and potential reversals. When it hits extreme lows or highs, it usually '
            f'means a reversal of some sort is ahead and it&rsquo;s time to take some profits.&rdquo;'
            f'<span>More often than not, the number of advancing versus declining issues provides '
            f'a leading indicator of where stocks are headed.</span></blockquote>')
    else:
        brd_html = ('<div class="brdempty">Not enough price history cached for the breadth '
                    'oscillator. Run <code>python3 build_rs.py --refresh</code> to pull ~6+ '
                    'months, then reopen.</div>')
    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relative Strength &mdash; Sectors &amp; Industries</title>
<style>
 :root{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;}
 body{margin:0;background:#f4f6f8;color:#1f2733;}
 header{padding:18px 24px;background:#fff;border-bottom:1px solid #e3e8ee;}
 header h1{margin:0;font-size:19px;}
 header .meta{margin-top:4px;font-size:12px;color:#6b7785;}
 .tabs{display:flex;gap:8px;padding:14px 24px 0;}
 .tab{padding:8px 16px;border:1px solid #d4dbe3;border-bottom:none;border-radius:8px 8px 0 0;
      background:#e9edf2;cursor:pointer;font-size:13px;font-weight:600;color:#46505c;}
 .tab.active{background:#fff;color:#1f2733;}
 .wrap{padding:0 24px 40px;}
 table{width:100%;max-width:860px;border-collapse:collapse;background:#fff;
       border:1px solid #e3e8ee;border-top:none;}
 thead th{position:sticky;top:0;background:#fafbfc;text-align:left;font-size:11px;
          letter-spacing:.04em;text-transform:uppercase;color:#7a8794;
          padding:10px 12px;border-bottom:1px solid #e3e8ee;cursor:pointer;user-select:none;}
 thead th.pc,td.pc{text-align:right;width:74px;}
 td{padding:7px 12px;border-bottom:1px solid #eef1f4;font-size:13px;vertical-align:middle;}
 td.nm{font-weight:600;color:#222b36;}
 td.nm .cnt{color:#9aa6b2;font-weight:400;font-size:11px;margin-left:7px;}
 td.sp{width:160px;}
 td.pc{font-weight:700;font-variant-numeric:tabular-nums;}
 .hide{display:none;}
 .note{max-width:760px;margin:14px 0 0;font-size:11.5px;color:#8a94a0;}
 tr.grp{cursor:pointer;}
 tr.grp:hover td{background:#f5f9f6;}
 td.nm .car{display:inline-block;width:11px;color:#9aa6b2;font-size:10px;
            margin-right:5px;transition:transform .12s;}
 td.nm .car.open{transform:rotate(90deg);}
 td.subcell{padding:0;background:#fbfcfd;border-bottom:1px solid #e3e8ee;}
 table.mtbl{width:100%;border:none;background:transparent;margin:0;}
 table.mtbl td{border-bottom:1px solid #eef2f5;padding:4px 12px;font-size:12px;}
 td.mnm{padding-left:4px!important;color:#3a4654;font-weight:500;}
 td.mnm .msym{color:#aab4c0;font-weight:400;font-size:10.5px;margin-left:7px;}
 td.msp{width:140px;}
 td.mpc{text-align:right;width:74px;font-weight:600;font-variant-numeric:tabular-nums;}
 td.mlt{text-align:right;width:78px;font-weight:600;font-variant-numeric:tabular-nums;
   color:#2b3542;}
 td.mhi{text-align:right;width:66px;font-weight:600;font-variant-numeric:tabular-nums;
   color:#b06a2c;}
 td.madr{text-align:right;width:62px;font-weight:600;font-variant-numeric:tabular-nums;
   color:#4a5bb0;padding-right:14px;}
 .searchbar{padding:14px 24px 0;display:flex;align-items:center;gap:10px;}
 .searchbar input{width:100%;max-width:420px;padding:9px 12px;font-size:13px;
   border:1px solid #d4dbe3;border-radius:8px;outline:none;}
 .searchbar input:focus{border-color:#1e7a4d;box-shadow:0 0 0 2px rgba(30,122,77,.12);}
 .searchbar #qinfo{font-size:12px;color:#8a94a0;white-space:nowrap;}
 .seltools{padding:10px 24px 0;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
 .seltools #selcount{font-size:12px;color:#46505c;font-weight:600;margin-right:4px;}
 .seltools button{padding:7px 12px;font-size:12px;font-weight:600;cursor:pointer;
   border:1px solid #d4dbe3;border-radius:7px;background:#fff;color:#46505c;}
 .seltools button:hover{border-color:#1e7a4d;color:#1e7a4d;}
 .seltools button.primary{background:#1e7a4d;border-color:#1e7a4d;color:#fff;}
 .seltools button.primary:hover{background:#176039;color:#fff;}
 .seltools #flash{font-size:12px;color:#1e7a4d;font-weight:600;}
 td.mck{width:26px;text-align:center;padding-left:14px!important;}
 td.nm input.gpick{margin-right:7px;vertical-align:middle;}
 input.pick,input.gpick{cursor:pointer;}
 .brdwrap{max-width:1000px;background:#fff;border:1px solid #e3e8ee;padding:16px 18px;}
 .brdhead{font-size:14px;font-weight:700;color:#222b36;margin-bottom:10px;}
 .brdhead span{font-weight:400;font-size:11.5px;color:#7a8794;}
 .brdscroll{position:relative;overflow-x:auto;overflow-y:hidden;
   border:1px solid #eef1f4;border-radius:6px;}
 .brdsvg{display:block;}
 .brdtip{position:absolute;transform:translateX(-50%);pointer-events:none;
   visibility:hidden;background:#111a24;color:#fff;font-size:11px;padding:4px 8px;
   border-radius:5px;white-space:nowrap;z-index:5;box-shadow:0 2px 8px rgba(0,0,0,.28);}
 .brdtip b{font-weight:700;margin-right:7px;}
 .brdtip span{font-variant-numeric:tabular-nums;}
 .brdcap{font-size:12px;color:#46505c;margin-top:10px;max-width:900px;line-height:1.5;}
 .brdq{margin:14px 0 0;padding:10px 14px;border-left:3px solid #1e7a4d;background:#f6faf8;
   font-size:12px;color:#46505c;font-style:italic;max-width:900px;line-height:1.5;}
 .brdq span{display:block;margin-top:8px;font-style:normal;color:#6b7785;}
 .brdempty{padding:30px;color:#8a94a0;font-size:13px;}
 .brdempty code{background:#eef1f4;padding:2px 5px;border-radius:4px;}
 .emabar{padding:10px 24px 0;display:flex;align-items:center;gap:7px;flex-wrap:wrap;}
 .emabar .lbl{font-size:12px;color:#46505c;font-weight:600;}
 .ematog{padding:6px 11px;font-size:12px;font-weight:600;cursor:pointer;
   border:1px solid #d4dbe3;border-radius:7px;background:#fff;color:#46505c;}
 .ematog:hover{border-color:#1e7a4d;color:#1e7a4d;}
 .ematog.on{background:#1e7a4d;border-color:#1e7a4d;color:#fff;}
 .emabar #emainfo{font-size:12px;color:#8a94a0;margin-left:2px;}
 table.mtbl thead th{position:static;background:#fbfcfd;color:#93a0ad;font-size:10px;
   text-transform:none;letter-spacing:0;padding:5px 6px;border-bottom:1px solid #eef2f5;text-align:center;}
 table.mtbl thead th.ehn{text-align:left;padding-left:6px;}
 table.mtbl thead th.ehp{text-align:right;}
 table.mtbl thead th.ehl{text-align:right;}
 table.mtbl thead th.ehh{text-align:right;width:66px;}
 table.mtbl thead th.eha{text-align:right;padding-right:14px;width:62px;}
 table.mtbl thead th.eh{width:30px;color:#7a8794;font-weight:700;}
 .hifilt{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#46505c;
   font-weight:600;padding:5px 11px;border:1px solid #d4dbe3;border-radius:7px;background:#fff;
   margin-left:6px;}
 .hifilt.on{border-color:#b06a2c;color:#8a4d1c;background:#fff8f1;}
 .hifilt.adr.on{border-color:#4a5bb0;color:#334090;background:#f5f6fd;}
 .hifilt input[type=number]{width:46px;padding:2px 4px;font-size:12px;font-weight:700;
   border:1px solid #d4dbe3;border-radius:5px;text-align:right;font-variant-numeric:tabular-nums;}
 .hifilt input[type=checkbox]{cursor:pointer;}
 td.e{width:30px;text-align:center;font-size:11px;font-weight:700;padding:4px 2px;}
 td.e[data-a="1"]{background:#e6f5ec;color:#1e7a4d;}
 td.e[data-a="1"]::after{content:"\\2713";}
 td.e[data-a="0"]{background:#fdecea;color:#e0a9a2;}
 td.e[data-a="0"]::after{content:"\\2717";}
 td.e[data-a="-1"]{color:#cdd5de;}
 td.e[data-a="-1"]::after{content:"\\2013";}
</style></head>
<body>
<header>
 <h1>Relative Strength &mdash; Sectors &amp; Industries</h1>
 <div class="meta">Equal-weighted &middot; benchmark __BENCH__ &middot; __WINDOW__-day window
   &middot; window __DRANGE__ &middot; generated __GEN__</div>
</header>
<div class="searchbar">
 <input id="q" type="search" placeholder="Search stock, sector or industry&hellip;" autocomplete="off">
 <span id="qinfo"></span>
</div>
<div class="seltools">
 <span id="selcount">0 selected</span>
 <button id="selvis">Select all shown</button>
 <button id="selclear">Clear</button>
 <button id="btncopy" class="primary">Copy for TradingView</button>
 <button id="btndl" class="primary">Download .txt</button>
 <span id="flash"></span>
</div>
<div class="emabar">
 <span class="lbl">Price above:</span>
__EMATOGS__
 <button class="ematog" id="emaclear" style="border-style:dashed;">clear</button>
 <label class="hifilt" id="hifilt" title="show only stocks within this % of their 52-week high">
   <input type="checkbox" id="hion"> within
   <input type="number" id="himax" value="20" min="0" max="100" step="1"> % of 52W high</label>
 <label class="hifilt adr" id="adrfilt" title="show only stocks whose 20-day Average Daily Range is at least this %">
   <input type="checkbox" id="adron"> ADR&#8805;
   <input type="number" id="adrmin" value="3" min="0" max="50" step="0.5"> %</label>
 <span id="emainfo"></span>
</div>
<div class="tabs">
__TABS__
 <div class="tab" data-t="brd">Market Breadth</div>
</div>
<div class="wrap">
__TABLES__
 <div id="brd" class="hide brdwrap">
__BRD__
 </div>
 <p class="note">RS_STS% = PERCENTRANK of the latest relative-strength ratio within its trailing
   __WINDOW__-day range. Count beside each name = constituents used. Click a row to expand its
   stocks; click a header to re-sort.</p>
</div>
<script>var MEMBERS=__MEMBERS__;var EMAHEAD='__EMAHEAD__';</script>
<script>
 // ---- constituent rows are built lazily in the browser (the data lives in
 //      MEMBERS as JSON) so the initial page is tiny and never hangs ----
 function esc(s){return String(s).replace(/[&<>"]/g,function(c){
   return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
 function spark(series,w,h){
   if(!series||!series.length) return '';
   var lo=Math.min.apply(null,series),hi=Math.max.apply(null,series);
   var rng=(hi-lo)||1,n=series.length,gap=1.5,bw=(w-gap*(n-1))/n,hiIdx=0;
   for(var i=1;i<n;i++) if(series[i]>series[hiIdx]) hiIdx=i;
   var bars='';
   for(var i=0;i<n;i++){
     var bh=3+(series[i]-lo)/rng*(h-4),x=i*(bw+gap),y=h-bh;
     var col=(i===hiIdx)?'#1e7a4d':'#a9dcc0';
     bars+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+
           '" height="'+bh.toFixed(1)+'" fill="'+col+'" rx="0.6"/>';
   }
   return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+
          '" preserveAspectRatio="none">'+bars+'</svg>';
 }
 function greenBg(pct){
   var r=Math.round(255+(46-255)*pct),g=Math.round(255+(158-255)*pct),
       b=Math.round(255+(110-255)*pct),text=pct<0.55?'#0a3d24':'#ffffff';
   return 'background:rgb('+r+','+g+','+b+');color:'+text+';';
 }
 function buildMembers(gid){
   var arr=MEMBERS[gid]||[],rows='';
   for(var j=0;j<arr.length;j++){
     var m=arr[j],sp=spark(m.r,120,22),bg=greenBg(m.p),ema='';
     for(var k=0;k<m.e.length;k++) ema+='<td class="e" data-a="'+m.e[k]+'"></td>';
     var ltp=(m.l!=null)?Number(m.l).toLocaleString(undefined,
       {minimumFractionDigits:2,maximumFractionDigits:2}):'&ndash;';
     var off=(m.h!=null)?('-'+m.h.toFixed(1)+'%'):'&ndash;';
     var adr=(m.a!=null)?(m.a.toFixed(1)+'%'):'&ndash;';
     var ck=sel.has(m.s)?' checked':'';
     rows+='<tr>'+
       '<td class="mck"><input type="checkbox" class="pick" data-sym="'+esc(m.s)+'"'+ck+'></td>'+
       '<td class="mnm">'+esc(m.n)+'<span class="msym">'+esc(m.s)+'</span></td>'+
       '<td class="msp">'+sp+'</td>'+
       '<td class="mpc" style="'+bg+'">'+Math.round(m.p*100)+'%</td>'+
       '<td class="mlt">'+ltp+'</td>'+
       '<td class="mhi">'+off+'</td>'+
       '<td class="madr">'+adr+'</td>'+ema+'</tr>';
   }
   var head='<thead><tr><th></th><th class="ehn">Stock</th><th>RS</th>'+
     '<th class="ehp">RS%</th><th class="ehl">LTP</th><th class="ehh">Off Hi</th>'+
     '<th class="eha">ADR%</th>'+EMAHEAD+'</tr></thead>';
   return '<table class="mtbl">'+head+'<tbody>'+rows+'</tbody></table>';
 }
 function ensureBuilt(body){
   if(body.dataset.built) return;
   body.querySelector('td.subcell').innerHTML=buildMembers(body.dataset.gid);
   body.dataset.built='1';
 }

 document.querySelectorAll('.tab').forEach(function(t){
   t.onclick=function(){
     document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
     t.classList.add('active');
     __TABIDS__.forEach(function(id){
       document.getElementById(id).classList.toggle('hide', t.dataset.t!==id);
     });
     var onTable = t.dataset.t!=='brd';   // search/select/filter only apply to the tables
     document.querySelector('.searchbar').style.display=onTable?'':'none';
     document.querySelector('.seltools').style.display=onTable?'':'none';
     document.querySelector('.emabar').style.display=onTable?'':'none';
     if(onTable) runSearch();
   };
 });
 // expand / collapse a group -> build its constituent stocks on first open
 document.querySelectorAll('table').forEach(function(tbl){
   tbl.addEventListener('click',function(e){
     if(e.target.tagName==='INPUT')return;   // don't toggle when ticking a checkbox
     var grp=e.target.closest('tr.grp'); if(!grp||!tbl.contains(grp))return;
     var body=grp.parentNode, sub=body.querySelector('tr.sub');
     if(sub.classList.contains('hide')) ensureBuilt(body);
     sub.classList.toggle('hide');
     grp.querySelector('.car').classList.toggle('open');
   });
 });

 // ---- filter: text search + "price above EMA(s)" + "near 52W high" (all AND) ----
 var qbox=document.getElementById('q'), qinfo=document.getElementById('qinfo');
 var emaSel=new Set();               // indices of active EMA toggles (AND logic)
 var emainfo=document.getElementById('emainfo');
 var hion=document.getElementById('hion'), himax=document.getElementById('himax');
 var hifilt=document.getElementById('hifilt');
 var adron=document.getElementById('adron'), adrmin=document.getElementById('adrmin');
 var adrfilt=document.getElementById('adrfilt');
 var hiOn=false, hiMax=20, adrOn=false, adrMin=3;
 function memberMatch(m,q,gmatch){
   if(!(q==='' || gmatch || (m.n+' '+m.s).toLowerCase().indexOf(q)>=0)) return false;
   for(var i of emaSel){ if(m.e[i]!==1) return false; }      // above ALL selected EMAs
   if(hiOn){ if(m.h==null || m.h>hiMax) return false; }      // within hiMax% of 52W high
   if(adrOn){ if(m.a==null || m.a<adrMin) return false; }    // ADR% at or above adrMin
   return true;
 }
 // members of a group that pass the CURRENT filter (all of them when no filter is on)
 function groupMatches(body){
   var arr=MEMBERS[body.dataset.gid]||[];
   var q=qbox.value.trim().toLowerCase();
   if(q==='' && !emaSel.size && !hiOn && !adrOn) return arr;
   var gmatch = q!=='' && body.dataset.name.toLowerCase().indexOf(q)>=0;
   return arr.filter(function(m){ return memberMatch(m,q,gmatch); });
 }
 function activeTable(){       // the visible LEVEL table (never an inner member table)
   var t=document.querySelector('.tab.active');
   if(!t || t.dataset.t==='brd') return null;
   return document.getElementById(t.dataset.t);
 }
 function runSearch(){
   var q=qbox.value.trim().toLowerCase();
   var filtering = q!=='' || emaSel.size>0 || hiOn || adrOn;
   var tbl=activeTable(); if(!tbl) return;
   var shown=0, stocks=0;
   tbl.querySelectorAll('tbody.gb').forEach(function(body){
     var grp=body.querySelector('tr.grp'), sub=body.querySelector('tr.sub');
     var car=grp.querySelector('.car'), cnt=grp.querySelector('.cnt');
     var arr=MEMBERS[body.dataset.gid]||[];
     if(cnt && cnt.dataset.orig===undefined) cnt.dataset.orig=cnt.textContent;
     if(!filtering){                 // reset to default collapsed view
       body.style.display=''; sub.classList.add('hide'); car.classList.remove('open');
       if(cnt) cnt.textContent=cnt.dataset.orig;   // restore full constituent count
       if(body.dataset.built)
         body.querySelectorAll('table.mtbl tbody tr').forEach(r=>r.style.display='');
       return;
     }
     var gmatch = q!=='' && body.dataset.name.toLowerCase().indexOf(q)>=0;
     var hits=[];
     for(var j=0;j<arr.length;j++){ if(memberMatch(arr[j],q,gmatch)) hits.push(j); }
     if(hits.length){
       ensureBuilt(body);
       var set={}; hits.forEach(function(i){set[i]=1;});
       body.querySelectorAll('table.mtbl tbody tr').forEach(function(r,idx){
         r.style.display=set[idx]?'':'none';
       });
       body.style.display=''; sub.classList.remove('hide'); car.classList.add('open');
       if(cnt) cnt.textContent=hits.length;   // show how many match the active filter
       shown++; stocks+=hits.length;
     } else { body.style.display='none'; }
   });
   qinfo.textContent = filtering ? (shown+' group(s), '+stocks+' stock(s)') : '';
   var bits=[];
   if(emaSel.size) bits.push('above '+emaSel.size+' EMA'+(emaSel.size>1?'s':''));
   if(hiOn) bits.push('\\u2264'+hiMax+'% off high');
   if(adrOn) bits.push('ADR\\u2265'+adrMin+'%');
   emainfo.textContent = bits.join(' \\u00b7 ');
 }
 qbox.addEventListener('input', runSearch);
 qbox.addEventListener('keydown', function(e){ if(e.key==='Escape'){qbox.value='';runSearch();} });

 // ---- "price above EMA" toggles ----
 document.querySelectorAll('.ematog[data-i]').forEach(function(btn){
   btn.onclick=function(){
     var i=+btn.dataset.i;
     if(emaSel.has(i)){ emaSel.delete(i); btn.classList.remove('on'); }
     else { emaSel.add(i); btn.classList.add('on'); }
     runSearch();
   };
 });
 document.getElementById('emaclear').onclick=function(){
   emaSel.clear();
   document.querySelectorAll('.ematog[data-i]').forEach(b=>b.classList.remove('on'));
   runSearch();
 };

 // ---- "within X% of 52-week high" filter ----
 function syncHi(){
   hiOn=hion.checked; hiMax=parseFloat(himax.value); if(isNaN(hiMax)) hiMax=0;
   hifilt.classList.toggle('on', hiOn); runSearch();
 }
 hion.addEventListener('change', syncHi);
 himax.addEventListener('input', function(){
   if(himax.value!=='' && !hion.checked){ hion.checked=true; }  // a real number auto-enables
   syncHi();
 });

 // ---- "ADR% >= X" (Average Daily Range) filter ----
 function syncAdr(){
   adrOn=adron.checked; adrMin=parseFloat(adrmin.value); if(isNaN(adrMin)) adrMin=0;
   adrfilt.classList.toggle('on', adrOn); runSearch();
 }
 adron.addEventListener('change', syncAdr);
 adrmin.addEventListener('input', function(){
   if(adrmin.value!=='' && !adron.checked){ adron.checked=true; }
   syncAdr();
 });

 // ---- multi-select -> TradingView export (state keyed by symbol) ----
 var sel=new Set();
 var selcount=document.getElementById('selcount'), flash=document.getElementById('flash');
 function syncDup(sym,on){    // mirror onto any already-built duplicate rows
   document.querySelectorAll('input.pick[data-sym="'+CSS.escape(sym)+'"]').forEach(x=>x.checked=on);
 }
 function updateCount(){ selcount.textContent=sel.size+' selected'; }
 function showFlash(msg){ flash.textContent=msg; setTimeout(()=>{flash.textContent='';},2200); }
 document.addEventListener('change',function(e){
   var t=e.target;
   if(t.classList.contains('pick')){
     if(t.checked) sel.add(t.dataset.sym); else sel.delete(t.dataset.sym);
     syncDup(t.dataset.sym,t.checked); updateCount();
   } else if(t.classList.contains('gpick')){
     var body=t.closest('tbody.gb');
     var matches=groupMatches(body);          // respect the active filter, not all constituents
     var pick={}; matches.forEach(function(m){ pick[m.s]=1;
       if(t.checked) sel.add(m.s); else sel.delete(m.s); });
     ensureBuilt(body);
     body.querySelectorAll('input.pick').forEach(function(cb){
       if(pick[cb.dataset.sym]) cb.checked=t.checked;   // only tick the filtered rows
     });
     matches.forEach(function(m){ syncDup(m.s,t.checked); });
     updateCount();
   }
 });
 function selectVisible(on){
   var tbl=activeTable(); if(!tbl) return;
   tbl.querySelectorAll('table.mtbl tr').forEach(function(r){
     if(r.offsetParent===null)return;            // only rows actually on screen
     var cb=r.querySelector('input.pick'); if(!cb)return;
     cb.checked=on;
     if(on) sel.add(cb.dataset.sym); else sel.delete(cb.dataset.sym);
     syncDup(cb.dataset.sym,on);
   });
   updateCount();
 }
 function clearSel(){
   sel.clear();
   document.querySelectorAll('input.pick,input.gpick').forEach(x=>x.checked=false);
   updateCount();
 }
 function tvText(){ return Array.from(sel).map(s=>'NSE:'+s+',').join('\\n'); }
 function copyTV(){
   if(!sel.size){ showFlash('nothing selected'); return; }
   var txt=tvText();
   if(navigator.clipboard && navigator.clipboard.writeText){
     navigator.clipboard.writeText(txt).then(()=>showFlash('copied '+sel.size),fallbackCopy.bind(null,txt));
   } else fallbackCopy(txt);
 }
 function fallbackCopy(txt){
   var ta=document.createElement('textarea'); ta.value=txt; document.body.appendChild(ta);
   ta.select(); try{document.execCommand('copy'); showFlash('copied '+sel.size);}catch(e){showFlash('copy failed');}
   document.body.removeChild(ta);
 }
 function downloadTV(){
   if(!sel.size){ showFlash('nothing selected'); return; }
   var blob=new Blob([tvText()],{type:'text/plain'});
   var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
   a.download='tradingview_watchlist.txt'; document.body.appendChild(a); a.click();
   document.body.removeChild(a); URL.revokeObjectURL(a.href); showFlash('downloaded '+sel.size);
 }
 document.getElementById('selvis').onclick=function(){selectVisible(true);};
 document.getElementById('selclear').onclick=clearSel;
 document.getElementById('btncopy').onclick=copyTV;
 document.getElementById('btndl').onclick=downloadTV;
 // sort whole groups (each group is one tbody.gb)
 document.querySelectorAll('th[data-k]').forEach(function(th){
   th.onclick=function(){
     var tbl=th.closest('table');
     var k=th.dataset.k, asc=th.dataset.asc==='1'; th.dataset.asc=asc?'0':'1';
     var bodies=[].slice.call(tbl.querySelectorAll('tbody.gb'));
     bodies.sort(function(a,b){
       var va=k==='pct'?parseFloat(a.dataset.pct):a.dataset.name.toLowerCase();
       var vb=k==='pct'?parseFloat(b.dataset.pct):b.dataset.name.toLowerCase();
       if(va<vb)return asc?-1:1; if(va>vb)return asc?1:-1; return 0;
     });
     bodies.forEach(b=>tbl.appendChild(b));
   };
 });
</script>
</body></html>"""
    ematogs = "\n".join(
        f' <button class="ematog" data-i="{i}">EMA{p}</button>'
        for i, p in enumerate(EMA_PERIODS))
    tabs = "\n".join(
        f' <div class="tab{" active" if i == 0 else ""}" data-t="{key}">'
        f'{label} ({len(items)})</div>'
        for i, (key, label, items) in enumerate(levels))
    members_out, gid = {}, 0
    table_parts = []
    for i, (key, label, items) in enumerate(levels):
        rows_html, gid = render_rows(items, gid, members_out)
        cls = "" if i == 0 else ' class="hide"'
        table_parts.append(
            f' <table id="{key}"{cls}><thead><tr>'
            f'<th data-k="name">{label}</th><th>Relative Strength</th>'
            f'<th class="pc" data-k="pct">RS_STS%</th></tr></thead>\n'
            f'{rows_html}\n </table>')
    tables = "\n".join(table_parts)
    # embed member data as JSON (built into rows lazily in the browser). Escape
    # "</" so a symbol/name can never prematurely close the <script> tag.
    members_json = json.dumps(members_out, separators=(",", ":")).replace("</", "<\\/")
    tabids = "[" + ",".join(f"'{k}'" for k, _, _ in levels) + ",'brd']"
    return (template
            .replace("__MEMBERS__", members_json)
            .replace("__EMAHEAD__", EMA_HEAD_JS)
            .replace("__EMATOGS__", ematogs)
            .replace("__TABS__", tabs)
            .replace("__TABLES__", tables)
            .replace("__TABIDS__", tabids)
            .replace("__BRD__", brd_html)
            .replace("__BENCH__", BENCHMARK_NAME)
            .replace("__WINDOW__", str(WINDOW))
            .replace("__DRANGE__", meta["drange"])
            .replace("__GEN__", meta["gen"]))


# --------------------------------------------------------------------------- #
#  JSON export for the FastAPI backend
# --------------------------------------------------------------------------- #
def save_rs_json(levels, breadth, meta, path):
    """Write precomputed RS data so the backend can serve it without recomputing."""
    data = {
        "meta": meta,
        "breadth": breadth if breadth else {"dates": [], "osc": [], "n": 0},
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
                    "l": round(m["ltp"], 2) if m.get("ltp") is not None else None,
                    "h": round(m["hi52"], 1) if m.get("hi52") is not None else None,
                    "a": round(m["adr"], 2) if m.get("adr") is not None else None,
                })
            level_data["groups"].append({
                "id": gid, "name": it["name"],
                "n": it["n"], "pct": round(it["pct"], 4),
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
        _lock_fh = open(os.path.join(HERE, ".build.lock"), "w")
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
    # runs only; --html-only must stay offline.
    if not args.html_only:
        repair_intraday_gap(cache, highs, lows, have, thresh)

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
        breadth = {"dates": bdates, "osc": bosc, "n": bn}
        if bosc:
            print(f"Breadth oscillator: {len(bosc)} days "
                  f"({bdates[0]} → {bdates[-1]}), latest {bosc[-1]:+.1f}")
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
    meta = {
        "drange": f"{ref_dates[0]} → {ref_dates[-1]}" if ref_dates else "n/a",
        "gen": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_stocks": n_stocks,
        "n_window": n_window,
        "excluded": excluded,
    }
    page = build_html(levels, meta, breadth)
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Wrote {OUT_HTML}")
    save_rs_json(levels, breadth, meta, RS_DATA_JSON)
    print(f"Wrote {RS_DATA_JSON}")


if __name__ == "__main__":
    main()
