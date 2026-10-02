"""Tests for Phase-4 engine: rotation RS-lines, breadth divergence, IPO watch,
ranking snapshots + deltas, daily report."""
import datetime as dt


import build_rs
from build_rs import (
    compute_rotation, detect_breadth_divergence, build_ipo_watch,
    load_previous_snapshot, append_snapshot, write_daily_report,
)


def _bench_and_stocks(n_days=60, start="2026-01-01"):
    base = dt.date.fromisoformat(start)
    dates = [(base + dt.timedelta(days=i)).isoformat() for i in range(n_days)]
    bench = {d: 100.0 + i for i, d in enumerate(dates)}          # +1/day
    winners = {f"W{i}": {d: 100.0 + 2 * i for i, d in enumerate(dates)}
               for i in range(8)}                                # +2/day
    losers = {f"L{i}": {d: 100.0 + 0.5 * i for i, d in enumerate(dates)}
              for i in range(8)}                                 # +0.5/day
    cache = {"__BENCH__": bench, **winners, **losers}
    universe = ([{"sym": s, "sector": "Winners", "name": s} for s in winners]
                + [{"sym": s, "sector": "Losers", "name": s} for s in losers])
    return universe, cache, bench, dates


def test_rotation_lines_separate_strong_and_weak():
    universe, cache, bench, dates = _bench_and_stocks()
    rot = compute_rotation(universe, cache, bench, dates, level="sector")
    assert rot["dates"] == dates
    names = [g["name"] for g in rot["groups"]]
    assert names == sorted(names)
    by = {g["name"]: g["rs"] for g in rot["groups"]}
    assert by["Winners"][-1] > 1.05      # outperforming the bench
    assert by["Losers"][-1] < 0.95       # underperforming
    assert all(g["rs"][0] == 1.0 for g in rot["groups"])   # rebased at start


def test_divergence_bearish():
    # index at 26-day highs, breadth lower than at the previous peak
    dates = [f"2026-06-{d:02d}" for d in range(1, 28)]
    bench = {d: 19800.0 for d in dates}       # mid-range by default
    bench["2026-06-10"] = 20050.0             # earlier peak
    bench["2026-06-27"] = 20100.0             # new high at the end
    osc = [5.0] * len(dates)
    osc[dates.index("2026-06-10")] = 25.0     # breadth was higher at that peak
    div = detect_breadth_divergence(bench, dates, osc)
    assert div["state"] == "bearish"


def test_divergence_bullish():
    dates = [f"2026-06-{d:02d}" for d in range(1, 28)]
    bench = {d: 20200.0 for d in dates}
    bench["2026-06-10"] = 19950.0             # earlier trough
    bench["2026-06-27"] = 19900.0             # new low at the end
    osc = [-5.0] * len(dates)
    osc[dates.index("2026-06-10")] = -30.0    # breadth was lower at that trough
    div = detect_breadth_divergence(bench, dates, osc)
    assert div["state"] == "bullish"


def test_divergence_none_on_normal_day():
    dates = [f"2026-06-{d:02d}" for d in range(1, 28)]
    bench = {d: 20000.0 + i * 100 for i, d in enumerate(dates)}   # steady trend
    osc = [0.0] * len(dates)
    assert detect_breadth_divergence(bench, dates, osc)["state"] == "none"


def test_ipo_watch_lists_only_unrankable_excluded():
    cache = {
        "NEW1": {"2026-09-20": 100.0, "2026-09-21": 101.0, "2026-09-22": 102.0},
        "OLD1": {f"2026-0{i % 9 + 1}-{i % 28 + 1:02d}": 10.0 + i for i in range(50)},
        "IN1": {"2026-09-20": 50.0},
    }
    universe = [
        {"sym": "NEW1", "name": "New One"},
        {"sym": "OLD1", "name": "Old One"},
        {"sym": "IN1", "name": "In View"},
    ]
    ipo = build_ipo_watch(universe, cache, excluded={"NEW1", "OLD1"})
    assert [i["s"] for i in ipo] == ["NEW1"]       # OLD1 has >= WINDOW days, IN1 not excluded
    assert ipo[0]["days"] == 3
    assert ipo[0]["eta"] == build_rs.WINDOW - 3
    assert ipo[0]["ltp"] == 102.0
    assert "rs" not in ipo[0]                       # no bench given → no chart data


def test_ipo_watch_embeds_rs_line_when_bench_given():
    """New-listing charts must work even without the /api/stock endpoint
    (static site) — the RS line + EMA21 are embedded in the meta.ipo data."""
    cache = {
        "NEW1": {"2026-09-20": 100.0, "2026-09-21": 101.0, "2026-09-22": 102.0},
    }
    bench = {"2026-09-20": 500.0, "2026-09-21": 501.0, "2026-09-22": 502.0}
    universe = [{"sym": "NEW1", "name": "New One"}]
    ipo = build_ipo_watch(universe, cache, excluded={"NEW1"}, bench=bench)
    e = ipo[0]
    assert e["dates"] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    assert e["rs"] == [0.2, 0.2016, 0.20319]
    assert e["ema21"] == [0.2, 0.20015, 0.20042]


def test_snapshot_roundtrip_and_idempotency(tmp_path, monkeypatch):
    import rs_engine.snapshot
    monkeypatch.setattr(rs_engine.snapshot, "SNAPSHOTS",
                        str(tmp_path / "snaps.jsonl"))
    levels = [("macro", "Macro", [
        {"name": "Tech", "pct": 0.8, "members": [{"sym": "AAA", "pct": 0.9}]},
    ])]
    assert load_previous_snapshot() is None
    snap = append_snapshot(levels, "2026-10-01")
    assert snap["end"] == "2026-10-01"
    prev = load_previous_snapshot()
    assert prev["g"]["macro"]["Tech"] == 0.8 and prev["m"]["AAA"] == 0.9
    # same window end → no new line
    append_snapshot(levels, "2026-10-01")
    with open(tmp_path / "snaps.jsonl") as f:
        assert len([ln for ln in f if ln.strip()]) == 1


def test_daily_report_written(tmp_path):
    meta = {"drange": "2026-09-01 → 2026-10-01", "gen": "2026-10-01 18:00",
            "n_window": 100, "n_stocks": 110, "src": {}}
    breadth = {"osc": [-12.0], "divergence": {"state": "none"}}
    levels = [("sector", "Sector", [{"name": "IT", "pct": 0.9, "n": 50,
                                     "members": []}])]
    out = tmp_path / "report.html"
    write_daily_report(str(out), meta, breadth, levels, [])
    html = out.read_text()
    assert "daily digest" in html and "IT" in html
    assert "-12.0" in html and "Market breadth" in html
