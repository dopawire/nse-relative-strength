"""Upcoming corporate events (results, dividends, splits…) from NSE's board-
meeting calendar → nse_events.csv.  The build tags each stock with its next
event so the Swing page can warn before a position is held through results.
"""
import csv
import datetime as dt
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(ROOT, "nse_events.csv")
NSE_URLS = ("https://www.nseindia.com/api/corporate-board-meetings"
            "?index=equities&from_date={a}&to_date={b}",
            "https://www.nseindia.com/api/event-calendar"
            "?index=equities&from_date={a}&to_date={b}")
AHEAD_DAYS = 14          # calendar days a stock is flagged ahead of its event


def short_purpose(p):
    """'Financial Results/Dividend/Other business matters' → 'Results, Dividend'."""
    p = p or ""
    out = []
    for key, word in (("result", "Results"), ("dividend", "Dividend"), ("bonus", "Bonus"),
                      ("split", "Split"), ("buyback", "Buyback"), ("fund raising", "Fund raising"),
                      ("rights", "Rights"), ("merger", "Merger"), ("amalgamation", "Merger"),
                      ("demerger", "Demerger"), ("scheme of arrangement", "Scheme")):
        if key in p.lower() and word not in out:
            out.append(word)
    return ", ".join(out) or "Board meeting"


def parse_nse(rows):
    """API rows → {(symbol, YYYY-MM-DD): purpose}."""
    out = {}
    for x in rows or []:
        sym = (x.get("bm_symbol") or x.get("symbol") or "").strip().upper()
        try:
            d = dt.datetime.strptime(x.get("bm_date") or x.get("date"), "%d-%b-%Y").date()
        except (TypeError, ValueError):
            continue
        if sym:
            # one stock can have several rows for a day ("Board Meeting
            # Intimation" + "Financial Results"): merge what they say
            k = (sym, d.isoformat())
            words = [w for w in (out.get(k, "").split(", ") + short_purpose(
                x.get("bm_purpose") or x.get("purpose")).split(", ")) if w]
            specific = [w for w in dict.fromkeys(words) if w != "Board meeting"]
            out[k] = ", ".join(specific) or "Board meeting"
    return out


def read_events(path=None):
    path = path or EVENTS
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["symbol"], r["date"]): r["purpose"] for r in csv.DictReader(f)}


def write_events(ev, path=None):
    path = path or EVENTS
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "date", "purpose"])
        for (s, d), p in sorted(ev.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            w.writerow([s, d, p])
    os.replace(tmp, path)


def merge(old, new, today):
    """Keep events from a week back on (recent results explain a gap move);
    the fresh fetch replaces everything from today on."""
    keep_from = (dt.date.fromisoformat(today) - dt.timedelta(days=7)).isoformat()
    out = {k: v for k, v in old.items() if keep_from <= k[1] < today}
    out.update({k: v for k, v in new.items() if k[1] >= keep_from})
    return out


def next_events(ev, asof, ahead=AHEAD_DAYS):
    """{symbol: "YYYY-MM-DD Purpose"} for the first event after `asof` (the
    last close) within `ahead` calendar days."""
    end = (dt.date.fromisoformat(asof) + dt.timedelta(days=ahead)).isoformat()
    out = {}
    for (s, d), p in sorted(ev.items(), key=lambda kv: kv[0][1]):
        if asof < d <= end and s not in out:
            out[s] = f"{d} {p}"
    return out


def is_results(tag):
    return bool(tag) and bool(re.search(r"\bResults\b", tag))
