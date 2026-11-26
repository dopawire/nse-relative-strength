"""RS maths: percentile rank, EMA flags, corporate-action breaks, ADR,
equal-weight group index vs the benchmark."""

import datetime as dt

from rs_engine.config import EMA_PERIODS, ADR_PERIOD, CORP_ACTION_JUMP, ILLIQUID_TURNOVER_CR

LISTING_SKIP = 10        # a new listing's first sessions: frenzy volume, left out of volume averages
WEEKLY_SMA = 10          # weeks — the weekly 10 SMA (≈ the 50-day line)
WEEKLY_SESSIONS = 160    # daily closes looked at: ~32 weeks, plenty for SMA10 + its streak


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


def rs_line(ser, bench_series, lookback=125):
    """TradingView-style RS line (stock/benchmark) + its 21-day EMA over the
    last `lookback` common dates.  Returns (dates, rs, ema21) or None."""
    days = [d for d in sorted(ser) if d in bench_series][-lookback:]
    if not days:
        return None
    rs = [ser[d] / bench_series[d] for d in days]
    k = 2.0 / 22
    ema = [rs[0]]
    for v in rs[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return days, rs, ema


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
        hi_v, lo_v = highs_by_date[d], lows_by_date[d]
        if hi_v and lo_v and lo_v > 0 and hi_v > lo_v:
            ratios.append(hi_v / lo_v)
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


def period_return(closes_by_date, sessions, calendar=None):
    """% change over the last `sessions` sessions, close to close (21 ≈ 1
    month, 63 ≈ 3 months).  None when the history is shorter or a
    corporate-action break falls inside the period (a demerger is not a
    gain).  With `calendar` (the market's sessions, ending on the as-of day)
    the period is counted in MARKET sessions, from the stock's close on or
    before the start session — so a stock that skipped days isn't measured
    over a longer stretch."""
    dates = sorted(closes_by_date)
    if calendar is not None:
        if len(calendar) <= sessions:
            return None
        start = calendar[-(sessions + 1)]
        base = [d for d in dates if d <= start]
        if not base:
            return None
        window = [base[-1]] + [d for d in dates if start < d <= calendar[-1]]
        if len(window) < 2:
            return None
    else:
        if len(dates) <= sessions:
            return None
        window = dates[-(sessions + 1):]
    if last_break_date({d: closes_by_date[d] for d in window}, sessions + 1):
        return None
    a, b = closes_by_date[window[0]], closes_by_date[window[-1]]
    return (b / a - 1) * 100.0 if a else None


def avg_turnover_cr(closes_by_date, volumes_by_date, sessions=20):
    """Average daily traded value (close × shares) over the last `sessions`
    sessions, in ₹ crore — the liquidity gauge of the scans.  None with fewer
    than half the sessions of volume data."""
    days = [d for d in sorted(volumes_by_date) if d in closes_by_date][-sessions:]
    if len(days) < max(1, sessions // 2):
        return None
    return sum(closes_by_date[d] * volumes_by_date[d] for d in days) / len(days) / 1e7


def rs_ratings(series_by_sym, as_of):
    """IBD-style RS rating 1-99 for every symbol: percentile rank of the
    weighted 12-month performance 2×3M + 6M + 9M + 12M (63 / 126 / 189 / 252
    sessions back, closes on/before `as_of`).  Periods longer than a stock's
    history reuse its 3M return; stocks without 3 months are unrated."""
    score = {}
    for sym, ser in series_by_sym.items():
        ds = [d for d in sorted(ser) if d <= as_of]
        if len(ds) <= 63:
            continue
        last = ser[ds[-1]]
        r = [last / ser[ds[-1 - n]] - 1 if len(ds) > n else None for n in (63, 126, 189, 252)]
        r = [x if x is not None else r[0] for x in r]
        score[sym] = 2 * r[0] + r[1] + r[2] + r[3]
    order = sorted(score, key=score.get)
    n = len(order)
    return {s: max(1, min(99, round(100 * (i + 1) / n))) for i, s in enumerate(order)}


def index_trend(closes_by_date):
    """Trend snapshot of an index ({date: close}) for the regime check:
    close, EMA flags (EMA_PERIODS), 1W / 1M / 3M % returns and % below the
    52-week closing high.  {} without data."""
    if not closes_by_date:
        return {}
    flags, price = ema_flags(closes_by_date)
    dates = sorted(closes_by_date)
    hi = max(closes_by_date[d] for d in dates[-252:])
    rnd = lambda v: round(v, 2) if v is not None else None   # noqa: E731
    return {"close": round(price, 2), "date": dates[-1], "ema": flags,
            "w1": rnd(period_return(closes_by_date, 5)),
            "m1": rnd(period_return(closes_by_date, 20)),
            "m3": rnd(period_return(closes_by_date, 63)),
            "off_high": round((1 - price / hi) * 100, 2) if hi else None}


def listing_vsince(closes, first_session):
    """For a stock listed after `first_session` (the start of the price
    history), the date its volume averages may start: after its first
    LISTING_SKIP sessions — listing-day volume (often 50–100× normal) would
    otherwise swamp every average for months.  None for older stocks."""
    ds = sorted(closes)
    return ds[LISTING_SKIP] if ds and ds[0] > first_session and len(ds) > LISTING_SKIP else None


def setup_metrics(closes, highs, lows, volumes, since=None, vsince=None):
    """Breakout-readiness gauges for one stock ({date: value} each):

      vr  today's volume ÷ the 50 sessions before it   (≥ 1.5 = volume surge)
      vd  10-session average volume ÷ the 50 before it  (< 0.85 = drying up)
      tt  10-session high-low range as % of the close   (small = tight)

    Zero-volume days count (an untraded day is real information).  None
    where there isn't enough history (after `since`, a corporate-action
    break, prices before it are a different security).  `vsince`: volume
    averages start there (a new listing's first sessions — listing_vsince)."""
    days = [d for d in sorted(closes) if d in volumes and (since is None or d >= since)
            and (vsince is None or d >= vsince)]
    out = {"vr": None, "vd": None, "tt": None}
    if len(days) >= 31:
        v = [volumes[d] for d in days]
        prior = v[-51:-1]
        avg = sum(prior) / len(prior)
        out["vr"] = round(v[-1] / avg, 2) if avg > 0 else None
        if len(days) >= 40:
            base = v[-60:-10]
            b = sum(base) / len(base)
            out["vd"] = round(sum(v[-10:]) / 10 / b, 2) if b > 0 else None
    hd = [d for d in sorted(highs) if d in lows and (since is None or d >= since)][-10:]
    if len(hd) == 10 and closes:
        last = closes[max(closes)]
        hi, lo = max(highs[d] for d in hd), min(lows[d] for d in hd)
        if last > 0 and hi >= lo > 0:
            out["tt"] = round((hi - lo) / last * 100, 2)
    return out


def week_key(day):
    """ISO (year, week) of a YYYY-MM-DD session — weekly bars run Mon–Sun."""
    y, w, _ = dt.date.fromisoformat(day).isocalendar()
    return y, w


def weekly_closes(closes, since=None, sessions=WEEKLY_SESSIONS):
    """Weekly closes, oldest first, from the last `sessions` daily closes on or
    after `since`: each week's last close; the running week's close is the
    latest close (TradingView's weekly bar)."""
    days = [d for d in sorted(closes) if since is None or d >= since][-sessions:]
    out, last = [], None
    for d in days:
        k = week_key(d)
        if k != last:
            out.append(closes[d])
            last = k
        else:
            out[-1] = closes[d]
    return out


def weekly_trend(wcl, period=WEEKLY_SMA):
    """Weekly-timeframe trend from weekly closes (last = this week):

      s  the 10-week SMA of weekly closes (this week included)
      d  % the close is above (+) / below (−) it
      u  1 if the SMA is rising vs last week's, else 0
      n  weeks in a row the weekly close has held above the SMA (0 = below)

    None with fewer than period + 1 weeks."""
    if len(wcl) < period + 1:
        return None
    sma = [sum(wcl[j - period + 1:j + 1]) / period for j in range(period - 1, len(wcl))]
    closes = wcl[period - 1:]                    # aligned with sma
    n = 0
    for c, m in zip(reversed(closes), reversed(sma)):
        if c > m:
            n += 1
        else:
            break
    s = sma[-1]
    return {"s": round(s, 2), "d": round((wcl[-1] / s - 1) * 100, 2) if s > 0 else None,
            "u": 1 if sma[-1] > sma[-2] else 0, "n": n}


HTF = {"minPole": 100.0, "poleSessions": 45, "maxFlag": 25.0, "flagMin": 4, "flagMax": 40,
       "boDays": 5, "boHold": 5.0, "boMax": 15.0, "dry": 0.7,
       "innerDays": 10, "innerAdr": 2.5}
HTF_SESSIONS = 100       # bars htf_state needs: breakout look-back + flag + pole


def _last_index(xs, x, i0, i1):
    """Last index of x in xs[i0:i1 + 1] — the pole starts where the run leaves
    its low, not at the first touch of a flat base."""
    for j in range(i1, i0 - 1, -1):
        if xs[j] == x:
            return j
    return i0


def _inner_range(c, h, lo, end, R):
    """The flag's last `innerDays` bars ending at `end`: (high, low) when that
    range is tight — within innerAdr × the 20-day ADR — else None."""
    s0 = end - R["innerDays"] + 1
    if s0 < 0 or c[end] <= 0:
        return None
    hi_, lo_ = max(h[s0:end + 1]), min(lo[s0:end + 1])
    ratios = [h[j] / lo[j] for j in range(max(0, end - 19), end + 1) if lo[j] > 0 and h[j] > lo[j]]
    if len(ratios) < 10:
        return None
    adr = (sum(ratios) / len(ratios) - 1) * 100
    return (hi_, lo_) if (hi_ - lo_) / c[end] * 100 <= R["innerAdr"] * adr else None


def _htf_at(c, h, lo, b, R):
    """The flag behind bar b: (pivot, pivot index, pole low index, gain %, depth %)
    with the pivot = the highest high of the flagMax + 1 bars before b, or None."""
    w0 = b - R["flagMax"] - 1
    if w0 < 0:
        return None
    seg = h[w0:b]
    P = max(seg)
    p = w0 + seg.index(P)
    ps = max(0, p - R["poleSessions"])
    pl_v = min(lo[ps:p + 1])
    pl = _last_index(lo, pl_v, ps, p)
    if pl >= p or pl_v <= 0:
        return None
    gain = (P / pl_v - 1) * 100
    depth = (1 - min(lo[p:b + 1] if b > p else [P]) / P) * 100
    return P, p, pl, gain, depth


def htf_state(c, h, lo, v, R=HTF):
    """High Tight Flag from aligned daily bars (oldest first, last = today):
    a pole of ≥ +100% in ≤ 9 weeks (45 sessions) to the pivot high, then a
    flag ≤ 25% deep for 1–8 weeks (the model book's longest flag was 43 days;
    on NSE 8 weeks tested as well as 6 and keeps the late breakouts).  Either still in the flag (today's close
    at or under the pivot) or broken out — first close above the pivot —
    within the last 5 sessions and holding (≥ 95% of the pivot, ≤ 15% above).

      p    pivot = pole high (the breakout level)
      g    pole gain %          pw  pole length, sessions
      fd   flag depth %         fw  flag length, sessions (pivot → today)
      dist today's close vs the pivot, % (negative = still below it)
      dry  flag ÷ pole average volume (< 0.7 = drying up)
      bo   sessions since the breakout, None while still in the flag
      et   early trigger: the high of a tight range late in the flag (the
           last innerDays sessions within innerAdr × ADR) — an earlier,
           lower-risk entry than the pivot (the model book's "early /
           aggressive entry")
      es   its stop: the low of that range
      eb   sessions since a close above et (still under the pivot), or None
      vx   volume on that breakout session (pivot or early) ÷ the flag's
           average volume before it — the confirmation (≥ 1.5 = strong)

    None if no setup, or a corporate-action jump lies inside it."""
    n = len(c)
    if n < 60:
        return None
    t = n - 1

    def vx_at(b):
        """Breakout-day volume ÷ the flag's average volume before it."""
        fv = [x for x in v[p + 1:b] if x is not None]
        return round(v[b] / (sum(fv) / len(fv)), 2) if v[b] is not None and fv and sum(fv) > 0 else None

    def pack(P, p, pl, gain, depth, bo, early=(None, None, None)):
        if any(c[j - 1] > 0 and abs(c[j] / c[j - 1] - 1) > CORP_ACTION_JUMP for j in range(pl + 1, n)):
            return None
        pv = [x for x in v[pl:p + 1] if x is not None]
        fv = [x for x in v[p + 1:t + 1] if x is not None]
        dry = (sum(fv) / len(fv)) / (sum(pv) / len(pv)) if pv and fv and sum(pv) > 0 else None
        return {"p": round(P, 2), "g": round(gain, 1), "pw": p - pl, "fd": round(depth, 1),
                "fw": t - p, "dist": round((c[t] / P - 1) * 100, 2),
                "dry": None if dry is None else round(dry, 2), "bo": bo,
                "et": None if early[0] is None else round(early[0], 2),
                "es": None if early[1] is None else round(early[1], 2), "eb": early[2],
                "vx": vx_at(t - bo) if bo is not None else vx_at(t - early[2]) if early[2] is not None else None}

    # broke out within the last boDays sessions (the first close above the pivot)
    for k in range(R["boDays"]):
        b = t - k
        f = _htf_at(c, h, lo, b, R)
        if not f or c[b] <= f[0]:
            continue
        P, p, pl, gain, depth = f
        if not (R["flagMin"] + 1 <= b - p <= R["flagMax"]) or gain < R["minPole"] \
                or (1 - min(lo[p:b]) / P) * 100 > R["maxFlag"]:
            continue
        if any(c[j] > P for j in range(p + 1, b)):
            continue                                   # not the first close above it
        if not (P * (1 - R["boHold"] / 100) <= c[t] <= P * (1 + R["boMax"] / 100)):
            return None                                # failed, or already extended
        return pack(P, p, pl, gain, (1 - min(lo[p:b]) / P) * 100, k)
    # still in the flag
    seg = h[t - R["flagMax"]:t + 1]
    P = max(seg)
    p = t - R["flagMax"] + seg.index(P)
    if not (R["flagMin"] <= t - p <= R["flagMax"] - 1) or c[t] > P:
        return None
    # (the same window the breakout test uses for tomorrow: it breaks out on
    # the first close above P)
    ps = max(0, p - R["poleSessions"])
    pl_v = min(lo[ps:p + 1])
    pl = _last_index(lo, pl_v, ps, p)
    if pl >= p or pl_v <= 0:
        return None
    gain = (P / pl_v - 1) * 100
    depth = (1 - min(lo[p:t + 1]) / P) * 100
    if gain < R["minPole"] or depth > R["maxFlag"]:
        return None
    # early trigger: a close above a tight range inside the flag within the
    # last boDays sessions (still under the pivot) — else the current tight
    # range's high is the trigger for the next session
    early = (None, None, None)
    for k in reversed(range(R["boDays"])):            # oldest first: the FIRST break counts
        b = t - k
        if b - R["innerDays"] <= p:
            continue                                   # the range must lie inside the flag
        rng = _inner_range(c, h, lo, b - 1, R)
        if rng and c[b] > rng[0] and c[t] >= rng[1] and all(c[j] <= rng[0] for j in range(b - R["innerDays"], b)):
            early = (rng[0], rng[1], k)
            break
    if early[0] is None and t - R["innerDays"] + 1 > p:
        rng = _inner_range(c, h, lo, t, R)
        if rng:
            early = (rng[0], rng[1], None)
    return pack(P, p, pl, gain, depth, None, early)


def htf_from_series(closes, highs, lows, volumes, since=None, vsince=None):
    """htf_state on {date: value} series: the last HTF_SESSIONS sessions on or
    after `since`; a missing high / low falls back to the close; volume before
    `vsince` (a new listing's first sessions) is left out."""
    days = [d for d in sorted(closes) if since is None or d >= since][-HTF_SESSIONS:]
    c = [closes[d] for d in days]
    return htf_state(c, [highs.get(d, closes[d]) for d in days],
                     [lows.get(d, closes[d]) for d in days],
                     [volumes.get(d) if vsince is None or d >= vsince else None for d in days])


def untraded_sessions(closes, volumes, window):
    """Sessions of `window` (market sessions) on or after the stock's first
    bar on which it didn't trade (no volume)."""
    if not closes:
        return 0
    first = min(closes)
    return sum(1 for d in window if d >= first and not (volumes or {}).get(d))


def is_illiquid(closes, volumes, window, max_turnover_cr=ILLIQUID_TURNOVER_CR):
    """Thinly traded: skipped at least one session of the RS window AND
    trades under ₹`max_turnover_cr` crore a day.  Its untraded days carry the
    last price, so its RS and returns aren't real — it's left out of the
    rankings.  (A liquid stock suspended for a day or two — a consolidation,
    an exchange hiccup — stays in.)"""
    if not untraded_sessions(closes, volumes, window):
        return False
    tv = avg_turnover_cr(closes, volumes or {}, 20)
    return tv is None or tv < max_turnover_cr


def ipo_metrics(closes, ipo, calendar, bench=None, max_age=252, raw_first=None):
    """A mainboard IPO listed in the last `max_age` market sessions:
    {"d": listing day, "p": issue price, "n": sessions since listing
    (1 = the listing day), "g": % vs the issue price, "x": % out-/under-
    performance vs NIFTY 500 since the listing-day close}.  `raw_first` =
    NSE's unadjusted listing-day close: a split / bonus since listing scales
    the issue price like the price history (CORDELIA's 10:1 split would
    otherwise read −89% vs issue).  None for older
    listings, or when the cached history starts well before the listing
    day (a renamed / relisted symbol, not this IPO)."""
    if not ipo or not closes or not calendar:
        return None
    listed, price = ipo.get("listed"), ipo.get("price")
    first = min(closes)
    if not listed or listed > calendar[-1] or first < listed:
        return None
    age = len([d for d in calendar if d >= listed])
    if age > max_age:
        return None
    # the history should start on (or within days of) the listing
    if len([d for d in calendar if listed <= d < first]) > 5:
        return None
    last = closes[max(closes)]
    if price and raw_first and closes[first]:
        price = round(price * closes[first] / raw_first, 2)
    x = None
    if bench and bench.get(first) and bench.get(max(closes)) and closes[first]:
        x = round(((last / closes[first]) / (bench[max(closes)] / bench[first]) - 1) * 100, 1)
    return {"d": listed, "p": price, "n": age,
            "g": round((last / price - 1) * 100, 1) if price else None, "x": x}
