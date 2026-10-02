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


def test_stock_detail(client):
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
