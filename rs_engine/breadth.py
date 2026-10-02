"""Market-breadth oscillators (McClellan-style, total + per macro) and
Zanger-style divergence detection."""

from collections import defaultdict


def compute_breadth(universe, cache, covered_dates):
    """McClellan-style breadth oscillator from daily advancers vs decliners.

      RANA[d]  = (advances - declines) / (advances + declines) * 1000
      osc[d]   = EMA19(RANA) - EMA39(RANA)
    Oscillates around zero; extreme highs/lows precede reversals.
    Returns (dates, osc_values, n_stocks) with the EMA warm-up trimmed.
    """
    series = [cache[u["sym"]] for u in universe if cache.get(u["sym"])]
    rana, rdates = [], []
    for i in range(1, len(covered_dates)):
        prev, cur = covered_dates[i - 1], covered_dates[i]
        adv = dec = 0
        for s in series:
            a = s.get(prev)
            b = s.get(cur)
            if a is None or b is None:
                continue
            if b > a:
                adv += 1
            elif b < a:
                dec += 1
        # neutral 0.0 keeps the series 1:1 with covered_dates (no skips)
        rana.append((adv - dec) / (adv + dec) * 1000.0 if adv + dec else 0.0)
        rdates.append(cur)
    if len(rana) < 2:
        return [], [], len(series)

    def ema(vals, span):
        k = 2.0 / (span + 1)
        out = []
        e = vals[0]
        for v in vals:
            e = v * k + e * (1 - k)
            out.append(e)
        return out

    e19, e39 = ema(rana, 19), ema(rana, 39)
    osc = [a - b for a, b in zip(e19, e39)]
    warm = min(39, max(0, len(osc) // 4))   # drop EMA warm-up
    return rdates[warm:], osc[warm:], len(series)


def compute_macro_breadth(universe, cache, covered_dates):
    """The same McClellan-style oscillator, computed per MACRO group — the
    Market Breadth page shows all 12 as a dashboard grid.  Shares the main
    breadth's covered_dates so every chart is aligned.  Returns a list of
    {"name", "dates", "osc", "latest"} sorted by name (macros with ≥ 5
    stocks; the warm-up trim matches compute_breadth)."""
    by_macro = defaultdict(list)
    for u in universe:
        ser = cache.get(u["sym"])
        if ser and u.get("macro"):
            by_macro[u["macro"]].append(ser)

    def ema(vals, span):
        k = 2.0 / (span + 1)
        out, e = [], vals[0]
        for v in vals:
            e = v * k + e * (1 - k)
            out.append(e)
        return out

    out = []
    for name, series in sorted(by_macro.items()):
        if len(series) < 5:
            continue
        rana, rdates = [], []
        for i in range(1, len(covered_dates)):
            prev, cur = covered_dates[i - 1], covered_dates[i]
            adv = dec = 0
            for s in series:
                a = s.get(prev)
                b = s.get(cur)
                if a is None or b is None:
                    continue
                if b > a:
                    adv += 1
                elif b < a:
                    dec += 1
            # neutral 0.0 keeps the series 1:1 with covered_dates (no skips)
            rana.append((adv - dec) / (adv + dec) * 1000.0 if adv + dec else 0.0)
            rdates.append(cur)
        if len(rana) < 2:
            continue
        e19, e39 = ema(rana, 19), ema(rana, 39)
        osc = [a - b for a, b in zip(e19, e39)]
        warm = min(39, max(0, len(osc) // 4))
        if len(osc) - warm < 10:
            continue
        out.append({"name": name, "dates": rdates[warm:], "osc": osc[warm:],
                    "latest": round(osc[-1], 2)})
    return out


# --------------------------------------------------------------------------- #
#  Phase 4: rotation RS-lines, IPO watch, snapshots, divergence, daily report
# --------------------------------------------------------------------------- #


def detect_breadth_divergence(bench, bdates, bosc):
    """Zanger-style divergence: the index closes near its 26-day high while the
    breadth oscillator prints a LOWER high than at the previous index-peak
    (bearish), or the mirror image (bullish)."""
    if len(bosc) < 26 or len(bdates) != len(bosc):
        return {"state": "none"}
    idx = {d: i for i, d in enumerate(bdates)}
    closes = {d: v for d, v in bench.items() if d in idx}
    if len(closes) < 26:
        return {"state": "none"}
    days = sorted(closes)[-26:]
    hi = max(closes[d] for d in days)
    lo = min(closes[d] for d in days)
    last = days[-1]
    i_last = idx[last]
    if closes[last] >= 0.99 * hi:
        # at highs — find the previous near-high date inside the window
        for d in reversed(days[:-1]):
            if closes[d] >= 0.99 * hi:
                if bosc[i_last] < bosc[idx[d]]:
                    return {"state": "bearish",
                            "note": f"index at 26-day highs but breadth "
                                    f"({bosc[i_last]:+.1f}) below its level at "
                                    f"the previous peak ({bosc[idx[d]]:+.1f}, {d})"}
                break
    if closes[last] <= 1.01 * lo:
        for d in reversed(days[:-1]):
            if closes[d] <= 1.01 * lo:
                if bosc[i_last] > bosc[idx[d]]:
                    return {"state": "bullish",
                            "note": f"index at 26-day lows but breadth "
                                    f"({bosc[i_last]:+.1f}) above its level at "
                                    f"the previous trough ({bosc[idx[d]]:+.1f}, {d})"}
                break
    return {"state": "none"}


