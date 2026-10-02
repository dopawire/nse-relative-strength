"""
FastAPI backend for NSE Relative Strength.
Reads precomputed rs_data.json at startup and serves it as a JSON API.
Also serves the frontend static build.
"""
import json
import os
import sys
import subprocess
import threading
import datetime as dt
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.models import (
    MetaResponse, LevelSummary, LevelResponse,
    GroupOut, BreadthResponse, RotationResponse, StockDetail,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_PATH = os.path.join(ROOT, "rs_data.json")
STATIC_DIR = os.path.realpath(os.path.join(ROOT, "frontend", "dist"))
WINDOW = 26
BENCHMARK_NAME = "NIFTY 500"

# In-memory data — loaded at startup, replaced on /api/reload.
# None means "not loaded yet" (startup in progress).
_data: dict | None = None
_group_index: dict[int, dict] = {}   # gid -> group dict for O(1) lookup


def _load_data_from_disk():
    """Load rs_data.json into memory.  Called at startup and on /api/reload."""
    global _data, _group_index
    if not os.path.exists(DATA_PATH):
        print(f"WARNING: {DATA_PATH} not found. Run build_rs.py first.")
        _data = {"meta": {}, "levels": [], "breadth": None}
        _group_index = {}
        return
    with open(DATA_PATH) as f:
        _data = json.load(f)
    _group_index = {}
    for lv in _data.get("levels", []):
        for g in lv.get("groups", []):
            _group_index[g["id"]] = g
    print(f"Loaded RS data: {len(_data.get('levels', []))} levels, "
          f"{len(_group_index)} groups, "
          f"generated {_data.get('meta', {}).get('gen', 'unknown')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_data_from_disk()
    yield


app = FastAPI(title="NSE Relative Strength", version="1.0.0", lifespan=lifespan)


# ---- API endpoints ----

def _check_ready():
    """Guard against calls before startup finishes or after load failure."""
    if _data is None:
        raise HTTPException(status_code=503, detail="Server starting up — retry in a moment")


@app.get("/api/meta", response_model=MetaResponse)
def get_meta():
    _check_ready()
    m = _data.get("meta", {})
    levels = _data.get("levels", [])
    return {
        "benchmark": BENCHMARK_NAME,
        "window": WINDOW,
        "drange": m.get("drange", ""),
        "generated": m.get("gen", ""),
        "n_stocks": m.get("n_stocks", 0),
        "n_groups_per_level": [len(lv.get("groups", [])) for lv in levels],
        "n_window": m.get("n_window", 0),
        "excluded": m.get("excluded", []),
        "src": m.get("src", {}),
        "ipo": m.get("ipo", []),
    }


@app.get("/api/levels", response_model=list[LevelSummary])
def get_levels():
    _check_ready()
    return [
        {"key": lv["key"], "label": lv["label"], "n_groups": len(lv.get("groups", []))}
        for lv in _data.get("levels", [])
    ]


@app.get("/api/levels/{key}", response_model=LevelResponse)
def get_level(key: str):
    _check_ready()
    for lv in _data.get("levels", []):
        if lv["key"] == key:
            groups = []
            for g in lv.get("groups", []):
                groups.append(GroupOut(
                    id=g["id"],
                    name=g["name"],
                    n=g["n"],
                    pct=g["pct"],
                    r=g["r"],
                    members=g.get("members", []),
                ))
            return LevelResponse(key=lv["key"], label=lv["label"], groups=groups)
    raise HTTPException(status_code=404, detail=f"Level '{key}' not found")


@app.get("/api/groups/{gid}", response_model=GroupOut)
def get_group(gid: int):
    _check_ready()
    g = _group_index.get(gid)
    if g is None:
        raise HTTPException(status_code=404, detail=f"Group {gid} not found")
    return GroupOut(
        id=g["id"],
        name=g["name"],
        n=g["n"],
        pct=g["pct"],
        r=g["r"],
        members=g.get("members", []),
    )


@app.get("/api/breadth", response_model=BreadthResponse)
def get_breadth():
    _check_ready()
    brd = _data.get("breadth") or {}
    dates = brd.get("dates", [])
    osc = brd.get("osc", [])
    return {
        "dates": dates,
        "osc": osc,
        "n": brd.get("n", 0),
        "latest": osc[-1] if osc else 0.0,
        "span": f"{dates[0]} → {dates[-1]}" if dates else "",
        "macros": brd.get("macros", []),
        "divergence": brd.get("divergence", {}),
    }


# ---- Phase 4: rotation RS-lines + per-stock RS chart ----------------------- #

_price_cache: dict | None = None


def _prices():
    """Lazy-load the raw price cache (needed for per-stock RS lines)."""
    global _price_cache
    if _price_cache is None:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import build_rs
        try:
            with open(build_rs.PRICE_CACHE) as fh:
                _price_cache = json.load(fh)
        except Exception:
            _price_cache = {}
    return _price_cache


@app.get("/api/rotation", response_model=RotationResponse)
def get_rotation():
    """Full-history RS lines per sector group (rotation view)."""
    _check_ready()
    r = _data.get("rotation") or {}
    return {"dates": r.get("dates", []), "groups": r.get("groups", [])}


@app.get("/api/stock/{sym}", response_model=StockDetail)
def get_stock(sym: str):
    """Per-stock RS line (stock / NIFTY 500) + its 21-day EMA — the
    TradingView-style chart — computed on demand from the price cache."""
    _check_ready()
    cache = _prices()
    ser = cache.get(sym)
    bench = cache.get("__BENCH__", {})
    if not ser or not bench:
        raise HTTPException(404, f"unknown symbol: {sym}")
    days = [d for d in sorted(ser) if d in bench][-125:]
    if not days:
        raise HTTPException(404, f"no benchmark overlap for: {sym}")
    rs = [ser[d] / bench[d] for d in days]
    k = 2.0 / 22
    ema = [rs[0]]
    for v in rs[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    name = ""
    for lv in _data.get("levels", []):
        for g in lv.get("groups", []):
            for m in g.get("members", []):
                if m["s"] == sym:
                    name = m["n"]
    return {"sym": sym, "name": name, "dates": days, "rs": rs,
            "ema21": ema, "ltp": ser[days[-1]],
            "rse": 1 if rs[-1] >= ema[-1] else 0}


@app.post("/api/reload")
def reload_data():
    """Hot-reload rs_data.json after a daily pipeline run — no server restart needed."""
    _load_data_from_disk()
    return {"status": "ok", "generated": _data.get("meta", {}).get("gen", "")}


# ---- Pipeline runner (background subprocess) ----

_pipeline = {
    "running": False,
    "task": None,          # 'prices' or 'stocks'
    "last_result": None,   # 'ok' or 'error: ...'
    "last_output": "",     # tail of stdout/stderr
    "started_at": None,    # ISO timestamp
    "finished_at": None,
}
_pipeline_lock = threading.Lock()


def _run_script(args: list[str], task_name: str):
    """Run a script in the background, capture output, auto-reload data."""
    py = sys.executable
    cmd = [py] + args
    try:
        result = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        out = (result.stdout + "\n" + result.stderr)[-1500:]
        ok = result.returncode == 0
    except subprocess.TimeoutExpired:
        out = "Timed out after 15 minutes"
        ok = False
    except Exception as e:
        out = f"Error: {e}"
        ok = False

    with _pipeline_lock:
        _pipeline["running"] = False
        _pipeline["task"] = None
        _pipeline["last_result"] = "ok" if ok else "failed"
        _pipeline["last_output"] = out.strip()
        _pipeline["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")

    # If successful, reload the data into the API
    if ok:
        _load_data_from_disk()


@app.post("/api/update-prices")
def update_prices(full: bool = Query(False, description="Full 2y re-fetch instead of incremental top-up")):
    """Fetch latest prices from Yahoo and recompute RS rankings."""
    with _pipeline_lock:
        if _pipeline["running"]:
            raise HTTPException(409, detail=f"Already running: {_pipeline['task']}")
        _pipeline["running"] = True
        _pipeline["task"] = "prices"
        _pipeline["last_result"] = None
        _pipeline["last_output"] = ""
        _pipeline["started_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _pipeline["finished_at"] = None

    args = ["build_rs.py"]
    if full:
        args.append("--refresh")
    else:
        args.append("--fast")

    threading.Thread(target=_run_script, args=(args, "prices"), daemon=True).start()
    return {"status": "started", "full": full, "started_at": _pipeline["started_at"]}


@app.post("/api/refresh-stocks")
def refresh_stocks(dry_run: bool = Query(False, description="Only list new symbols, don't fetch")):
    """Fetch new NSE stock listings and their industry classifications."""
    with _pipeline_lock:
        if _pipeline["running"]:
            raise HTTPException(409, detail=f"Already running: {_pipeline['task']}")
        _pipeline["running"] = True
        _pipeline["task"] = "stocks"
        _pipeline["last_result"] = None
        _pipeline["last_output"] = ""
        _pipeline["started_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _pipeline["finished_at"] = None

    args = ["refresh_classification.py"]
    if dry_run:
        args.append("--dry-run")

    threading.Thread(target=_run_script, args=(args, "stocks"), daemon=True).start()
    return {"status": "started", "dry_run": dry_run, "started_at": _pipeline["started_at"]}


@app.get("/api/pipeline-status")
def pipeline_status():
    """Check whether a pipeline task is running and its last result."""
    with _pipeline_lock:
        return {
            "running": _pipeline["running"],
            "task": _pipeline["task"],
            "started_at": _pipeline["started_at"],
            "finished_at": _pipeline["finished_at"],
            "last_result": _pipeline["last_result"],
            "last_output": _pipeline["last_output"],
        }


# ---- Serve frontend static files (must be after API routes) ----

if os.path.isdir(STATIC_DIR):

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve frontend static files; fall back to index.html for SPA routing."""
        # Resolve the requested path and prevent directory traversal.
        # Use abspath first (resolves `..` components) then realpath (symlinks).
        resolved = os.path.realpath(os.path.abspath(os.path.join(STATIC_DIR, path)))
        if not resolved.startswith(STATIC_DIR + os.sep) and resolved != STATIC_DIR:
            raise HTTPException(status_code=404)  # traversal attempt — refuse
        if path and os.path.isfile(resolved):
            return FileResponse(resolved)
        # index.html must never be cached: it carries the app.js/app.css version
        # query strings — a stale copy keeps old JS in the browser forever.
        return FileResponse(os.path.join(STATIC_DIR, "index.html"),
                            headers={"Cache-Control": "no-cache"})

    # Mount assets directly for proper caching headers
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
