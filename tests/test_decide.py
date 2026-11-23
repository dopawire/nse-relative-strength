"""Focus / Swing rules (rs_engine.decide) and their track record (rs_engine.track)."""
from rs_engine import decide, track


def stock(s, sector, cap="Large", rr=90, m1=10.0, m3=20.0, w1=2.0, e=(1, 1, 1, 1, 1),
          b=1, h=3.0, a=4.0, tv=50.0, ltp=500.0, industry=None, nw=None):
    return {"s": s, "n": s, "sector": sector, "industry": industry or sector + " ind",
            "cap": cap, "rr": rr, "m1": m1, "m3": m3, "w1": w1, "e": list(e), "b": b,
            "h": h, "a": a, "tv": tv, "l": ltp, "nw": nw}


def universe():
    st = []
    for i in range(12):                             # strong sector
        st.append(stock(f"A{i}", "Alpha", m1=12 + i, m3=25))
    for i in range(5):                              # weak sector
        st.append(stock(f"Z{i}", "Zeta", cap="Small", rr=20, m1=-8, m3=-15,
                        e=(0, 0, 0, 0, 0), h=40))
    for i in range(6):                              # turning up: weak 3M, strong 1M
        st.append(stock(f"T{i}", "Tau", cap="Mid", rr=60, m1=15, m3=-5, e=(1, 1, 0, 0, 0), h=20))
    return st


def test_quadrants_focus_avoid_and_cap():
    d = decide.analyse(universe())
    q = {r["name"]: r["quad"] for r in d["sectors"]}
    assert q == {"Alpha": "Leading", "Zeta": "Lagging", "Tau": "Improving"}
    assert d["focus"][0] == "Alpha" and "Zeta" not in d["focus"]
    assert d["avoid"] == ["Zeta"]
    assert d["cap"] == "Large"
    assert all("list" not in r for r in d["sectors"])         # JSON-safe


def test_swing_lists():
    st = universe() + [
        stock("EXT", "Alpha", w1=25),                             # extended: not a breakout
        stock("THIN", "Alpha", tv=1),                             # illiquid
        stock("PB", "Alpha", e=(0, 1, 1, 1, 1), h=12, rr=85),     # pullback to below the 20-EMA
        stock("NEW", "Alpha", nw=3),                              # new listing: skipped
    ]
    d = decide.analyse(st)
    assert "EXT" not in d["breakouts"] and "EXT" in d["extended"]
    assert "THIN" not in d["breakouts"] and "NEW" not in d["breakouts"]
    assert "PB" in d["pullbacks"] and "PB" not in d["breakouts"]
    assert set(d["breakouts"]) >= {f"A{i}" for i in range(6)}


def test_regime_checklist():
    st = universe()
    on = decide.market_regime(st, {"ema": [1, 1, 1, 1, 1], "w1": 1, "m1": 2, "off_high": 1},
                              [5, 6, 7, 8, 9, 10], 100.0)
    assert on["known"] == 7 and on["level"] in ("on", "mixed")
    off = decide.market_regime(st, {"ema": [0, 0, 0, 0, 0]}, [-1, -2, -3, -4, -5, -9], -50.0)
    assert off["level"] == "off" and off["pass"] <= 2
    none = decide.market_regime(st, {}, [], None)
    assert none["known"] == 1                        # only the stock-based check


def test_crore_indian_grouping():
    assert decide.crore(111949.14) == "+₹1,11,949 cr"
    assert decide.crore(-2760.1) == "−₹2,760 cr"
    assert decide.crore(512) == "+₹512 cr"


def test_save_pick_live_beats_backfill(tmp_path):
    p = str(tmp_path / "picks.jsonl")
    base = {"date": "2026-11-20", "regime": "on", "focus": ["A"], "avoid": [], "cap": "Large",
            "breakouts": [], "pullbacks": []}
    assert track.save_pick({**base, "bt": True}, p)
    assert track.save_pick({**base, "regime": "off"}, p)                 # live replaces
    assert not track.save_pick({**base, "bt": True, "regime": "on"}, p)  # backfill can't
    assert [r["regime"] for r in track.read_picks(p)] == ["off"]


def test_evaluate_forward_returns():
    days = [f"2026-01-{d:02d}" for d in range(1, 31)]
    bench = {d: 100.0 + i for i, d in enumerate(days)}               # NIFTY +1/day
    up = {d: 100.0 * (1.02 ** i) for i, d in enumerate(days)}        # pick: +2%/day
    flat = {d: 100.0 for d in days}
    split = dict(up)
    split[days[3]] = up[days[3]] / 2                                  # corp-action jump
    cache = {"__BENCH__": bench, "UP": up, "FLAT": flat, "SPL": split}
    uni = [{"sym": "UP", "sector": "A", "cap": "Large"},
           {"sym": "FLAT", "sector": "B", "cap": "Small"},
           {"sym": "SPL", "sector": "A", "cap": "Large"}]
    picks = [{"date": days[0], "regime": "on", "focus": ["A"], "avoid": ["B"], "cap": "Large",
              "breakouts": ["UP", "SPL"], "pullbacks": []}]
    res = track.evaluate(picks, cache, uni, horizons=(5,))
    h = res["rows"][0]["h"][5]
    assert h["brk"]["n"] == 1                       # SPL skipped (jump on the way)
    assert abs(h["brk"]["ret"] - (1.02 ** 5 - 1)) < 1e-9
    assert h["focus"] > 0 and h["avoid"] > 0 and h["cap"] > 0
    assert res["summary"][5]["brk_regime"]["on"]["hit"] == 1.0
    site = track.track_for_site(res)
    assert site["n"] == 1 and site["rows"][0]["h"]["5"]["brk"]["n"] == 1


def test_setup_metrics():
    from rs_engine.maths import setup_metrics
    days = [f"2026-{m:02d}-{d:02d}" for m in (9, 10, 11) for d in range(1, 29)][:70]
    closes = {d: 100.0 for d in days}
    vols = {d: 1000 for d in days}
    for d in days[-10:]:
        vols[d] = 500                          # drying up
    vols[days[-1]] = 3000                      # surge today
    highs = {d: 101.0 for d in days}
    lows = {d: 99.0 for d in days}
    m = setup_metrics(closes, highs, lows, vols)
    assert m["tt"] == 2.0                       # (101 - 99) / 100
    assert m["vr"] > 2.5 and m["vd"] < 0.85
    assert setup_metrics({}, {}, {}, {}) == {"vr": None, "vd": None, "tt": None}


def test_setup_bonus_and_tags():
    st = universe()
    st.append(stock("TGT", "Alpha", rr=85, h=5.0, a=4.0) | {"tt": 6.0, "vd": 0.6, "vr": 0.5})
    st.append(stock("CHASE", "Alpha", rr=85, h=5.0, a=4.0) | {"tt": 20.0, "vd": 1.6, "vr": 3.0})
    d = decide.analyse(st)
    assert d["breakouts"].index("TGT") < d["breakouts"].index("CHASE")
    assert d["tags"]["TGT"] == ["tight", "dry"] and d["tags"]["CHASE"] == ["surge"]


def test_decide_from_rs_data_joins_levels_and_flows():
    def mem(s, **kw):
        base = {"s": s, "n": s, "rr": 90, "m1": 10.0, "m3": 20.0, "w1": 1.0, "e": [1, 1, 1, 1, 1],
                "b": 1, "h": 2.0, "a": 4.0, "tv": 50.0, "l": 500.0, "cap": "Large"}
        return base | kw
    ms = [mem(f"A{i}") for i in range(6)]
    data = {
        "meta": {"window_dates": ["2026-11-20", "2026-11-23"]},
        "levels": [{"key": "macro", "groups": [{"name": "M", "members": ms}]},
                   {"key": "sector", "groups": [{"name": "Alpha", "pct": 0.9, "members": ms}]},
                   {"key": "industry", "groups": [{"name": "Alpha ind", "pct": 0.8, "members": ms}]},
                   {"key": "basic", "groups": [{"name": "B", "members": ms}]}],
        "breadth": {"osc": [1, 2, 3, 4, 5, 6], "market": {"ema": [1, 1, 1, 1, 1]}},
        "flows": {"months": [{"m": "2026-10", "fii": -5.0}, {"m": "2026-11", "fii": 7.0}]},
    }
    d = decide.decide_from_rs_data(data)
    assert d["asof"] == "2026-11-23"
    assert d["sectors"][0]["name"] == "Alpha" and d["sectors"][0]["pct"] == 90.0
    fii = [c for c in d["regime"]["checks"] if c["t"].startswith("FIIs")][0]
    assert fii["ok"] is True
    data["flows"]["months"].pop()                 # only last month's flow → not this month's
    fii = [c for c in decide.decide_from_rs_data(data)["regime"]["checks"] if c["t"].startswith("FIIs")][0]
    assert fii["ok"] is None
