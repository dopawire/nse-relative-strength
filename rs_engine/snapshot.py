"""Daily ranking archive (snapshots.jsonl), deltas, and IPO watch."""

import os
import json
import datetime as dt

from rs_engine.config import CACHE_DIR, WINDOW, IST


SNAPSHOTS = os.path.join(CACHE_DIR, "snapshots.jsonl")   # daily ranking archive



def _read_lines():
    if not os.path.exists(SNAPSHOTS):
        return []
    with open(SNAPSHOTS) as fh:
        return [ln for ln in fh if ln.strip()]


def load_previous_snapshot(before=None):
    """Last archived snapshot — or, with `before`, the last one whose window
    ends strictly before that date.  None if there is none."""
    try:
        for line in reversed(_read_lines()):
            snap = json.loads(line)
            if before is None or snap.get("end", "") < before:
                return snap
    except Exception:
        pass
    return None


def append_snapshot(levels, window_end):
    """Archive today's rankings — one JSONL line per window end.  A rebuild of
    the same window REPLACES its line, so the archive keeps the final data."""
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
    lines = _read_lines()
    if lines and json.loads(lines[-1]).get("end") == window_end:
        lines = lines[:-1]
    lines.append(json.dumps(line, separators=(",", ":")) + "\n")
    tmp = SNAPSHOTS + ".tmp"
    with open(tmp, "w") as fh:
        fh.writelines(lines)
    os.replace(tmp, SNAPSHOTS)
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


def _close_on_or_before(series, day):
    days = [d for d in series if d <= day]
    return series[max(days)] if days else None


def _listing_perf(ser, bench):
    """% return from the listing-day close to the latest close, NIFTY 500's
    return over the same dates, and the relative performance
    ((1 + stock) / (1 + bench) − 1).  Empty when the benchmark lacks data."""
    first, last = min(ser), max(ser)
    b0, b1 = _close_on_or_before(bench, first), _close_on_or_before(bench, last)
    if not (ser[first] and b0 and b1):
        return {}
    ret = ser[last] / ser[first] - 1
    bret = b1 / b0 - 1
    return {"base": round(ser[first], 2),
            "ret": round(ret * 100, 2),
            "bret": round(bret * 100, 2),
            "xret": round(((1 + ret) / (1 + bret) - 1) * 100, 2)}


def build_ipo_watch(universe, cache, excluded, bench=None):
    """New listings not yet rankable (< WINDOW days of data) — and stocks NSE
    hasn't classified yet (`uc`: no group to rank them in): symbol, name,
    first trading day, days of history, LTP, days until first ranking, and
    performance since the listing-day close (`perf`, needs >= 2 sessions):
    the stock's % return, NIFTY 500's over the same dates, and the stock's
    out-/under-performance vs it.  Plus the RS line + EMA21 (`bench` given)
    so the UI can chart them even where the /api/stock endpoint isn't
    available (static site)."""
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
        if bench and len(ser) >= 2:
            entry.update(_listing_perf(ser, bench))
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


