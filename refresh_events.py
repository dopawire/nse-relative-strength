#!/usr/bin/env python3
"""Update nse_events.csv with NSE's board-meeting calendar for the next
30 days.  Best effort: keeps the file on failure.  See rs_engine/events.py."""
import datetime as dt
import sys

import requests

from refresh_classification import NSE_UA
from rs_engine import events
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
        return 0
    new = events.parse_nse(rows)
    ev = events.merge(events.read_events(), new, today.isoformat())
    events.write_events(ev)
    res = sum(1 for p in new.values() if events.is_results(p))
    print(f"Events: {len(new)} upcoming board meetings ({res} results) → {events.EVENTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
