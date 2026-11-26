"""Core per-stock metrics (rs_engine.maths) with hand-checked numbers, and
parity between the backfill's incremental versions and the live functions."""
import datetime as dt
import math
import random

import pytest

from rs_engine import maths


def days(n, start=dt.date(2025, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def test_percentrank_inc_matches_excel():
    a = [1, 2, 3, 4, 5]
    assert maths.percentrank_inc(a, 5) == 1.0 and maths.percentrank_inc(a, 1) == 0.0
    assert maths.percentrank_inc(a, 3) == 0.5
    assert maths.percentrank_inc(a, 3.5) == pytest.approx(0.625)     # Excel: 0.625
    assert maths.percentrank_inc([7, 7, 7], 7) == 1.0                 # flat series
    assert maths.percentrank_inc([1], 1) == 0.0


def test_pct_off_high_uses_intraday_high_and_break():
    ds = days(300)
    highs = {d: 100.0 for d in ds}
    highs[ds[10]] = 500.0                      # older than 252 sessions: ignored
    highs[ds[-100]] = 125.0
    assert maths.pct_off_high(highs, 100.0) == pytest.approx(20.0)
    assert maths.pct_off_high(highs, 100.0, since=ds[-50]) == pytest.approx(0.0)
    assert maths.pct_off_high({}, 100.0) is None and maths.pct_off_high(highs, None) is None


def test_adr_skips_zero_range_bars():
    ds = days(40)
    hi = {d: 105.0 for d in ds}
    lo = {d: 100.0 for d in ds}
    for d in ds[-5:]:
        hi[d] = lo[d] = 100.0                  # phantom flat bars: skipped
    assert maths.adr_pct(hi, lo) == pytest.approx(5.0)
    assert maths.adr_pct({ds[0]: 2.0}, {ds[0]: 1.0}) is None


def test_avg_turnover_crore():
    ds = days(30)
    closes = {d: 200.0 for d in ds}
    vols = {d: 1_000_000 for d in ds}          # 200 × 10 lakh = ₹20 crore
    assert maths.avg_turnover_cr(closes, vols) == pytest.approx(20.0)
    assert maths.avg_turnover_cr(closes, {ds[-1]: 5}) is None   # < half the sessions


def test_period_return_and_break():
    ds = days(30)
    c = {d: 100.0 + i for i, d in enumerate(ds)}
    assert maths.period_return(c, 5) == pytest.approx((129 / 124 - 1) * 100)
    c[ds[-3]] = c[ds[-4]] * 0.4                # 60% gap inside the period
    assert maths.period_return(c, 5) is None
    assert maths.period_return(c, 40) is None


def test_ema_flags_against_textbook_ema():
    ds = days(260)
    rnd = random.Random(3)
    v, closes = 100.0, {}
    for d in ds:
        v *= 1 + rnd.uniform(-0.02, 0.021)
        closes[d] = v
    flags, price = maths.ema_flags(closes)
    vals = [closes[d] for d in ds]
    for p, f in zip((20, 50, 100, 150, 200), flags):
        e = sum(vals[:p]) / p
        for x in vals[p:]:
            e = x * 2 / (p + 1) + e * (1 - 2 / (p + 1))
        assert f == (1 if price >= e else 0)
    assert maths.ema_flags({ds[0]: 1.0})[0] == [-1] * 5


def test_rs_ratings_order_and_weights():
    ds = days(300)
    ser = {"UP": {d: 100 * 1.002 ** i for i, d in enumerate(ds)},
           "FLAT": {d: 100.0 for d in ds},
           "DOWN": {d: 100 * 0.999 ** i for i, d in enumerate(ds)},
           "SHORT": {d: 100.0 for d in ds[-30:]}}           # < 64 sessions: unrated
    r = maths.rs_ratings(ser, ds[-1])
    assert set(r) == {"UP", "FLAT", "DOWN"}
    assert r["UP"] == 99 and r["DOWN"] == 33 and r["FLAT"] == 67


def test_index_trend_off_high():
    ds = days(300)
    c = {d: 100.0 + i for i, d in enumerate(ds)}
    c[ds[-1]] = c[ds[-2]] * 0.9
    t = maths.index_trend(c)
    assert t["off_high"] == pytest.approx(10.0, abs=0.01)
    assert t["w1"] == pytest.approx((c[ds[-1]] / c[ds[-6]] - 1) * 100, abs=0.01)


def test_backfill_record_matches_live_functions():
    """backfill_picks.Stock recomputes metrics incrementally; on the same data
    it must agree with the functions the live build uses."""
    import backfill_picks as bp
    ds = days(320)
    rnd = random.Random(7)
    v, c, h, lo, vol, bench = 100.0, {}, {}, {}, {}, {}
    for i, d in enumerate(ds):
        v *= 1 + rnd.uniform(-0.03, 0.032)
        c[d], h[d], lo[d] = v, v * 1.02, v * 0.98
        vol[d] = rnd.randint(50_000, 150_000)
        bench[d] = 1000 * (1.0005 ** i)
    u = {"sym": "X", "name": "X", "sector": "S", "industry": "I"}
    st = bp.Stock(u, c, h, lo, vol, bench)
    for k in (len(ds) - 1, len(ds) - 40):
        day = ds[k]
        cut = {d: x for d, x in c.items() if d <= day}
        hc = {d: x for d, x in h.items() if d <= day}
        lc = {d: x for d, x in lo.items() if d <= day}
        vc = {d: x for d, x in vol.items() if d <= day}
        bc = {d: x for d, x in bench.items() if d <= day}
        r = st.record(day, ds[k - 25], "Large", ds, k)
        cal = ds[:k + 1]
        flags, price = maths.ema_flags(cut)
        assert r["e"] == flags and r["l"] == price
        assert r["b"] == maths.rs_ema_flag(cut, bc)
        assert r["h"] == pytest.approx(maths.pct_off_high(hc, price, since=cal[-252]))
        assert r["a"] == pytest.approx(maths.adr_pct(hc, lc))
        assert r["tv"] == pytest.approx(maths.avg_turnover_cr(cut, vc))
        for key, n in (("m1", 20), ("m3", 63), ("w1", 5)):
            assert r[key] == pytest.approx(maths.period_return(cut, n, cal))
            assert r[key] == pytest.approx(maths.period_return(cut, n))     # no gaps: same
        sm = maths.setup_metrics(cut, hc, lc, vc)
        for key in ("vr", "vd", "tt"):
            assert r[key] == pytest.approx(sm[key])
        assert r["wk"] == maths.weekly_trend(maths.weekly_closes(cut))
        assert not math.isnan(st.rr_score(r["_i"]))


def test_weekly_trend_tradingview_style():
    """Weekly bars Mon–Sun, the running week's close = the latest close;
    SMA10 of weekly closes, rising flag, weeks in a row above it."""
    import datetime as dt
    start = dt.date(2026, 6, 1)                       # a Monday
    c = {}
    for w in range(14):                               # 14 weeks, Mon–Fri
        for k in range(5):
            c[(start + dt.timedelta(weeks=w, days=k)).isoformat()] = 100.0 + w * 10 + k
    c["2026-09-07"] = 300.0                           # Mon of week 15: running week
    wcl = maths.weekly_closes(c)
    assert wcl == [104.0 + w * 10 for w in range(14)] + [300.0]
    t = maths.weekly_trend(wcl)
    sma = sum(wcl[-10:]) / 10
    assert t["s"] == round(sma, 2) and t["d"] == round((300 / sma - 1) * 100, 2)
    assert t["u"] == 1 and t["n"] == 6                # weeks 10–15 (all with an SMA) above
    down = maths.weekly_trend(wcl[:-1] + [100.0])      # this week closes under the line
    assert down["n"] == 0 and down["d"] < 0
    assert maths.weekly_trend(wcl[:10]) is None       # needs 11 weeks
    # after a corporate-action break only post-break closes count
    assert maths.weekly_closes(c, since="2026-08-31") == [234.0, 300.0]


def test_backfill_weekly_trend_after_a_split():
    """A 1:2 split inside the window: live restarts at the break, the
    backfill must too."""
    import backfill_picks as bp
    ds = days(320)
    c = {d: 100.0 + i * 0.2 for i, d in enumerate(ds)}
    for d in ds[-90:]:
        c[d] /= 2
    h = {d: v * 1.01 for d, v in c.items()}
    lo = {d: v * 0.99 for d, v in c.items()}
    vol = {d: 100_000 for d in ds}
    bench = {d: 1000.0 for d in ds}
    st = bp.Stock({"sym": "X", "name": "X", "sector": "S", "industry": "I"}, c, h, lo, vol, bench)
    k = len(ds) - 1
    r = st.record(ds[k], ds[k - 25], "Large", ds, k)
    brk = maths.last_break_date(c, 252)
    assert brk == ds[-90]
    assert r["wk"] == maths.weekly_trend(maths.weekly_closes(c, since=brk))
    assert r["wk"]["n"] >= 10                          # steady uptrend after the split


def test_period_return_counts_market_sessions():
    """A stock that skipped sessions is measured from its close on or before
    the start session — not over a longer stretch of its own bars."""
    cal = days(30)
    c = {d: 100.0 + i for i, d in enumerate(cal)}
    for d in cal[-4:-2]:
        del c[d]                               # no trades on 2 sessions inside the week
    by_cal = maths.period_return(c, 5, cal)
    assert by_cal == pytest.approx((c[cal[-1]] / c[cal[-6]] - 1) * 100)   # 5 SESSIONS back
    del c[cal[-6]]                             # start session untraded: the close before it
    assert maths.period_return(c, 5, cal) == pytest.approx((c[cal[-1]] / c[cal[-7]] - 1) * 100)
    assert maths.period_return(c, 5) != pytest.approx(by_cal)     # bar counting reaches further back
    assert maths.period_return(c, 40, cal) is None


def test_is_illiquid_needs_a_skipped_session_and_low_turnover():
    cal = days(40)
    c = {d: 100.0 for d in cal}
    thin = {d: 1_000 for d in cal}                  # ₹1 lakh/day
    assert not maths.is_illiquid(c, thin, cal[-26:])     # trades every day: stays in
    thin[cal[-3]] = 0                               # one untraded session
    assert maths.untraded_sessions(c, thin, cal[-26:]) == 1
    assert maths.is_illiquid(c, thin, cal[-26:])
    big = {d: 1_000_000 for d in cal}               # ₹10 cr/day, suspended one day
    del big[cal[-3]]
    assert not maths.is_illiquid(c, big, cal[-26:])
    # days before the listing don't count as untraded
    young = {d: 100.0 for d in cal[-12:]}
    assert maths.untraded_sessions(young, {d: 5 for d in young}, cal[-26:]) == 0


def test_ipo_metrics():
    cal = days(300)
    c = {d: 100.0 * (1.01 ** i) for i, d in enumerate(cal[-30:])}
    bench = {d: 1000.0 for d in cal}
    m = maths.ipo_metrics(c, {"listed": cal[-30], "price": 80.0}, cal, bench)
    assert m["d"] == cal[-30] and m["n"] == 30 and m["p"] == 80.0
    assert m["g"] == pytest.approx((c[cal[-1]] / 80 - 1) * 100, abs=0.05)
    assert m["x"] == pytest.approx((1.01 ** 29 - 1) * 100, abs=0.05)   # NIFTY flat
    assert maths.ipo_metrics(c, {"listed": cal[-260], "price": 80.0}, cal) is None   # > 1 year
    old = {d: 1.0 for d in cal}                     # history long before the listing day
    assert maths.ipo_metrics(old, {"listed": cal[-30], "price": 80.0}, cal) is None
    late = {d: v for d, v in c.items() if d >= cal[-20]}   # history starts 10 sessions late
    assert maths.ipo_metrics(late, {"listed": cal[-30], "price": 80.0}, cal) is None


def test_backfill_record_ipo_and_illiquid():
    import backfill_picks as bp
    ds = days(320)
    c = {d: 100.0 + i * 0.1 for i, d in enumerate(ds[-40:])}
    hl = {d: v * 1.01 for d, v in c.items()}
    ll = {d: v * 0.99 for d, v in c.items()}
    vol = {d: 200_000 for d in c}
    bench = {d: 1000.0 for d in ds}
    u = {"sym": "NEWCO", "name": "N", "sector": "S", "industry": "I"}
    ipo = {"listed": ds[-40], "price": 90.0}
    k = len(ds) - 1
    r = bp.Stock(u, c, hl, ll, vol, bench, ipo).record(ds[k], ds[k - 25], "New", ds, k)
    assert r["ipo"] == maths.ipo_metrics(c, ipo, ds, bench)
    thin = {d: 100 for d in c}
    thin[ds[-5]] = 0
    assert bp.Stock(u, c, hl, ll, thin, bench).record(ds[k], ds[k - 25], "New", ds, k) is None


def test_ipo_metrics_adjusts_issue_price_for_a_split():
    """CORDELIA: issue ₹808, listed at 668.1, 10:1 split later — the cache is
    adjusted (listing close 66.81), so the issue price must be too."""
    cal = days(40)
    c = {d: 66.81 for d in cal[-30:]}
    c[cal[-1]] = 84.56
    m = maths.ipo_metrics(c, {"listed": cal[-30], "price": 808.0}, cal, raw_first=668.1)
    assert m["p"] == pytest.approx(80.8)
    assert m["g"] == pytest.approx((84.56 / 80.8 - 1) * 100, abs=0.05)      # +4.7%, not −89.5%
    no_ca = maths.ipo_metrics(c, {"listed": cal[-30], "price": 808.0}, cal, raw_first=66.81)
    assert no_ca["p"] == 808.0


def _htf_bars(pole=110.0, flag_depth=12.0, flag_len=10, flag_vol=40_000, extra=()):
    """40 flat bars at 100, a pole to 100·(1+pole%) over 30 bars, then a flag."""
    c, v = [100.0] * 40, [100_000] * 40
    top = 100 * (1 + pole / 100)
    for k in range(1, 31):
        c.append(100 + (top - 100) * k / 30)
        v.append(150_000)
    for k in range(flag_len):
        c.append(top * (1 - flag_depth / 100 * (0.5 + 0.5 * (k % 2))))
        v.append(flag_vol)
    c += list(extra)
    v += [200_000] * len(extra)
    h = [x * 1.0 for x in c]
    lo = [x * 1.0 for x in c]
    return c, h, lo, v


def test_htf_in_flag_then_breakout():
    c, h, lo, v = _htf_bars()
    r = maths.htf_state(c, h, lo, v)
    top = 210.0
    assert r["bo"] is None and r["p"] == top and r["g"] == pytest.approx(110.0)
    assert r["fd"] == pytest.approx(12.0) and r["fw"] == 10 and r["pw"] == 30
    assert r["dist"] == pytest.approx((c[-1] / top - 1) * 100, abs=0.01) and r["dist"] < 0
    assert r["dry"] == pytest.approx(40_000 / 150_000, abs=0.01)
    b = maths.htf_state(*_htf_bars(extra=(215.0,)))       # first close above the pivot
    assert b["bo"] == 0 and b["p"] == top and b["dist"] == pytest.approx((215 / top - 1) * 100, abs=0.01)
    b3 = maths.htf_state(*_htf_bars(extra=(215.0, 214.0, 216.0)))
    assert b3["bo"] == 2                                   # still listed 2 sessions later
    assert maths.htf_state(*_htf_bars(extra=(215.0, 190.0))) is None   # failed back under
    assert maths.htf_state(*_htf_bars(extra=(250.0,))) is None         # > 15% above: extended


def test_htf_rejects_weak_poles_deep_flags_and_splits():
    assert maths.htf_state(*_htf_bars(pole=80)) is None    # pole under +100%
    assert maths.htf_state(*_htf_bars(flag_depth=30)) is None
    assert maths.htf_state(*_htf_bars(flag_len=2)) is None # no flag yet
    assert maths.htf_state(*_htf_bars(flag_len=35))["fw"] == 35   # 7 weeks: still a flag
    assert maths.htf_state(*_htf_bars(flag_len=45)) is None        # over 8 weeks
    c, h, lo, v = _htf_bars()
    for k in range(50, 60):                                # a 2:1 split inside the pole
        c[k], h[k], lo[k] = c[k] * 2, h[k] * 2, lo[k] * 2
    assert maths.htf_state(c, h, lo, v) is None


def test_backfill_htf_matches_live():
    import backfill_picks as bp
    c0, h0, l0, v0 = _htf_bars(extra=(215.0, 214.0))
    ds = days(320)[-len(c0):]
    c = dict(zip(ds, c0))
    h, lo, vol = dict(zip(ds, h0)), dict(zip(ds, l0)), dict(zip(ds, v0))
    bench = {d: 1000.0 for d in ds}
    st = bp.Stock({"sym": "X", "name": "X", "sector": "S", "industry": "I"}, c, h, lo, vol, bench)
    for k in (len(ds) - 1, len(ds) - 3):
        cut = {d: x for d, x in c.items() if d <= ds[k]}
        r = st.record(ds[k], ds[k - 25], "Large")
        assert r["htf"] == maths.htf_from_series(cut, h, lo, vol)
    assert r["htf"]["bo"] is None and st.record(ds[-1], ds[-26], "Large")["htf"]["bo"] == 1


def _early_bars(extra=()):
    """Flat 100 → pole to 210 → a dip to ~185, then 12 tight sessions at
    189–191 (high/low ±2%: ADR ≈ 4%) — a tight range inside the flag."""
    c = [100.0] * 40 + [100 + 110 * k / 30 for k in range(1, 31)]
    c += [205.0, 198.0, 192.0, 186.0, 185.0, 188.0, 187.0, 189.0]
    c += [190.0, 189.0, 191.0, 190.0, 189.5, 190.5, 191.0, 189.0, 190.0, 190.5, 189.5, 190.0]
    v = [100_000] * 40 + [150_000] * 30 + [50_000] * 20
    c += list(extra)
    v += [120_000] * len(extra)
    return c, [x * 1.02 for x in c], [x * 0.98 for x in c], v


def test_htf_early_trigger_set_then_hit():
    r = maths.htf_state(*_early_bars())
    assert r["bo"] is None and r["eb"] is None
    assert r["et"] == pytest.approx(191.0 * 1.02) and r["es"] == pytest.approx(189.0 * 0.98)
    hit = maths.htf_state(*_early_bars(extra=(200.0,)))      # over the range, under the 214 pivot
    assert hit["bo"] is None and hit["eb"] == 0 and hit["et"] == pytest.approx(191.0 * 1.02)
    assert hit["vx"] == pytest.approx(120_000 / 50_000)      # vs the flag's average volume
    later = maths.htf_state(*_early_bars(extra=(200.0, 203.0)))
    assert later["eb"] == 1 and later["et"] == r["et"]       # the FIRST break is kept
    failed = maths.htf_state(*_early_bars(extra=(200.0, 180.0)))
    assert failed["eb"] is None                              # fell back under the range low
    piv = maths.htf_state(*_early_bars(extra=(200.0, 220.0)))
    assert piv["bo"] == 0 and piv["vx"] is not None
    assert piv["et"] == r["et"] and piv["eb"] == 1          # the early entry stays on the row
    plain = maths.htf_state(*_early_bars(extra=(220.0,)))   # straight through the pivot
    assert plain["bo"] == 0 and plain["eb"] is None


def test_listing_volume_left_out():
    cal = days(80)
    c = {d: 100.0 for d in cal[20:]}                         # listed 20 sessions after the history starts
    vol = {d: (90_000_000 if i < 10 else 500_000) for i, d in enumerate(cal[20:])}
    vs = maths.listing_vsince(c, cal[0])
    assert vs == cal[30] and maths.listing_vsince({d: 1.0 for d in cal}, cal[0]) is None
    hl = {d: 101.0 for d in c}
    ll = {d: 99.0 for d in c}
    with_frenzy = maths.setup_metrics(c, hl, ll, vol)
    without = maths.setup_metrics(c, hl, ll, vol, vsince=vs)
    assert with_frenzy["vr"] < 0.5 and without["vr"] == pytest.approx(1.0)   # one 90M day in the 50


def test_backfill_new_listing_matches_live():
    import backfill_picks as bp
    cal = days(200)
    c0, h0, l0, v0 = _early_bars(extra=(200.0,))
    ds = cal[-len(c0):]
    c, h, lo = dict(zip(ds, c0)), dict(zip(ds, h0)), dict(zip(ds, l0))
    vol = dict(zip(ds, v0))
    vol[ds[0]] = 50_000_000                                  # listing-day frenzy
    bench = {d: 1000.0 for d in cal}
    st = bp.Stock({"sym": "N", "name": "N", "sector": "S", "industry": "I"}, c, h, lo, vol, bench)
    k = len(cal) - 1
    r = st.record(cal[k], cal[k - 25], "Small", cal, k)
    vs = maths.listing_vsince(c, cal[0])
    assert vs == ds[10]
    assert r["htf"] == maths.htf_from_series(c, h, lo, vol, vsince=vs) and r["htf"]["eb"] == 0
    sm = maths.setup_metrics(c, h, lo, vol, vsince=vs)
    assert r["vr"] == pytest.approx(sm["vr"]) and r["vd"] == pytest.approx(sm["vd"])
