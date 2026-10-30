"""Daily ranking archive (snapshots.jsonl), deltas, and IPO watch."""

import os
import json
import datetime as dt

from rs_engine.config import CACHE_DIR, WINDOW, IST


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
            "gen": dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
            "g": g, "m": m}
    with open(SNAPSHOTS, "a") as fh:
        fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return line


def seed_from_rs_data(path):
    """Append the rankings in a committed rs_data.json to the archive when the
    archive is behind it — a fresh cloud runner (empty cache) or a machine
    that pulled a newer snapshot then computes daily deltas against the last
    PUBLISHED rankings instead of none / stale ones.  Returns True if seeded."""
    try:
        with open(path) as fh:
            data = json.load(fh)
        end = data["meta"]["window_dates"][-1]
    except (OSError, ValueError, KeyError, IndexError):
        return False
    prev = load_previous_snapshot()
    if prev and prev.get("end", "") >= end:
        return False
    g = {lv["key"]: {grp["name"]: grp["pct"] for grp in lv["groups"]}
         for lv in data.get("levels", [])}
    m = {mem["s"]: mem["p"] for lv in data.get("levels", [])
         for grp in lv["groups"] for mem in grp["members"]}
    line = {"end": end, "gen": data["meta"].get("gen", ""), "g": g, "m": m}
    with open(SNAPSHOTS, "a") as fh:
        fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return True


def build_ipo_watch(universe, cache, excluded, bench=None):
    """New listings not yet rankable (< WINDOW days of data) — and stocks NSE
    hasn't classified yet (`uc`: no group to rank them in): symbol, name,
    first trading day, days of history, LTP, days until first ranking — plus
    the stock's RS line + EMA21 (`bench` given) so the UI can chart them even
    where the /api/stock endpoint isn't available (static site)."""
    from rs_engine.maths import rs_line
    out = []
    for u in universe:
        sym = u["sym"]
        if sym not in excluded:
            continue
        ser = cache.get(sym)
        unclassified = not any(u.get(k) for k in ("macro", "sector", "industry", "basic"))
        if not ser or (len(ser) >= WINDOW and not unclassified):
            continue
        first = min(ser)
        entry = {"s": sym, "n": u["name"], "first": first,
                 "days": len(ser), "ltp": round(ser[max(ser)], 2),
                 "eta": max(0, WINDOW - len(ser))}
        if unclassified:
            entry["uc"] = True
        if bench:
            line = rs_line(ser, bench)
            if line:
                days, rs, ema = line
                entry["dates"] = days
                entry["rs"] = [round(x, 5) for x in rs]
                entry["ema21"] = [round(x, 5) for x in ema]
        out.append(entry)
    out.sort(key=lambda x: x["first"], reverse=True)
    return out


