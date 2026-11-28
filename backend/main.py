"""
FastAPI backend for NSE Relative Strength.
Reads precomputed rs_data.json at startup and serves it as a JSON API.
Also serves the frontend static build.

Private by default (backend/auth.py): every /api call except login and the
health check needs a session cookie; the update / reload / watchlist-edit
actions need an admin.  NSE_RS_AUTH=0 turns login off for local development.
"""
import importlib.util
import json
import os
import sys
import subprocess
import threading
import time
import datetime as dt
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend import auth

from rs_engine.config import WINDOW, BENCHMARK_NAME, data_path
from backend.models import (
    MetaResponse, LevelSummary, LevelResponse,
    GroupOut, BreadthResponse, RotationResponse, StockDetail, FlowsResponse, WatchlistIn,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_PATH = data_path("rs_data.json")
STATIC_DIR = os.path.realpath(os.path.join(ROOT, "frontend", "dist"))

# In-memory data — loaded at startup, replaced on /api/reload.
# None means "not loaded yet" (startup in progress).
_data: dict | None = None
_group_index: dict[int, dict] = {}   # gid -> group dict for O(1) lookup
_data_mtime = 0.0                    # rs_data.json mtime when it was loaded
_mtime_checked = 0.0


def _load_data_from_disk():
    """Load rs_data.json into memory.  Called at startup and on /api/reload."""
    global _data, _group_index, _price_cache, _data_mtime
    _price_cache = None          # per-stock charts re-read the fresh price cache
    if not os.path.exists(DATA_PATH):
        print(f"WARNING: {DATA_PATH} not found. Run build_rs.py first.")
        _data = {"meta": {}, "levels": [], "breadth": None}
        _group_index = {}
        return
    _data_mtime = os.path.getmtime(DATA_PATH)
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


app = FastAPI(title="NSE Relative Strength", version="2.0.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

PUBLIC_API = {"/api/auth/login", "/api/health"}
ADMIN_API = {("POST", "/api/update-prices"), ("POST", "/api/refresh-stocks"),
             ("POST", "/api/reload"), ("PUT", "/api/watchlist")}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; "
                                "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                "form-action 'self'"),
}


def _maybe_reload():
    """The scheduler container rewrites rs_data.json on the shared volume:
    pick the new file up (checked at most every 5 s)."""
    global _mtime_checked
    now = time.time()
    if now - _mtime_checked < 5:
        return
    _mtime_checked = now
    try:
        if os.path.getmtime(DATA_PATH) > _data_mtime:
            _load_data_from_disk()
    except OSError:
        pass


@app.middleware("http")
async def guard(request: Request, call_next):
    """Session check for /api, admin check for the write actions, a custom
    header on state-changing calls (CSRF), security headers on everything."""
    path, method = request.url.path, request.method
    if path.startswith("/api/") and path not in PUBLIC_API:
        if auth.enabled():
            user = auth.read_token(request.cookies.get(auth.COOKIE, ""))
            if user is None:
                return JSONResponse({"detail": "login required"}, status_code=401,
                                    headers=SECURITY_HEADERS)
            if (method, path) in ADMIN_API and user["r"] != "admin":
                return JSONResponse({"detail": "admin only"}, status_code=403,
                                    headers=SECURITY_HEADERS)
            request.state.user = user
        else:
            request.state.user = {"u": "local", "r": "admin"}
    if path.startswith("/api/") and method not in ("GET", "HEAD", "OPTIONS") \
            and request.headers.get("x-nse-rs") != "1":
        return JSONResponse({"detail": "missing X-NSE-RS header"}, status_code=403,
                            headers=SECURITY_HEADERS)
    if path.startswith("/api/") and _data is not None:
        _maybe_reload()
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# ---- auth ----

class LoginIn(BaseModel):
    username: str
    password: str


def _client_ip(request: Request):
    return request.client.host if request.client else "?"


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    """Password login → HttpOnly session cookie (SameSite=Strict)."""
    if not auth.enabled():
        return {"user": "local", "role": "admin", "auth": False}
    ip, name = _client_ip(request), body.username.strip()
    keys = (f"ip:{ip}", f"user:{name.lower()}")
    if auth.locked(*keys):
        raise HTTPException(429, detail="too many failed logins — try again in 15 minutes")
    user = auth.authenticate(name, body.password)
    if user is None:
        auth.record_failure(*keys)
        raise HTTPException(401, detail="wrong username or password")
    auth.clear_failures(*keys)
    resp = JSONResponse({"user": name, "role": user["role"], "auth": True})
    resp.set_cookie(auth.COOKIE, auth.make_token(name, user), max_age=auth.SESSION_DAYS * 86400,
                    httponly=True, samesite="strict", path="/",
                    secure=os.environ.get("NSE_RS_COOKIE_SECURE", "1") != "0")
    return resp


@app.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.get("/api/auth/me")
def me(request: Request):
    """Who is signed in, and what this server can do for them."""
    u = request.state.user
    admin = u["r"] == "admin"
    return {"user": u["u"], "role": u["r"], "auth": auth.enabled(),
            "can": {"update_prices": admin,
                    "refresh_stocks": admin and importlib.util.find_spec("playwright") is not None,
                    "edit_watchlist": admin}}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    """Liveness + data freshness for the container healthcheck / monitoring."""
    meta = (_data or {}).get("meta", {})
    return {"ok": _data is not None, "generated": meta.get("gen"),
            "asof": ((_data or {}).get("decide") or {}).get("asof")}


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
        "illiquid": m.get("illiquid", []),
        "src": m.get("src", {}),
        "ipo": m.get("ipo", []),
        "window_dates": m.get("window_dates", []),
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
                    dp=g.get("dp"),
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
        dp=g.get("dp"),
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
        "market": brd.get("market", {}),
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


@app.get("/api/decide")
def get_decide():
    """Focus / Swing decisions computed by the build (rs_engine.decide)."""
    _check_ready()
    return _data.get("decide") or {}


@app.get("/api/track")
def get_track():
    """Track record of the Focus / Swing calls (rs_engine.track)."""
    _check_ready()
    return _data.get("track") or {}


def _watchlist():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import watchlist
    return watchlist


@app.get("/api/watchlist")
def get_watchlist():
    """Starred symbols the evening brief alerts on (~/.config/nse-rs/watchlist.txt)."""
    return {"symbols": _watchlist().read()}


@app.put("/api/watchlist")
def put_watchlist(body: WatchlistIn):
    """Replace the alert watchlist with the site's ☆ list."""
    if len(body.symbols) > 500:
        raise HTTPException(400, detail="too many symbols")
    return {"symbols": _watchlist().write(body.symbols)}


@app.get("/api/flows", response_model=FlowsResponse)
def get_flows():
    """FII / DII net cash-market flows by month and by session (NSE provisional, ₹ crore)."""
    _check_ready()
    f = _data.get("flows") or {}
    return {"months": f.get("months", []), "days": f.get("days", []), "asof": f.get("asof"), "src": f.get("src", "")}


@app.get("/api/stock/{sym}", response_model=StockDetail)
def get_stock(sym: str):
    """Per-stock RS line (stock / NIFTY 500) + its 21-day EMA — the
    TradingView-style chart — computed on demand from the price cache."""
    _check_ready()
    from rs_engine.maths import rs_line
    cache = _prices()
    ser = cache.get(sym)
    bench = cache.get("__BENCH__", {})
    if not ser or not bench:
        raise HTTPException(404, f"unknown symbol: {sym}")
    line = rs_line(ser, bench)
    if not line:
        raise HTTPException(404, f"no benchmark overlap for: {sym}")
    days, rs, ema = line
    name = next((m["n"] for lv in _data.get("levels", [])
                 for g in lv.get("groups", []) for m in g.get("members", [])
                 if m["s"] == sym),
                next((i["n"] for i in _data.get("meta", {}).get("ipo", [])
                      if i["s"] == sym), ""))     # new listings aren't in a level
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


def _run_script(args: list[str] | list[list[str]], task_name: str):
    """Run a script — or several in sequence, stopping at the first failure —
    in the background, capture output, auto-reload data."""
    steps = args if args and isinstance(args[0], list) else [args]
    try:
        out, ok = "", True
        for step in steps:
            result = subprocess.run(
                [sys.executable] + step, cwd=ROOT, capture_output=True,
                text=True, timeout=900,
            )
            out += result.stdout + "\n" + result.stderr
            if result.returncode != 0:
                ok = False
                break
        out = out[-1500:]
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

    # a real refresh is followed by a quick build, so new listings show up
    args = (["refresh_classification.py", "--dry-run"] if dry_run else
            [["refresh_classification.py"], ["refresh_flows.py"], ["refresh_events.py"],
             ["build_rs.py", "--fast"]])

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

class _HashedAssets(StaticFiles):
    """Vite's /assets/* names carry a content hash: cache them for a year."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


if os.path.isdir(os.path.join(STATIC_DIR, "assets")):
    app.mount("/assets", _HashedAssets(directory=os.path.join(STATIC_DIR, "assets")),
              name="assets")

if os.path.isdir(STATIC_DIR):

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])   # HEAD: uptime monitors
    async def serve_spa(path: str):
        """Serve frontend static files; fall back to index.html for SPA routing."""
        # Resolve the requested path and prevent directory traversal.
        # Use abspath first (resolves `..` components) then realpath (symlinks).
        resolved = os.path.realpath(os.path.abspath(os.path.join(STATIC_DIR, path)))
        if not resolved.startswith(STATIC_DIR + os.sep) and resolved != STATIC_DIR:
            raise HTTPException(status_code=404)  # traversal attempt — refuse
        if path.startswith("api/"):
            raise HTTPException(status_code=404)   # unknown API route: no SPA page
        if path and os.path.isfile(resolved):
            return FileResponse(resolved)
        # index.html must never be cached: it names the current hashed bundles —
        # a stale copy keeps old JS in the browser.
        return FileResponse(os.path.join(STATIC_DIR, "index.html"),
                            headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
