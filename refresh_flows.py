#!/usr/bin/env python3
"""Update the FII / DII cash-market history (nse_fii_dii_*.csv).

Best effort, like the listing refresh: if a source is unreachable the files
keep what they have and the build still runs.  See rs_engine/flows.py.
"""
import argparse
import json
import os
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


def fetch_archive():
    try:
        r = requests.get(flows.ARCHIVE_URL, timeout=30,
                         headers={"User-Agent": NSE_UA, "Accept": "text/html"})
        if r.status_code == 200:
            return flows.parse_archive(r.text)
    except requests.RequestException:
        pass
    return {}


RS_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_data.json")


def patch_rs_data():
    """Swap the fresh flows into rs_data.json — the evening FII/DII numbers
    usually land after the price build, and a full rebuild isn't needed."""
    if not os.path.exists(RS_DATA):
        return False
    with open(RS_DATA, encoding="utf-8") as f:
        data = json.load(f)
    data["flows"] = flows.build_flows()
    tmp = RS_DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, RS_DATA)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-behind", action="store_true",
                    help="do nothing when the latest session is already recorded")
    ap.add_argument("--patch", action="store_true",
                    help="on new data, also update the flows in rs_data.json")
    ap.add_argument("--backfill", action="store_true",
                    help="also add older daily net figures from the stockezee archive")
    args = ap.parse_args()
    if args.if_behind:
        from rs_engine.config import latest_session
        have = max(flows.read_csv(flows.DAILY, "date") or {"": 0})
        if have >= latest_session():
            return 0
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
    if args.backfill:
        arc = fetch_archive()
        n = len(days)
        days = flows.backfill(days, arc)
        print(f"FII/DII: archive {len(arc)} days, {len(days) - n} added")
    if not months:
        print("FII/DII: no data available — files unchanged.")
        return 0          # best effort: never blocks the build that follows
    if months != old_m:
        flows.write_csv(flows.MONTHLY, "month", months)
    if days != old_d:
        flows.write_csv(flows.DAILY, "date", days)
    if args.patch and (months != old_m or days != old_d) and patch_rs_data():
        print("FII/DII: rs_data.json updated")
    last = max(months)
    print(f"FII/DII: {len(months)} months ({min(months)} → {last}), "
          f"{last}: FII {months[last]['fii_net']:+,.0f} cr, DII {months[last]['dii_net']:+,.0f} cr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
