"""Evening brief (send_brief.py) and watchlist alerts (watchlist.py)."""
import send_brief
import watchlist


def data(e20=1, h=3.0, ev=None):
    m = {"s": "AAA", "n": "Aaa Ltd", "rr": 95, "h": h, "e": [e20, 1, 1, 1, 1], "d1": 1.2,
         "wk": {"s": 90.0, "d": 4.2, "u": 1, "n": 7},
         "htf": {"p": 100.0, "g": 140.0, "pw": 30, "fd": 14.0, "fw": 12, "dist": -2.5, "dry": 0.5, "bo": None,
                 "et": 98.0, "es": 92.0, "eb": 0, "ebd": "2026-11-23", "bod": None}}
    if ev:
        m["ev"] = ev
    return {
        "levels": [{"key": "macro", "groups": [{"name": "X", "members": [m]}]}],
        "decide": {"asof": "2026-11-23", "regime": {"level": "mixed", "pass": 4, "known": 7},
                   "focus": ["Healthcare"], "turning": [], "avoid": ["Metals & Mining"],
                   "cap": "Large", "breakouts": ["AAA"], "pullbacks": [], "weekly": ["AAA"], "htf": ["AAA"],
                   "tags": {"AAA": ["tight"]}},
        "flows": {"months": [{"m": "2026-11", "fii": 117622.1, "dii": -64547.2, "to": "2026-11-23"}]},
    }


def test_compose_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "STATE", str(tmp_path / "st.json"))
    txt = send_brief.compose(data(), [])
    assert "23 Nov 2026" in txt and "🟡 <b>Mixed</b> (4/7 checks)" in txt
    assert "Healthcare · large caps" in txt and "Metals &amp; Mining" in txt    # escaped
    assert "+₹1,17,622 cr" in txt and "−₹64,547 cr" in txt
    assert "<b>AAA</b> RS 95, 3.0% off high, tight" in txt
    assert "Weekly trend — above the 10-week SMA</b> (1)" in txt and "+4.2% vs 10W, 7 wk above" in txt
    assert "High tight flags</b> (1)" in txt and "pole +140%, flag −14%, in the flag, 2.5% below pivot" in txt
    assert "early trigger 98 hit 23 Nov (stop 92)" in txt
    assert send_brief.compose({"levels": []}, []) is None


def test_watchlist_alerts_ema_cross_and_rerun(tmp_path):
    st = str(tmp_path / "state.json")
    d0 = data(e20=0)
    d0["decide"]["asof"] = "2026-11-20"
    d0["decide"]["breakouts"] = []
    assert watchlist.alerts(d0, ["AAA"], st) == []                 # nothing notable
    d1 = data(e20=1, h=0.2, ev="2026-11-26 Results")
    a = watchlist.alerts(d1, ["AAA"], st)
    assert len(a) == 1
    for bit in ("breakout watch (#1)", "back above its 20-day EMA", "52-week high", "📅 Results 26 Nov"):
        assert bit in a[0]
    assert watchlist.alerts(d1, ["AAA"], st) == a                  # same session re-run: same alert
    assert watchlist.alerts(d1, ["ZZZ"], st) == []                  # unknown symbol: silent


def test_watchlist_file_roundtrip(tmp_path):
    p = str(tmp_path / "wl.txt")
    assert watchlist.write(["reliance", "RELIANCE", "M&M", "bad sym!", ""], p) == ["RELIANCE", "M&M"]
    assert watchlist.read(p) == ["RELIANCE", "M&M"]
    assert watchlist.read(str(tmp_path / "none.txt")) == []
