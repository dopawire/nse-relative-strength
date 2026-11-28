"""Mainboard IPOs from NSE's past-issues list → nse_ipos.csv.

A stock's first NSE session is not enough to call it an IPO: NSE also
lists old BSE companies directly (≈160 of them on 17/18-Aug-2026) and SME
stocks migrate up — neither is a fresh IPO.  NSE's own list of public issues
(securityType "Equity" = mainboard) gives the real ones with their listing
day and issue price.

    nse_ipos.csv   symbol,listed,price      (ISO date; issue price in ₹)
"""
import csv
import datetime as dt
import os

from rs_engine.config import data_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IPOS = data_path("nse_ipos.csv")
NSE_URL = "https://www.nseindia.com/api/public-past-issues"


def _date(s):
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime((s or "").strip().title(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _price(s):
    try:
        v = float(str(s).replace(",", "").replace("Rs.", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_nse(rows):
    """NSE public-past-issues JSON → {SYMBOL: {"listed": iso, "price": float|None}}
    for mainboard equity IPOs that have listed."""
    out = {}
    for r in rows or []:
        if (r.get("securityType") or "").strip() != "Equity":
            continue
        sym = (r.get("symbol") or "").strip().upper()
        day = _date(r.get("listingDate"))
        if not sym or not day:
            continue
        out[sym] = {"listed": day, "price": _price(r.get("issuePrice"))}
    return out


def read(path=None):
    path = path or IPOS
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["symbol"]: {"listed": r["listed"], "price": _price(r.get("price"))}
                for r in csv.DictReader(f) if r.get("symbol") and r.get("listed")}


def write(ipos, path=None):
    path = path or IPOS
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "listed", "price"])
        for s in sorted(ipos, key=lambda s: (ipos[s]["listed"], s)):
            p = ipos[s]["price"]
            w.writerow([s, ipos[s]["listed"], "" if p is None else f"{p:g}"])
    os.replace(tmp, path)


def merge(old, new):
    """New rows win; old ones are kept (NSE's list only covers a few years)."""
    return {**old, **new}
