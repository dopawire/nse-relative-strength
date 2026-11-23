"""RS maths: percentile rank, EMA flags, corporate-action breaks, ADR,
equal-weight group index vs the benchmark."""

from rs_engine.config import EMA_PERIODS, ADR_PERIOD, CORP_ACTION_JUMP


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


def period_return(closes_by_date, sessions):
    """% change over the last `sessions` sessions, close to close (21 ≈ 1
    month, 63 ≈ 3 months).  None when the history is shorter or a
    corporate-action break falls inside the period (a demerger is not a
    gain)."""
    dates = sorted(closes_by_date)
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


def setup_metrics(closes, highs, lows, volumes, since=None):
    """Breakout-readiness gauges for one stock ({date: value} each):

      vr  today's volume ÷ the 50 sessions before it   (≥ 1.5 = volume surge)
      vd  10-session average volume ÷ the 50 before it  (< 0.85 = drying up)
      tt  10-session high-low range as % of the close   (small = tight)

    Zero-volume days count (an untraded day is real information).  None
    where there isn't enough history (after `since`, a corporate-action
    break, prices before it are a different security)."""
    days = [d for d in sorted(closes) if d in volumes and (since is None or d >= since)]
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
