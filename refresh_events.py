#!/usr/bin/env python3
"""Update nse_events.csv with NSE's board-meeting calendar for the next
30 days, and nse_ipos.csv with NSE's list of mainboard IPOs.  Best effort:
keeps the files on failure.  See rs_engine/events.py and rs_engine/ipos.py."""
import datetime as dt
import sys

import requests

from refresh_classification import NSE_UA
from rs_engine import events, ipos
from rs_engine.config import IST


def main():
    today = dt.datetime.now(IST).date()
    a, b = today.strftime("%d-%m-%Y"), (today + dt.timedelta(days=30)).strftime("%d-%m-%Y")
    s = requests.Session()
    s.headers.update({"User-Agent": NSE_UA, "Accept": "application/json",
                      "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings"})
    rows, ok = [], 0
    for url in events.NSE_URLS:           # board meetings + event calendar
        try:
            r = s.get(url.format(a=a, b=b), timeout=30)
            got = r.json() if r.status_code == 200 else None
        except (requests.RequestException, ValueError):
            got = None
        if isinstance(got, list):
            rows += got
            ok += 1
    if not ok:
        print("NSE event calendar: unavailable — nse_events.csv unchanged.")
    else:
        new = events.parse_nse(rows)
        ev = events.merge(events.read_events(), new, today.isoformat())
        events.write_events(ev)
        res = sum(1 for p in new.values() if events.is_results(p))
        print(f"Events: {len(new)} upcoming board meetings ({res} results) → {events.EVENTS}")
    refresh_ipos(s)
    return 0


def refresh_ipos(s):
    """NSE's past public issues → nse_ipos.csv (mainboard IPOs + issue price)."""
    try:
        r = s.get(ipos.NSE_URL, timeout=30,
                  headers={"Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"})
        got = r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        got = None
    new = ipos.parse_nse(got) if isinstance(got, list) else {}
    if not new:
        print("NSE IPO list: unavailable — nse_ipos.csv unchanged.")
        return
    allx = ipos.merge(ipos.read(), new)
    ipos.write(allx)
    print(f"IPOs: {len(new)} mainboard issues from NSE ({len(allx)} kept) → {ipos.IPOS}")


if __name__ == "__main__":
    sys.exit(main())
