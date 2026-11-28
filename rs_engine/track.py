"""Track record of the Focus / Swing calls.

Every build appends the day's picks to nse_picks.jsonl (one line per
session; backfilled days carry "bt": true).  evaluate() then measures each
call 5 / 10 / 20 sessions later from the adjusted price cache:

  breakouts / pullbacks / IPO bases / weekly trend / high tight flags
                          average return of the listed stocks vs NIFTY 500,
                          and the share of them that beat NIFTY 500
  focus sectors           their stocks' average return vs the average stock
  avoid sectors           how far they trailed the average stock
  size pick               that size class vs the average stock
  regime                  NIFTY 500's forward return by regime level
"""
import json
import os
from statistics import mean

from rs_engine.config import CORP_ACTION_JUMP, data_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICKS = data_path("nse_picks.jsonl")
HORIZONS = (5, 10, 20)
N_BREAKOUTS, N_PULLBACKS, N_IPOS, N_WEEKLY, N_HTF = 25, 15, 15, 25, 15


def pick_record(dec, backtest=False):
    rec = {"date": dec["asof"], "regime": dec["regime"]["level"],
           "pass": dec["regime"]["pass"], "known": dec["regime"]["known"],
           "focus": dec["focus"], "avoid": dec["avoid"], "turning": dec["turning"],
           "cap": dec["cap"], "breakouts": dec["breakouts"][:N_BREAKOUTS],
           "pullbacks": dec["pullbacks"][:N_PULLBACKS], "ipos": dec.get("ipos", [])[:N_IPOS],
           "weekly": dec.get("weekly", [])[:N_WEEKLY], "htf": dec.get("htf", [])[:N_HTF]}
    if backtest:
        rec["bt"] = True
    return rec


def read_picks(path=None):
    path = path or PICKS
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def write_picks(recs, path=None):
    path = path or PICKS
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in sorted(recs, key=lambda r: r["date"]):
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def save_pick(rec, path=None):
    """Insert / replace the line for rec's date.  A live pick replaces a
    backfilled one; a backfill never overwrites a live pick."""
    recs = {r["date"]: r for r in read_picks(path)}
    old = recs.get(rec["date"])
    if old and not old.get("bt") and rec.get("bt"):
        return False
    recs[rec["date"]] = rec
    write_picks(recs.values(), path)
    return True


def add_missing(rec, path=None):
    """Give a live pick the lists it was logged without (a list added to the
    rules later, e.g. "ipos"), from a backfilled rec of the same day.  The
    live lists already there are never touched."""
    recs = {r["date"]: r for r in read_picks(path)}
    old = recs.get(rec["date"])
    if not old:
        return False
    new = {k: v for k, v in rec.items() if k not in old and k != "bt"}
    if not new:
        return False
    old.update(new)
    write_picks(recs.values(), path)
    return True


def fwd_return(ser, d0, d1, path_days):
    """Close-to-close return d0 → d1, None if either close is missing or a
    corporate-action jump lies on the way (a split is not a loss)."""
    a, b = ser.get(d0), ser.get(d1)
    if not a or not b:
        return None
    prev = a
    for d in path_days:
        v = ser.get(d)
        if v is None:
            continue
        if prev and abs(v / prev - 1) > CORP_ACTION_JUMP:
            return None
        prev = v
    return b / a - 1


def evaluate(picks, cache, universe, horizons=HORIZONS):
    """→ {"rows": [...], "summary": {h: {...}}} — see the module docstring.
    `universe` = [{sym, sector, cap}] (current classification)."""
    bench = cache.get("__BENCH__", {})
    dates = sorted(bench)
    pos = {d: i for i, d in enumerate(dates)}
    by_sector, by_cap = {}, {}
    for u in universe:
        by_sector.setdefault(u.get("sector"), []).append(u["sym"])
        by_cap.setdefault(u.get("cap"), []).append(u["sym"])
    syms = [u["sym"] for u in universe if cache.get(u["sym"])]

    rows = []
    for p in sorted(picks, key=lambda r: r["date"]):
        i = pos.get(p["date"])
        if i is None:
            continue
        row = {"date": p["date"], "regime": p["regime"], "focus": p["focus"],
               "cap": p["cap"], "bt": bool(p.get("bt")), "h": {}}
        for h in horizons:
            if i + h >= len(dates):
                continue
            d0, d1 = dates[i], dates[i + h]
            path = dates[i + 1:i + h + 1]
            rets = {}
            for s in syms:
                r = fwd_return(cache[s], d0, d1, path)
                if r is not None:
                    rets[s] = r
            if not rets:
                continue
            avg = mean(rets.values())
            nifty = bench[d1] / bench[d0] - 1

            def grp(members):
                v = [rets[s] for s in members if s in rets]
                return mean(v) if v else None

            def stock_list(lst):
                v = [rets[s] for s in lst if s in rets]
                if not v:
                    return None
                return {"n": len(v), "ret": mean(v), "ex": mean(v) - nifty,
                        "hit": len([x for x in v if x > nifty]) / len(v)}
            focus = grp([s for sec in p["focus"] for s in by_sector.get(sec, [])])
            avoid = grp([s for sec in p["avoid"] for s in by_sector.get(sec, [])])
            cap = grp(by_cap.get(p["cap"], [])) if p.get("cap") else None
            row["h"][h] = {
                "nifty": nifty, "avg": avg,
                "focus": None if focus is None else focus - avg,
                "avoid": None if avoid is None else avg - avoid,      # > 0 = right call
                "cap": None if cap is None else cap - avg,
                "brk": stock_list(p.get("breakouts", [])),
                "pb": stock_list(p.get("pullbacks", [])),
                "ipo": stock_list(p.get("ipos", [])),
                "wkl": stock_list(p.get("weekly", [])),
                "htf": stock_list(p.get("htf", [])),
            }
        rows.append(row)
    return {"rows": rows, "summary": summarise(rows, horizons)}


def summarise(rows, horizons=HORIZONS):
    """Per horizon: average edge and how often the call was right.  Days
    overlap (a 20-day window starts every day), so hit rates are of days,
    not independent trades."""
    out = {}
    for h in horizons:
        hs = [r["h"][h] for r in rows if h in r["h"]]
        if not hs:
            continue

        def edge(key):
            v = [x[key] for x in hs if x.get(key) is not None]
            return None if not v else {"n": len(v), "avg": mean(v),
                                       "hit": len([x for x in v if x > 0]) / len(v)}

        def lists(key):
            v = [x[key] for x in hs if x.get(key)]
            return None if not v else {"n": len(v), "ex": mean(x["ex"] for x in v),
                                       "ret": mean(x["ret"] for x in v),
                                       "hit": mean(x["hit"] for x in v)}
        reg, brk_reg = {}, {}
        for lvl in ("on", "mixed", "off"):
            v = [r["h"][h]["nifty"] for r in rows if h in r["h"] and r["regime"] == lvl]
            if v:
                reg[lvl] = {"n": len(v), "nifty": mean(v),
                            "up": len([x for x in v if x > 0]) / len(v)}
            # the regime's real job: when do breakouts pay?
            b = [r["h"][h]["brk"] for r in rows
                 if h in r["h"] and r["regime"] == lvl and r["h"][h].get("brk")]
            if b:
                brk_reg[lvl] = {"n": len(b), "ex": mean(x["ex"] for x in b),
                                "hit": mean(x["hit"] for x in b)}
        out[h] = {"days": len(hs), "focus": edge("focus"), "avoid": edge("avoid"),
                  "cap": edge("cap"), "brk": lists("brk"), "pb": lists("pb"), "ipo": lists("ipo"),
                  "wkl": lists("wkl"), "htf": lists("htf"), "regime": reg, "brk_regime": brk_reg}
    return out


def _round(o):
    if isinstance(o, float):
        return round(o, 4)
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v) for v in o]
    return o


def track_for_site(result, last=30):
    """The slice rs_data.json carries: summary + the latest rows."""
    rows = result["rows"]
    return _round({"summary": {str(k): v for k, v in result["summary"].items()},
                   "rows": [{**r, "h": {str(k): v for k, v in r["h"].items()}}
                            for r in rows[-last:]][::-1],
                   "since": rows[0]["date"] if rows else None,
                   "live_since": next((r["date"] for r in rows if not r["bt"]), None),
                   "n": len(rows)})
