#!/usr/bin/env python3
"""Update the FII / DII cash-market history (nse_fii_dii_*.csv).

Best effort, like the listing refresh: if a source is unreachable the files
keep what they have and the build still runs.  See rs_engine/flows.py.
"""
import sys

import requests

from refresh_classification import NSE_UA
from rs_engine import flows


def fetch_kotak():
    try:
        r = requests.get(flows.KOTAK_URL, timeout=30,
                         headers={"User-Agent": NSE_UA, "Accept": "text/html"})
        if r.status_code == 200:
            return flows.parse_kotak(r.text)
    except requests.RequestException:
        pass
    return {}, {}


def fetch_nse():
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": NSE_UA, "Accept": "application/json",
                          "Referer": "https://www.nseindia.com/reports/fii-dii"})
        r = s.get(flows.NSE_URL, timeout=20)
        if r.status_code == 200:
            return flows.parse_nse(r.json())
    except (requests.RequestException, ValueError):
        pass
    return {}


def main():
    km, kd = fetch_kotak()
    nd = fetch_nse()
    print(f"FII/DII: Kotak {len(km)} months / {len(kd)} days, NSE {sorted(nd) or 'unavailable'}")
    # NSE's official day must agree with the republished one when both exist
    for d in set(kd) & set(nd):
        if abs(kd[d]["fii_net"] - nd[d]["fii_net"]) > 1 or abs(kd[d]["dii_net"] - nd[d]["dii_net"]) > 1:
            print(f"  note: {d} differs between Kotak and NSE — keeping NSE's figures")
    old_m = flows.read_csv(flows.MONTHLY, "month")
    old_d = flows.read_csv(flows.DAILY, "date")
    months, days = flows.merge(old_m, old_d, km, kd, nd)
    if not months:
        print("FII/DII: no data available — files unchanged.")
        return 0          # best effort: never blocks the build that follows
    if months != old_m:
        flows.write_csv(flows.MONTHLY, "month", months)
    if days != old_d:
        flows.write_csv(flows.DAILY, "date", days)
    last = max(months)
    print(f"FII/DII: {len(months)} months ({min(months)} → {last}), "
          f"{last}: FII {months[last]['fii_net']:+,.0f} cr, DII {months[last]['dii_net']:+,.0f} cr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
