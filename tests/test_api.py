"""API tests — FastAPI TestClient against the real rs_data.json (skipped when
the data file isn't generated).  Read-only endpoints only; the pipeline POST
endpoints are excluded (they spawn real subprocesses)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (ROOT / "rs_data.json").exists(),
    reason="rs_data.json not generated yet")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import backend.main as m
    with TestClient(m.app) as c:
        yield c


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    d = r.json()
    for key in ("benchmark", "window", "drange", "generated", "n_stocks",
                "n_groups_per_level", "n_window", "excluded", "src", "ipo"):
        assert key in d, key
    assert d["n_stocks"] > 0 and d["n_window"] <= d["n_stocks"]


def test_levels_summaries(client):
    r = client.get("/api/levels")
    assert r.status_code == 200
    keys = [lv["key"] for lv in r.json()]
    assert keys == ["macro", "sector", "industry", "basic"]


def test_level_detail_and_members(client):
    r = client.get("/api/levels/macro")
    assert r.status_code == 200
    d = r.json()
    assert d["key"] == "macro" and d["groups"]
    g = d["groups"][0]
    for key in ("id", "name", "n", "pct", "r", "members"):
        assert key in g, key
    m = g["members"][0]
    for key in ("n", "s", "r", "p", "e", "b", "l"):
        assert key in m, key


def test_level_404(client):
    assert client.get("/api/levels/nope").status_code == 404


def test_group_detail(client):
    gid = client.get("/api/levels/macro").json()["groups"][0]["id"]
    r = client.get(f"/api/groups/{gid}")
    assert r.status_code == 200
    assert r.json()["id"] == gid


def test_group_404(client):
    assert client.get("/api/groups/999999").status_code == 404


def test_breadth(client):
    r = client.get("/api/breadth")
    assert r.status_code == 200
    d = r.json()
    assert len(d["dates"]) == len(d["osc"]) > 100
    assert isinstance(d["macros"], list) and d["macros"]
    assert "divergence" in d and "state" in d["divergence"]


def test_rotation(client):
    r = client.get("/api/rotation")
    assert r.status_code == 200
    d = r.json()
    assert d["dates"] and d["groups"]
    g = d["groups"][0]
    assert len(g["rs"]) == len(d["dates"])


def test_stock_detail(client, monkeypatch, tmp_path):
    # Hermetic: synthetic price cache so CI (no real caches) works too.
    import json
    import backend.main as m
    import build_rs
    ser = {f"2026-08-{d:02d}": 100.0 + d for d in range(20, 32)}
    ser.update({f"2026-09-{d:02d}": 112.0 + d for d in range(1, 21)})
    bench = {d: 2000.0 + 2 * i for i, d in enumerate(sorted(ser))}
    p = tmp_path / ".yh_price_cache.json"
    p.write_text(json.dumps({"RELIANCE": ser, "__BENCH__": bench}))
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(p))
    monkeypatch.setattr(m, "_price_cache", None)
    r = client.get("/api/stock/RELIANCE")
    assert r.status_code == 200
    d = r.json()
    assert d["sym"] == "RELIANCE" and d["ltp"] > 0
    assert len(d["rs"]) == len(d["dates"]) == len(d["ema21"])
    assert d["rse"] in (0, 1)


def test_stock_404(client):
    assert client.get("/api/stock/NOTAREALSYMBOL").status_code == 404


def test_pipeline_status(client):
    r = client.get("/api/pipeline-status")
    assert r.status_code == 200
    d = r.json()
    assert d["running"] in (True, False) and "last_result" in d


def test_reload_drops_cached_prices(client):
    """After a pipeline run the per-stock charts must re-read the price cache."""
    import backend.main as m
    m._price_cache = {"STALE": {"2020-01-01": 1.0}}
    assert client.post("/api/reload").status_code == 200
    assert m._price_cache is None


def test_flows(client):
    r = client.get("/api/flows")
    assert r.status_code == 200
    f = r.json()
    assert set(f) >= {"months", "asof", "src"}
    if f["months"]:
        ms = [x["m"] for x in f["months"]]
        assert ms == sorted(ms) and len(set(ms)) == len(ms)
        x = f["months"][-1]
        assert abs(x["fb"] - x["fs"] - x["fii"]) < 1 and abs(x["db"] - x["ds"] - x["dii"]) < 1
    if f.get("days"):
        ds = [x["d"] for x in f["days"]]
        assert ds == sorted(ds) and len(set(ds)) == len(ds)
        for x in f["days"]:
            if x["fb"] is not None:
                assert abs(x["fb"] - x["fs"] - x["fii"]) < 1 and abs(x["db"] - x["ds"] - x["dii"]) < 1


def test_decide_and_track(client):
    d = client.get("/api/decide").json()
    if d:
        assert d["regime"]["level"] in ("on", "mixed", "off")
        assert isinstance(d["breakouts"], list) and len(d["focus"]) <= 3
    t = client.get("/api/track").json()
    assert isinstance(t, dict)


def test_watchlist_roundtrip(client, tmp_path, monkeypatch):
    import watchlist
    monkeypatch.setattr(watchlist, "WATCHLIST", str(tmp_path / "wl.txt"))
    assert client.get("/api/watchlist").json() == {"symbols": []}
    r = client.put("/api/watchlist", json={"symbols": ["tcs", "INFY", "TCS"]})
    assert r.json() == {"symbols": ["TCS", "INFY"]}
    assert client.get("/api/watchlist").json() == {"symbols": ["TCS", "INFY"]}
    assert client.put("/api/watchlist", json={"symbols": ["X"] * 501}).status_code == 400
