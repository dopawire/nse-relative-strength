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
        assert not math.isnan(st.rr_score(r["_i"]))


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
