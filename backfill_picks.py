#!/usr/bin/env python3
"""Rebuild the Focus / Swing picks for past sessions → nse_picks.jsonl.

Each past session gets the stock fields the live build computes (EMA flags,
RS rating, 52-week-high distance, ADR, liquidity, returns, RS line vs its
EMA21) from the cached prices as they stood that evening, and the same
rs_engine.decide rules pick from them.  Lines are marked "bt": true and never
replace a live pick.

Thinly traded stocks are left out per day and IPOs (nse_ipos.csv) get
their IPO-base fields, as in the live build.

Known differences from a live pick, all small: today's classification and
size lists are used for the past, the group RS_STS% measure is left out of
the sector score, FII flows only count where daily figures exist, and
stocks that have since been archived are missing.

    python backfill_picks.py              # last 250 sessions
    python backfill_picks.py --sessions 60
"""
import argparse
import json
from bisect import bisect_right

import build_rs as B
from rs_engine import decide, flows, nse_archive, track
from rs_engine.config import ADR_PERIOD, CORP_ACTION_JUMP, EMA_PERIODS, ILLIQUID_TURNOVER_CR, WINDOW
from rs_engine.maths import index_trend, ipo_metrics


def _emas(vals, period):
    """EMA per index (SMA-seeded, as maths.ema_flags); None before `period`."""
    out = [None] * len(vals)
    if len(vals) < period:
        return out
    k = 2.0 / (period + 1)
    e = sum(vals[:period]) / period
    out[period - 1] = e
    for i in range(period, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


class Stock:
    """One stock's history, pre-indexed so any as-of date is a lookup."""

    def __init__(self, u, ser, hi, lo, vol, bench, ipo=None, raw_first=None):
        self.u = u
        self.ipo = ipo
        self.raw_first = raw_first
        self.ds = sorted(ser)
        self.c = [ser[d] for d in self.ds]
        self.hi, self.lo, self.vol = hi, lo, vol
        self.bench = bench
        self.ema = {p: _emas(self.c, p) for p in EMA_PERIODS}
        common = [i for i, d in enumerate(self.ds) if d in bench]
        self.rs_i = common
        ratios = [self.c[i] / bench[self.ds[i]] for i in common]
        self.rs_ema = _emas(ratios, 21)
        self.ratios = ratios
        # index of the last corporate-action jump at or before each bar
        self.brk = []
        last = None
        for i in range(len(self.c)):
            if i and self.c[i - 1] > 0:
                r = self.c[i] / self.c[i - 1]
                if r > 1 + CORP_ACTION_JUMP or r < 1 - CORP_ACTION_JUMP:
                    last = i
            self.brk.append(last)

    def ret(self, i, start):
        """% from the close on or before market session `start` to bar i
        (maths.period_return with a calendar)."""
        if start is None:
            return None
        j = bisect_right(self.ds, start) - 1
        if j < 0 or j >= i:
            return None
        b = self.brk[i]
        if b is not None and b > j:
            return None
        return (self.c[i] / self.c[j] - 1) * 100

    def record(self, day, window_start, cap, cal=None, k=None):
        """Metrics as of `day`; `cal[:k + 1]` = the market sessions up to it."""
        def sess(n):
            if cal is None:
                return self.ds[i - n] if i - n >= 0 else None
            return cal[k - n] if k - n >= 0 else None
        i = bisect_right(self.ds, day) - 1
        if i < 1 or self.ds[i] != day:
            return None                              # no bar that day
        b = self.brk[i]
        recent_break = b is not None and b > i - 252
        price = self.c[i]
        e = []
        for p in EMA_PERIODS:
            v = self.ema[p][i]
            e.append(-1 if v is None or recent_break else (1 if price >= v else 0))
        # RS line vs its EMA21
        j = bisect_right(self.rs_i, i) - 1
        rse = -1
        if j >= 20 and self.rs_i[j] == i and self.rs_ema[j] is not None and not recent_break:
            rse = 1 if self.ratios[j] >= self.rs_ema[j] else 0
        lo_day = sess(251) or self.ds[0]
        since = max(self.ds[b], lo_day) if recent_break else lo_day
        hs = [self.hi[d] for d in self.ds[max(0, i - 400):i + 1]
              if d in self.hi and d >= since]
        h = (max(hs) - price) / max(hs) * 100 if hs and max(hs) > 0 else None
        ratios = []
        for d in reversed(self.ds[max(0, i - 60):i + 1]):
            if d < since:
                break
            hv, lv = self.hi.get(d), self.lo.get(d)
            if hv and lv and hv > lv:
                ratios.append(hv / lv)
                if len(ratios) == ADR_PERIOD:
                    break
        a = 100 * (sum(ratios) / len(ratios) - 1) if len(ratios) >= ADR_PERIOD // 2 else None
        vdays = [d for d in self.ds[max(0, i - 19):i + 1] if d in self.vol]
        tv = (sum(self.c[self.ds.index(d, max(0, i - 19))] * self.vol[d] for d in vdays)
              / len(vdays) / 1e7) if len(vdays) >= 10 else None
        # breakout readiness (as maths.setup_metrics)
        vr = vd = tt = None
        vi = [d for d in self.ds[max(0, i - 59):i + 1] if d in self.vol and d >= since]
        if len(vi) >= 31:
            v = [self.vol[d] for d in vi]
            prior = v[-51:-1]
            avg = sum(prior) / len(prior)
            vr = round(v[-1] / avg, 2) if avg > 0 else None
            if len(vi) >= 40:
                base = v[-60:-10]
                bb = sum(base) / len(base)
                vd = round(sum(v[-10:]) / 10 / bb, 2) if bb > 0 else None
        hd = [d for d in self.ds[max(0, i - 9):i + 1] if d in self.hi and d in self.lo and d >= since]
        if len(hd) == 10:
            hi_v, lo_v = max(self.hi[d] for d in hd), min(self.lo[d] for d in hd)
            if price > 0 and hi_v >= lo_v > 0:
                tt = round((hi_v - lo_v) / price * 100, 2)
        nw = None
        if self.ds[0] > window_start:
            nw = len([d for d in self.ds[:i + 1] if d >= window_start])
        # thinly traded that day (maths.is_illiquid): skipped a session of the
        # RS window and < ₹1 cr/day — left out, as the live build does
        if cal is not None and (tv is None or tv < ILLIQUID_TURNOVER_CR):
            first = self.ds[0]
            if any(d >= first and not self.vol.get(d) for d in cal[max(0, k - WINDOW + 1):k + 1]):
                return None
        ipo = None
        if self.ipo and cal is not None:
            ipo = ipo_metrics(dict(zip(self.ds[:i + 1], self.c[:i + 1])), self.ipo,
                              cal[:k + 1], self.bench, raw_first=self.raw_first)
        return {"s": self.u["sym"], "n": self.u["name"], "sector": self.u["sector"],
                "industry": self.u["industry"], "cap": cap,
                "e": e, "b": rse, "h": h, "a": a, "l": price, "nw": nw,
                "m1": self.ret(i, sess(20)), "m3": self.ret(i, sess(63)), "w1": self.ret(i, sess(5)),
                "tv": tv, "vr": vr, "vd": vd, "tt": tt, "ipo": ipo, "_i": i}

    def rr_score(self, i):
        if i <= 63:
            return None
        r = [self.c[i] / self.c[i - n] - 1 if i - n >= 0 else None for n in (63, 126, 189, 252)]
        r = [x if x is not None else r[0] for x in r]
        return 2 * r[0] + r[1] + r[2] + r[3]


def iter_days(sessions):
    """Yield (day, stock records, decisions) for each of the last `sessions`
    sessions with enough history, as the live build would have seen them."""
    cache = B.load_json_cache(B.PRICE_CACHE)
    highs = B.load_json_cache(B.HIGH_CACHE)
    lows = B.load_json_cache(B.LOW_CACHE)
    vols = B.load_json_cache(B.VOLUME_CACHE)
    bench = cache.get("__BENCH__", {})
    universe = B.read_universe()
    caps = B.read_cap_classes()
    with open(B.RS_DATA_JSON, encoding="utf-8") as f:
        brd = json.load(f).get("breadth") or {}
    osc_by_day = dict(zip(brd.get("dates", []), brd.get("osc", [])))
    daily_flows = flows.read_csv(flows.DAILY, "date")
    arc = B.load_json_cache(nse_archive.ARCHIVE)
    ipo_list = B.read_ipos()

    stocks = [Stock(u, cache[u["sym"]], highs.get(u["sym"], {}), lows.get(u["sym"], {}),
                    vols.get(u["sym"], {}), bench, ipo_list.get(u["sym"]),
                    nse_archive.raw_close(arc, u["sym"], min(cache[u["sym"]])))
              for u in universe if cache.get(u["sym"])]
    bdates = sorted(bench)
    for day in bdates[-sessions:]:
        k = bdates.index(day)
        if k < WINDOW + 252:
            continue                                  # too little history before it
        window_start = bdates[k - WINDOW + 1]
        recs, scores = [], {}
        for st in stocks:
            n_sess = bisect_right(st.ds, day)
            r = st.record(day, window_start, B.cap_class(st.u["sym"], caps, n_sess), bdates, k)
            if r:
                r.update(nse_archive.delivery_metrics(arc.get(r["s"]), day))
                recs.append(r)
                sc = st.rr_score(r["_i"])
                if sc is not None:
                    scores[r["s"]] = sc
        order = sorted(scores, key=scores.get)
        n = len(order)
        rr = {s: max(1, min(99, round(100 * (i + 1) / n))) for i, s in enumerate(order)}
        for r in recs:
            r["rr"] = rr.get(r["s"])
            del r["_i"]
        mk = index_trend({d: v for d, v in bench.items() if d <= day})
        osc = [osc_by_day[d] for d in sorted(osc_by_day) if d <= day]
        month_days = [d for d in bdates if d[:7] == day[:7] and d <= day]
        fii = (sum(daily_flows[d]["fii_net"] for d in month_days)
               if month_days and all(d in daily_flows for d in month_days) else None)
        dec = decide.analyse(recs, mk, osc, fii)
        dec["asof"] = day
        yield day, recs, dec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=250)
    args = ap.parse_args()
    done = total = added = 0
    for _day, _recs, dec in iter_days(args.sessions):
        total += 1
        rec = track.pick_record(dec, backtest=True)
        if track.save_pick(rec):
            done += 1
        elif track.add_missing(rec):
            added += 1
    print(f"backfilled {done} of {total} sessions → {track.PICKS}"
          + (f"; added new lists to {added} live session(s)" if added else ""))


if __name__ == "__main__":
    main()
