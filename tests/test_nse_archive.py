"""NSE daily archive: parsing, aligning Yahoo's partial adjustments, filling
missing history, delivery metrics (rs_engine.nse_archive)."""
import pytest

from rs_engine import nse_archive as A

CSV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
20MICRONS, EQ, 23-Nov-2026, 179.49, 180.01, 183.67, 178.02, 182.50, 180.44, 181.58, 39466, 71.66, 2063, 21631, 54.81
21STCENMGM, BE, 23-Nov-2026, 46.09, 44.10, 46.50, 44.10, 46.50, 46.46, 45.39, 6150, 2.79, 78, -, -
GOLDBEES, ETF, 23-Nov-2026, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
"""

DAYS = ["2026-01-%02d" % d for d in (1, 2, 5, 6, 7, 8, 9)]


def test_parse():
    p = A.parse(CSV)
    assert p == {"20MICRONS": [180.44, 183.67, 178.02, 39466.0, 54.81],
                 "21STCENMGM": [46.46, 46.5, 44.1, 6150.0, None]}     # BE: no delivery; ETF skipped


def arc_from(closes):
    return {"X": {d: [c, c * 1.01, c * 0.99, 1000.0, 50.0] for d, c in closes.items()}}


DAYS10 = ["2026-01-%02d" % d for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14)]


def run(ours, raw, older=None):
    cache = {"X": dict(ours)}
    if older:
        cache["X"].update(older)
    highs, lows = {"X": dict(cache["X"])}, {"X": dict(cache["X"])}
    vol = {"X": {d: 1000.0 for d in cache["X"]}}
    out = A.rebase(cache, highs, lows, arc_from(raw), ["X"], vol)
    return cache["X"], highs["X"], vol["X"], out


def rets(s, days):
    return [s[d] / s[p] for p, d in zip(days, days[1:])]


def test_rebase_fixes_partial_adjustment_keeps_real_bonus():
    raw = dict(zip(DAYS10, [100, 101, 102, 103, 104, 52, 53, 54, 55, 56]))   # 1:1 bonus on day 6
    # Yahoo adjusted (÷2) back to day 3 only: fake −50% on day 3
    ours = {d: (v if i < 2 else (v / 2 if i < 5 else v)) for i, (d, v) in enumerate(raw.items())}
    s, h, vol, out = run(ours, raw)
    assert out["ca"] == {"X": {DAYS10[5]: 0.5}}
    r, rr = rets(s, DAYS10), rets(raw, DAYS10)
    for i, (x, y) in enumerate(zip(r, rr)):
        if i == 4:
            assert x == pytest.approx(52 / 52)               # adjusted: no fake bonus drop
        else:
            assert x == pytest.approx(y)                      # NSE's own returns
    assert s[DAYS10[0]] == pytest.approx(50.0) and h[DAYS10[0]] == pytest.approx(50.5)
    assert vol[DAYS10[0]] == pytest.approx(2000.0)


def test_rebase_replaces_stale_bar_and_fills_missing_days():
    raw = dict(zip(DAYS10, [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]))
    ours = {d: v for d, v in raw.items() if d >= DAYS10[2]}  # Yahoo starts on day 3
    ours[DAYS10[6]] = ours[DAYS10[5]]                         # stale copy of the day before
    s, _, _, out = run(ours, raw)
    assert out["ca"] == {} and out["added"] == {"X": 2}
    assert [s[d] for d in DAYS10] == pytest.approx(list(raw.values()))


def test_rebase_joins_older_yahoo_history_and_is_idempotent():
    raw = dict(zip(DAYS10[3:], [103, 104, 105, 106, 107, 108, 109]))
    ours = {d: v * 0.5 for d, v in raw.items()}               # Yahoo scale ×0.5 (later split)
    older = {DAYS10[0]: 50.0, DAYS10[1]: 50.5}                # pre-archive Yahoo history
    s, _, _, _ = run(ours, raw, older)
    # the whole series keeps Yahoo's scale; archived days follow NSE exactly
    assert s[DAYS10[3]] == pytest.approx(51.5) and s[DAYS10[0]] == pytest.approx(50.0)
    cache = {"X": dict(s)}
    again = A.rebase(cache, {}, {}, arc_from(raw), ["X"])
    assert again["changed"] == {} and cache["X"] == pytest.approx(s)


def test_rebase_ignores_one_day_blip_as_corporate_action():
    raw = dict(zip(DAYS10, [100, 100, 100, 100, 70, 100, 100, 100, 100, 100]))  # real −30% day
    ours = dict(raw)
    ours[DAYS10[4]] = 100.0                                   # Yahoo missed the crash day
    s, _, _, out = run(ours, raw)
    assert out["ca"] == {} and s[DAYS10[4]] == pytest.approx(70.0)


def test_delivery_metrics():
    rows = {d: [1, 1, 1, 1, 40.0 + i] for i, d in enumerate(DAYS)}
    rows.update({"2025-12-%02d" % d: [1, 1, 1, 1, 40.0] for d in range(1, 10)})
    m = A.delivery_metrics(rows, DAYS[-1])
    assert m["dl"] == 46.0 and m["dla"] == pytest.approx(sum([40.0] * 9 + [40 + i for i in range(7)]) / 16, abs=0.05)
    assert A.delivery_metrics(rows, "2026-02-01") == {"dl": None, "dla": None}
    assert A.delivery_metrics(None, DAYS[-1]) == {"dl": None, "dla": None}


def test_update_trims_and_skips_failures(monkeypatch):
    calls = []

    def fake(session, day):
        calls.append(day)
        return None if day == DAYS[1] else {"X": [1.0, 1.0, 1.0, 1.0, 50.0]}
    monkeypatch.setattr(A, "fetch_day", fake)
    monkeypatch.setattr(A, "KEEP_SESSIONS", 3)
    arc = {}
    added = A.update(arc, DAYS[:4], None)
    assert added == [DAYS[0], DAYS[2], DAYS[3]]
    assert arc["__DAYS__"] == [DAYS[0], DAYS[2], DAYS[3]]
    A.update(arc, DAYS[:5], None)                  # DAYS[1] retried, then trimmed to 3
    assert arc["__DAYS__"] == DAYS[2:5] and min(arc["X"]) == DAYS[2]


def test_rebase_stable_when_corporate_action_is_recent():
    """Regression: a split / dividend adjustment in the last few sessions must
    not rescale the series on every run (SMLMAH, ex-date 20-Nov-2026)."""
    raw = dict(zip(DAYS10, [100, 101, 102, 103, 104, 105, 106, 107, 90, 91]))   # ex-date on day 9
    ours = {d: (v * 0.85 if i < 8 else v) for i, (d, v) in enumerate(raw.items())}
    cache, hi, lo = {"X": dict(ours)}, {}, {}
    first = A.rebase(cache, hi, lo, arc_from(raw), ["X"])
    assert first["ca"] == {"X": {DAYS10[8]: 0.85}}
    assert cache["X"] == pytest.approx(ours)                  # already right: unchanged
    for _ in range(3):
        again = A.rebase(cache, hi, lo, arc_from(raw), ["X"])
        assert again["changed"] == {}
    assert cache["X"][DAYS10[-1]] == pytest.approx(91.0)


def test_rebase_carries_nse_close_on_untraded_days():
    """A session the stock didn't trade keeps a carried bar (so the stock stays
    in the window), but at NSE's last close — not Yahoo's stale value."""
    raw = dict(zip(DAYS10, [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]))
    del raw[DAYS10[5]]                                       # no trade on day 6
    ours = dict(zip(DAYS10, [100, 101, 102, 103, 104, 150, 106, 107, 108, 109]))  # stale carry
    s, h, vol, _ = run(ours, raw)
    assert s[DAYS10[5]] == pytest.approx(104.0) and h[DAYS10[5]] == pytest.approx(104.0)
    assert vol[DAYS10[5]] == 0
