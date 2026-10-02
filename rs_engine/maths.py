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
