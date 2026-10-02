"""Daily ranking archive (snapshots.jsonl), deltas, and IPO watch."""

import os
import json
import datetime as dt

from rs_engine.config import CACHE_DIR, WINDOW


SNAPSHOTS = os.path.join(CACHE_DIR, "snapshots.jsonl")   # daily ranking archive



def load_previous_snapshot():
    """Last line of the ranking archive, or None."""
    if not os.path.exists(SNAPSHOTS):
        return None
    try:
        with open(SNAPSHOTS) as fh:
            last = ""
            for line in fh:
                if line.strip():
                    last = line
            return json.loads(last) if last else None
    except Exception:
        return None


def append_snapshot(levels, window_end):
    """Append today's rankings to the archive (one JSONL line per window end;
    idempotent across rebuilds of the same day)."""
    prev = load_previous_snapshot()
    if prev and prev.get("end") == window_end:
        return prev
    g = {}
    m = {}
    for key, _label, items in levels:
        g[key] = {}
        for it in items:
            g[key][it["name"]] = round(it["pct"], 4)
            for stock in it["members"]:
                m[stock["sym"]] = round(stock["pct"], 4)
    line = {"end": window_end,
            "gen": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "g": g, "m": m}
    with open(SNAPSHOTS, "a") as fh:
        fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return line


def build_ipo_watch(universe, cache, excluded):
    """New listings not yet rankable (< WINDOW days of data): symbol, name,
    first trading day, days of history, LTP, days until first ranking."""
    out = []
    for u in universe:
        sym = u["sym"]
        if sym not in excluded:
            continue
        ser = cache.get(sym)
        if not ser or len(ser) >= WINDOW:
            continue
        first = min(ser)
        out.append({"s": sym, "n": u["name"], "first": first,
                    "days": len(ser), "ltp": round(ser[max(ser)], 2),
                    "eta": WINDOW - len(ser)})
    out.sort(key=lambda x: x["first"], reverse=True)
    return out


