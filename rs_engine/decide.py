"""Focus + Swing decisions — the rules behind the two pages, in one place.

Input is one record per stock (the fields rs_data.json carries for a member:
s, n, sector, industry, cap, e, b, h, a, l, nw, m1, m3, w1, tv, rr, plus the
optional setup fields vr / tt / dl and the ipo block), the NIFTY 500 trend, the breadth
oscillator and the month's FII flow.  Output is plain data: the pages render
it, the pick log records it and the evening brief sends it, so all three
always agree.

    analyse(stocks, market, osc, fii_month, group_pct)  → dict
"""
from statistics import median as _median

# EMA flags follow EMA_PERIODS = [20, 50, 100, 150, 200]
EMA_I = {20: 0, 50: 1, 100: 2, 150: 3, 200: 4}

GROUP_SPECS = [("rel1", 0.30), ("rel3", 0.20), ("p50", 0.20), ("leadPct", 0.15), ("pct", 0.15)]
CAP_SPECS = [("rel1", 0.35), ("rel3", 0.20), ("p50", 0.25), ("leadPct", 0.10), ("nearHi", 0.10)]
CAP_ORDER = ["Large", "Mid", "Small", "Micro"]

# Breakout: leaders in a full uptrend near their highs, liquid, with enough
# daily range to pay for the risk — and not already extended.
SWING = {"minRS": 80, "maxOffHigh": 10, "minAdr": 2, "maxAdr": 8, "minTurnoverCr": 5,
         "minPrice": 50, "maxWeek": 15, "maxMonth": 50, "pbMinRS": 75, "pbOffHigh": (5, 25)}
# IPO bases: a mainboard IPO from its first weeks to a year old has no RS
# rating (< 3 months) and no 150/200-day EMA, so the breakout screen can't
# see it.  Its own screen: holding above the issue price, beating NIFTY 500
# since listing, above every EMA it has, near its high since listing.
IPO = {"minAge": 10, "maxAge": 250, "maxOffHigh": 10, "minAdr": 2, "maxAdr": 10, "maxWeek": 15}
# Weekly trend: the weekly timeframe — weekly close above a rising 10-week
# SMA (TradingView's weekly bar: the running week closes at the latest close),
# RS leaders, tradeable range, not extended; ranked by RS rating.  Backtest
# (230 sessions, top 25): +3.1% vs NIFTY 500 over 20 sessions, median +1.7%,
# 54% beat it — vs +1.2% for RS-80 stocks below their 10-week line.
WEEKLY = {"sma": 10, "minRS": 90, "minAdr": 2, "maxAdr": 8, "maxWeek": 15, "maxMonth": 50, "near": 5}
# High Tight Flags (maths.htf_state finds them): liquid stocks only.  NSE
# test of htf_state itself (86 liquid breakouts, Nov 2024 – Nov 2026): +4.8%
# vs NIFTY 500 over 20 sessions; with volume drying up in the flag +6.8%, 37%
# reached +20% before −8% and 26% went +50% within 3 months (without: +2.8%,
# 29%, 15%; ordinary breakouts: 24%, 6%).  Fat tail, median ≈ flat — stops.
HTF_RULES = {"minPole": 100, "poleWeeks": 9, "maxFlag": 25, "flagWeeks": [1, 8], "dry": 0.7,
             "boDays": 5}
N_BREAKOUTS, N_PULLBACKS, N_EXTENDED, N_IPOS, N_WEEKLY, N_HTF = 25, 15, 12, 15, 25, 15


def median(xs):
    v = [x for x in xs if x is not None]
    return _median(v) if v else None


def above(m, p):
    e = m.get("e") or []
    return len(e) > EMA_I[p] and e[EMA_I[p]] == 1


def has_ema(m, p):
    e = m.get("e") or []
    return len(e) > EMA_I[p] and e[EMA_I[p]] != -1


def share(lst, f):
    return len([m for m in lst if f(m)]) / len(lst) * 100 if lst else None


def sgn(v, dp=1):
    return "—" if v is None else f"{'+' if v >= 0 else '−'}{abs(v):.{dp}f}%"


def crore(v):
    """₹ crore in Indian grouping: 111949 → +₹1,11,949 cr."""
    s = f"{abs(round(v)):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{'+' if v >= 0 else '−'}₹{s} cr"


def group_stats(lst, base=None):
    """Group health from its stocks — medians, so one wild stock can't carry
    a group.  rel1 / rel3 compare with the median of ALL stocks (the average
    stock), the same equal-weight view as the RS tabs."""
    e50 = [m for m in lst if has_ema(m, 50)]
    e200 = [m for m in lst if has_ema(m, 200)]
    r = {"n": len(lst),
         "m1": median(m.get("m1") for m in lst), "m3": median(m.get("m3") for m in lst),
         "w1": median(m.get("w1") for m in lst),
         "p50": share(e50, lambda m: above(m, 50)), "p200": share(e200, lambda m: above(m, 200)),
         "lead": len([m for m in lst if (m.get("rr") or 0) >= 80]),
         "leadPct": share(lst, lambda m: (m.get("rr") or 0) >= 80),
         "nearHi": share(lst, lambda m: m.get("h") is not None and m["h"] <= 10),
         "rr": median(m.get("rr") for m in lst)}
    if base is not None:
        r["rel1"] = None if r["m1"] is None or base["m1"] is None else r["m1"] - base["m1"]
        r["rel3"] = None if r["m3"] is None or base["m3"] is None else r["m3"] - base["m3"]
        if r["rel1"] is None or r["rel3"] is None:
            r["quad"] = "Lagging"
        elif r["rel3"] >= 0:
            r["quad"] = "Leading" if r["rel1"] >= 0 else "Weakening"
        else:
            r["quad"] = "Improving" if r["rel1"] >= 0 else "Lagging"
    return r


def rank_score(rows, specs):
    """Weighted percentile rank (0-100) across the rows; a missing value
    drops that measure for the row (its weight is renormalised)."""
    for r in rows:
        r["score"], r["_w"] = 0.0, 0.0
    for k, w in specs:
        v = sorted((r for r in rows if r.get(k) is not None), key=lambda r: r[k])
        if len(v) < 2:
            continue
        for i, r in enumerate(v):
            r["score"] += w * i / (len(v) - 1)
            r["_w"] += w
    for r in rows:
        r["score"] = round(r["score"] / r["_w"] * 100, 1) if r["_w"] else 0.0
        del r["_w"]
    # stable: equal scores keep name order, so the answer doesn't flicker
    return sorted(rows, key=lambda r: (-r["score"], r["name"]))


def group_rows(stocks, key, min_n, base, pct=None, specs=GROUP_SPECS):
    by = {}
    for m in stocks:
        k = m.get(key)
        if k and not m.get("nw"):                # new listings: too little history
            by.setdefault(k, []).append(m)
    rows = []
    for name, lst in by.items():
        if len(lst) < min_n:
            continue
        p = (pct or {}).get(name)
        rows.append({"name": name, "list": lst, "pct": p * 100 if p is not None else None,
                     **group_stats(lst, base)})
    return rank_score(rows, specs)


def market_regime(stocks, market, osc, fii_month):
    """Index trend + breadth + participation + flows, as a 7-point checklist."""
    mk = market or {}
    e = mk.get("ema") or []

    def flag(i):
        return None if len(e) <= i or e[i] == -1 else e[i] == 1
    o = osc[-1] if osc else None
    o5 = osc[-6] if len(osc or []) > 5 else None
    e50 = [m for m in stocks if has_ema(m, 50)]
    p50 = share(e50, lambda m: above(m, 50))
    checks = [
        {"t": "NIFTY 500 above its 20-day EMA", "ok": flag(0),
         "v": f"1W {sgn(mk['w1'])}" if mk.get("w1") is not None else ""},
        {"t": "NIFTY 500 above its 50-day EMA", "ok": flag(1),
         "v": f"1M {sgn(mk['m1'])}" if mk.get("m1") is not None else ""},
        {"t": "NIFTY 500 above its 200-day EMA", "ok": flag(4),
         "v": f"{mk['off_high']:.1f}% off its high" if mk.get("off_high") is not None else ""},
        {"t": "Breadth oscillator above zero", "ok": None if o is None else o > 0,
         "v": "" if o is None else f"{o:.1f}"},
        {"t": "Breadth rising over the last week",
         "ok": None if o is None or o5 is None else o > o5,
         "v": "" if o5 is None else f"{o5:.1f} → {o:.1f}"},
        {"t": "Half the stocks above their 50-day EMA", "ok": None if p50 is None else p50 >= 50,
         "v": "" if p50 is None else f"{p50:.0f}%"},
        {"t": "FIIs net buyers this month", "ok": None if fii_month is None else fii_month > 0,
         "v": "" if fii_month is None else crore(fii_month)},
    ]
    known = [c for c in checks if c["ok"] is not None]
    passed = len([c for c in known if c["ok"]])
    frac = passed / len(known) if known else 0
    level = "on" if frac >= 0.8 else "mixed" if frac >= 0.5 else "off"
    return {"level": level, "pass": passed, "known": len(known), "checks": checks,
            "p50": None if p50 is None else round(p50, 1)}


def _liquid(m):
    return ((m.get("tv") or 0) >= SWING["minTurnoverCr"]
            and (m.get("l") or 0) >= SWING["minPrice"])


def _range_ok(m, lo=SWING["minAdr"], hi=SWING["maxAdr"]):
    return m.get("a") is not None and lo <= m["a"] <= hi


def above_all(m):
    """Above every EMA it has history for (a young stock has only some)."""
    e = m.get("e") or []
    return all(x == 1 for x in e if x != -1)


def ipo_base(m):
    """The IPO-base screen (see IPO)."""
    i, R = m.get("ipo"), IPO
    return bool(i) and R["minAge"] <= i["n"] <= R["maxAge"] \
        and i.get("p") is not None and (m.get("l") or 0) > i["p"] \
        and i.get("x") is not None and i["x"] > 0 \
        and above_all(m) and m.get("h") is not None and m["h"] <= R["maxOffHigh"] \
        and _range_ok(m, R["minAdr"], R["maxAdr"]) and _liquid(m) \
        and (m.get("w1") is None or m["w1"] <= R["maxWeek"])


def weekly_trend(m):
    """The weekly-trend screen (see WEEKLY)."""
    w, R = m.get("wk") or {}, WEEKLY
    return w.get("d") is not None and w["d"] > 0 and w.get("u") == 1 \
        and (m.get("rr") or 0) >= R["minRS"] and _range_ok(m, R["minAdr"], R["maxAdr"]) \
        and _liquid(m) and (m.get("w1") is None or m["w1"] <= R["maxWeek"]) \
        and (m.get("m1") is None or m["m1"] <= R["maxMonth"])


def htf_dry(m):
    """Volume in the flag under 70% of the pole's — the HTF's best tell."""
    d = (m.get("htf") or {}).get("dry")
    return d is not None and d < HTF_RULES["dry"]


def near_10w(m):
    """Within WEEKLY["near"]% above the 10-week SMA — the low-risk entry."""
    d = (m.get("wk") or {}).get("d")
    return d is not None and 0 < d <= WEEKLY["near"]


def tight(m):
    """10-session range within 2.5 average daily ranges: a quiet base."""
    return m.get("tt") is not None and bool(m.get("a")) and m["tt"] <= 2.5 * m["a"]


def drying(m):
    return m.get("vd") is not None and m["vd"] < 0.85


def surge(m):
    return m.get("vr") is not None and m["vr"] >= 1.5


def deliv_high(m):
    return m.get("dla") is not None and m["dla"] >= 50


def deliv_weak(m):
    return m.get("dl") is not None and bool(m.get("dla")) and m["dl"] / m["dla"] < 0.8


def setup_bonus(m):
    """Rank boost from the backtest (250 sessions, 20-day excess vs NIFTY 500):
    tight bases +2.4% vs +1.6% for all candidates, drying volume +1.9%, while
    buying the close of a volume-surge day lagged (+1.2%) — that's chasing."""
    return 8 * tight(m) + 4 * drying(m) - 4 * surge(m)


def _strip(row):
    """Group row without its member list, rounded for the JSON."""
    out = {k: (round(v, 2) if isinstance(v, float) else v)
           for k, v in row.items() if k != "list"}
    return out


def analyse(stocks, market=None, osc=None, fii_month=None, group_pct=None):
    """Everything the Focus and Swing pages show, from one set of rules."""
    group_pct = group_pct or {}
    live = [m for m in stocks if not m.get("nw")]
    base = group_stats(live)
    sectors = group_rows(stocks, "sector", 5, base, group_pct.get("sector"))
    industries = group_rows(stocks, "industry", 4, base, group_pct.get("industry"))
    caps = group_rows([m for m in stocks if m.get("cap") in CAP_ORDER], "cap", 1, base,
                      specs=CAP_SPECS)
    for r in industries:                    # its sector = where most of its stocks are
        cnt = {}
        for m in r["list"]:
            if m.get("sector"):
                cnt[m["sector"]] = cnt.get(m["sector"], 0) + 1
        r["sector"] = max(sorted(cnt), key=cnt.get) if cnt else ""
    reg = market_regime(stocks, market, osc or [], fii_month)

    strong = [r for r in sectors if r["quad"] in ("Leading", "Improving")]
    focus = (strong or sectors)[:3]
    turning = sorted((r for r in sectors if r["quad"] == "Improving" and r not in focus
                      and (r["rel1"] or 0) >= 1), key=lambda r: -r["rel1"])[:2]
    avoid = [r for r in reversed(sectors) if r["quad"] in ("Lagging", "Weakening")][:3]
    for r in sectors:
        r["inds"] = [i["name"] for i in industries if i["sector"] == r["name"]][:2]
        r["leaders"] = [m["s"] for m in sorted(
            (m for m in r["list"] if (m.get("rr") or 0) >= 80 and above(m, 50)
             and (m.get("tv") or 0) >= SWING["minTurnoverCr"]),
            key=lambda m: (-m["rr"], m["s"]))][:4]

    lead_ind = [r for r in industries if r["quad"] in ("Leading", "Improving")][:8]
    hot_ind = {r["name"] for r in lead_ind}
    hot_sec = {r["name"] for r in strong[:3]}

    def in_lead(m):
        return m.get("industry") in hot_ind or m.get("sector") in hot_sec

    def full_trend(m):
        return all(above(m, p) for p in (20, 50, 100, 150, 200))

    S = SWING
    brk = [m for m in live if (m.get("rr") or 0) >= S["minRS"] and full_trend(m)
           and m.get("b") == 1 and m.get("h") is not None and m["h"] <= S["maxOffHigh"]
           and _range_ok(m) and _liquid(m)
           and (m.get("w1") is None or m["w1"] <= S["maxWeek"])
           and (m.get("m1") is None or m["m1"] <= S["maxMonth"])]
    # delivery (breakouts only — no consistent effect on pullbacks): steady
    # 50%+ delivery +1.9% vs +1.6% for all, a weak-delivery day +0.7%
    brk.sort(key=lambda m: -(m["rr"] + (10 if in_lead(m) else 0) - 1.5 * m["h"] + setup_bonus(m)
                             + 3 * deliv_high(m) - 4 * deliv_weak(m)))
    pb = [m for m in live if (m.get("rr") or 0) >= S["pbMinRS"] and above(m, 50) and above(m, 200)
          and has_ema(m, 20) and not above(m, 20) and m.get("h") is not None
          and S["pbOffHigh"][0] <= m["h"] <= S["pbOffHigh"][1] and _range_ok(m) and _liquid(m)]
    pb.sort(key=lambda m: -(m["rr"] + (10 if in_lead(m) else 0) - 0.5 * m["h"] + setup_bonus(m)))
    # IPO bases: tight and near the high first; strength since listing next
    in_brk = {m["s"] for m in brk}
    ipo = [m for m in stocks if ipo_base(m) and m["s"] not in in_brk]
    ipo.sort(key=lambda m: (-(10 * in_lead(m) - 1.5 * m["h"] + setup_bonus(m)
                              + 0.2 * min(m["ipo"]["x"], 100)), m["s"]))
    wkl = sorted((m for m in live if weekly_trend(m)), key=lambda m: (-m["rr"], m["s"]))
    # HTF: drying volume first, then nearest the pivot (fresh breakouts lead)
    htf = sorted((m for m in stocks if m.get("htf") and _liquid(m) and not m.get("nw")),
                 key=lambda m: (not htf_dry(m), -m["htf"]["dist"], m["s"]))
    ext = [m for m in live if (m.get("rr") or 0) >= S["minRS"] and _liquid(m)
           and ((m.get("w1") or 0) > 20 or (m.get("m1") or 0) > S["maxMonth"])]
    ext.sort(key=lambda m: -(m.get("w1") or 0))

    return {
        "regime": reg,
        "base": {"m1": base["m1"], "m3": base["m3"]},
        "sectors": [_strip(r) for r in sectors],
        "industries": [_strip(r) for r in industries],
        "caps": [_strip(r) for r in caps],
        "focus": [r["name"] for r in focus],
        "turning": [r["name"] for r in turning],
        "avoid": [r["name"] for r in avoid],
        "cap": caps[0]["name"] if caps else None,
        "lead_ind": [r["name"] for r in lead_ind],
        "hot": sorted(hot_ind | hot_sec),
        "breakouts": [m["s"] for m in brk],
        "pullbacks": [m["s"] for m in pb],
        "extended": [m["s"] for m in ext][:N_EXTENDED],
        "ipos": [m["s"] for m in ipo],
        "weekly": [m["s"] for m in wkl],
        "htf": [m["s"] for m in htf],
        "rules": {k: list(v) if isinstance(v, tuple) else v for k, v in SWING.items()},
        "ipo_rules": dict(IPO),
        "weekly_rules": dict(WEEKLY),
        "htf_rules": dict(HTF_RULES),
        "tags": {m["s"]: [t for t, f in (("tight", tight), ("dry", drying), ("surge", surge),
                                         ("dhi", deliv_high), ("dlo", deliv_weak), ("near10", near_10w), ("vdry", htf_dry)) if f(m)]
                 for m in brk[:N_BREAKOUTS] + pb[:N_PULLBACKS] + ipo[:N_IPOS] + wkl[:N_WEEKLY]
                 + htf[:N_HTF]},
    }


def stocks_from_levels(levels):
    """rs_data.json levels → one record per stock with its group names."""
    by_key = {lv["key"]: lv for lv in levels}
    stocks = {}
    for g in by_key.get("macro", {}).get("groups", []):
        for m in g["members"]:
            stocks[m["s"]] = {**m, "macro": g["name"]}
    for key in ("sector", "industry", "basic"):
        for g in by_key.get(key, {}).get("groups", []):
            for m in g["members"]:
                if m["s"] in stocks:
                    stocks[m["s"]][key] = g["name"]
    pct = {key: {g["name"]: g.get("pct") for g in by_key.get(key, {}).get("groups", [])}
           for key in ("sector", "industry")}
    return list(stocks.values()), pct


def decide_from_rs_data(data):
    """analyse() on a finished rs_data.json dict."""
    stocks, pct = stocks_from_levels(data.get("levels", []))
    brd = data.get("breadth") or {}
    months = (data.get("flows") or {}).get("months") or []
    asof = (data.get("meta") or {}).get("window_dates", [None])[-1]
    fii = None
    if months and asof and months[-1]["m"] == asof[:7]:
        fii = months[-1]["fii"]
    out = analyse(stocks, brd.get("market"), brd.get("osc"), fii, pct)
    out["asof"] = asof
    return out
