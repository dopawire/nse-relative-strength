#!/usr/bin/env python3
"""
Auto-refresh the NSE 4-level industry classification for NEWLY-LISTED stocks,
with no manual browser work.

What it does:
  1. Downloads NSE's official equity list (EQUITY_L.csv) — reachable directly.
  2. Diffs it against nse_stock_master.csv -> the set of new symbols.
  3. Drives a headless (or visible) Chromium via Playwright to establish an
     Akamai-validated NSE session, then calls the site's own GetQuoteApi for
     each new symbol and reads secInfo -> macro / sector / industry / basic.
     (Plain requests/curl_cffi get 403 here; only a real browser session works.)
  4. Appends the new rows to nse_stock_master.csv.
  5. Merges NSE's published trading holidays into nse_holidays.csv.

Why a browser: NSE's GetQuoteApi sits behind Akamai Bot Manager, which needs a
JS-validated _abck cookie. Playwright runs that JS, so the fetch succeeds just
like it does in your own browser.

Setup (one time):
    pip install playwright
    playwright install chromium

Usage:
    python3 refresh_classification.py            # fetch + append new listings
    python3 refresh_classification.py --dry-run  # just list new symbols (no browser)
    python3 refresh_classification.py --headful  # show the browser window (most Akamai-proof)
"""

import os
import csv
import io
import sys
import time
import argparse
import datetime as dt

import requests

from rs_engine.config import CURRENT_MACROS, standard_name, standard_company

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(HERE, "nse_stock_master.csv")
CHANGES = os.path.join(HERE, "nse_symbol_changes.csv")   # old,new,isin,date
DELISTED = os.path.join(HERE, "nse_delisted.csv")        # archived master rows
HOLIDAYS = os.path.join(HERE, "nse_holidays.csv")
OVERRIDES = os.path.join(HERE, "nse_classification_overrides.csv")  # hand-checked fixes
LEVEL_FIELDS = ["macro", "sector", "industry", "basicIndustry"]
HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
EQUITY_L = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
FIELDS = ["symbol", "company", "series", "isin",
          "macro", "sector", "industry", "basicIndustry"]
NSE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
WARMUP_URL = "https://www.nseindia.com/get-quote/equity/DLF/DLF-Limited"

# Runs inside the validated NSE page. Tries marketType/series combos (N first,
# then G for call-auction/ESM stocks) until secInfo carries a classification.
FETCH_JS = r"""
async ([sym, series]) => {
  const B = "/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData";
  const tries = [["N", series], ["N", "EQ"], ["G", series], ["G", "BE"], ["G", "BZ"]];
  for (const [mt, se] of tries) {
    try {
      const u = B + "&marketType=" + mt + "&series=" + encodeURIComponent(se) +
                "&symbol=" + encodeURIComponent(sym);
      const r = await fetch(u, { headers: { accept: "*/*" }, credentials: "include" });
      if (r.ok) {
        const j = await r.json();
        const si = j && j.equityResponse && j.equityResponse[0] && j.equityResponse[0].secInfo;
        if (si && (si.macro || si.sector || si.basicIndustry)) return si;
      }
    } catch (e) { /* try next combo */ }
  }
  return null;
}
"""


def load_master_rows():
    if not os.path.exists(MASTER):
        sys.exit(f"{MASTER} not found.")
    with open(MASTER, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_equity_list():
    """Download NSE's official equity list (EQUITY_L.csv) via plain HTTP.
    Returns {symbol: row} or None on any non-200 (NSE geo-blocks many IPs —
    notably everything outside India returns 403)."""
    try:
        r = requests.get(EQUITY_L, headers={"User-Agent": NSE_UA}, timeout=30)
        if r.status_code != 200:
            print(f"NSE equity list: HTTP {r.status_code} (geo-blocked?)")
            return None
        return parse_equity_text(r.text)
    except requests.RequestException as e:
        print(f"NSE equity list: fetch error: {e}")
        return None


def fetch_equity_list_via_browser(page):
    """Fallback: fetch EQUITY_L.csv inside the Akamai-validated browser session
    (page must already be on a validated www.nseindia.com page)."""
    try:
        resp = page.goto(EQUITY_L, wait_until="domcontentloaded", timeout=60000)
        if resp and resp.status == 200:
            return parse_equity_text(resp.body().decode("utf-8-sig", "ignore"))
        print(f"NSE equity list via browser: HTTP {resp.status if resp else 'no-response'}")
    except Exception as e:
        print(f"NSE equity list via browser: {type(e).__name__}: {e}")
    return None


def parse_equity_text(text):
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        def g(k):
            return (row.get(k) or next((row[c] for c in row if c.strip() == k), "")).strip()
        sym = g("SYMBOL").upper()
        if sym:
            rows[sym] = {"symbol": sym, "company": g("NAME OF COMPANY"),
                         "series": g("SERIES") or "EQ", "isin": g("ISIN NUMBER")}
    return rows


def load_overrides():
    """{symbol: {macro, sector, industry, basicIndustry}} — manual fixes for
    stocks NSE still classifies under its retired scheme."""
    if not os.path.exists(OVERRIDES):
        return {}
    with open(OVERRIDES, newline="", encoding="utf-8") as f:
        return {r["symbol"].strip().upper(): {k: r[k].strip() for k in LEVEL_FIELDS}
                for r in csv.DictReader(f) if r.get("symbol")}


def is_classified(row):
    """Has a classification in NSE's CURRENT scheme (retired-scheme values
    such as MANUFACTURING / CONSUMER count as unclassified → re-fetched)."""
    return standard_name(row.get("macro", "")) in CURRENT_MACROS


def normalise(master):
    """Apply overrides and the standard spelling (classification + company
    name) to every row in place.  Returns how many rows changed."""
    overrides = load_overrides()
    changed = 0
    for r in master:
        new = dict(overrides.get(r["symbol"].upper()) or {
            k: standard_name(r.get(k, "")) for k in LEVEL_FIELDS})
        new["company"] = standard_company(r.get("company", ""))
        if any(r.get(k, "") != v for k, v in new.items()):
            r.update(new)
            changed += 1
    return changed


def sync_holidays():
    """Merge NSE's published cash-market trading holidays into
    nse_holidays.csv — adds, never removes.  Weekdays only: weekend entries
    (and Sunday Muhurat sessions) never affect a trading calendar.  NSE posts
    next year's list around December."""
    try:
        r = requests.get(HOLIDAY_API, timeout=20,
                         headers={"User-Agent": NSE_UA, "Accept": "application/json"})
        rows = r.json().get("CM") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        rows = None
    if not rows:
        print("NSE holiday list: unavailable — calendar unchanged.")
        return
    with open(HOLIDAYS, newline="", encoding="utf-8") as f:
        cal = {row["date"]: row["description"] for row in csv.DictReader(f)}
    added = []
    for x in rows:
        try:
            d = dt.datetime.strptime(x["tradingDate"], "%d-%b-%Y").date()
        except (KeyError, TypeError, ValueError):
            continue
        if d.weekday() < 5 and d.isoformat() not in cal:
            cal[d.isoformat()] = (x.get("description") or "").strip()
            added.append(d.isoformat())
    if not added:
        return
    tmp = HOLIDAYS + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "description"])
        w.writerows(sorted(cal.items()))
    os.replace(tmp, HOLIDAYS)
    print(f"Holiday calendar: added {added}")


def reconcile(master, live, dry_run=False):
    """Sync the master with NSE's list for symbols that left it.
      * renamed (same ISIN now trades under another symbol): the row moves to
        the new symbol, keeping its classification; a duplicate row already
        added for the new symbol is merged.  Logged to nse_symbol_changes.csv
        so build_rs.py can stitch the old price history onto the new symbol.
      * gone (no ISIN match): moved to nse_delisted.csv (archived, not lost).
    Skipped when the live list looks truncated.  Returns the new master."""
    if len(live) < 0.9 * len(master):
        print(f"NSE list has {len(live)} symbols vs master {len(master)} — "
              f"looks truncated, skipping rename/delisting reconcile.")
        return master
    by_isin = {v["isin"]: s for s, v in live.items() if v.get("isin")}
    by_sym = {r["symbol"].upper(): r for r in master}
    today = time.strftime("%Y-%m-%d")
    keep, renames, gone = [], [], []
    for r in master:
        sym = r["symbol"].upper()
        if sym in live:
            keep.append(r)
            continue
        new = by_isin.get(r.get("isin", ""))
        if new:
            renames.append({"old": sym, "new": new, "isin": r["isin"], "date": today})
            dup = by_sym.get(new)
            if dup is not None:
                if not is_classified(dup):
                    for k in ("macro", "sector", "industry", "basicIndustry"):
                        dup[k] = r.get(k, "")
                continue                       # the new symbol's row stays
            r.update(live[new])
            keep.append(r)
        else:
            gone.append(dict(r, delisted_on=today))
    if renames:
        print(f"Symbol changes: {', '.join(c['old'] + '→' + c['new'] for c in renames)}")
    if gone:
        print(f"No longer on NSE (archived to {os.path.basename(DELISTED)}): "
              f"{[g['symbol'] for g in gone]}")
    if dry_run:
        return master
    if renames or gone:
        _append_csv(CHANGES, ["old", "new", "isin", "date"], renames)
        _append_csv(DELISTED, FIELDS + ["delisted_on"], gone)
        save_master(keep)
    return keep


def _append_csv(path, fields, rows):
    if not rows:
        return
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerows(rows)


def add_stubs(master, live, new_syms):
    """Append unclassified rows (symbol/company/series/isin) for new listings.
    They join the universe straight away — so the build prices them and the
    New Listings tab shows them — and are re-tried as 'unfilled' next run."""
    for s in new_syms:
        stub = {k: "" for k in FIELDS}
        stub.update(live[s])
        master.append(stub)


def save_stubs_and_exit(master, live, new_syms, why):
    if new_syms:
        add_stubs(master, live, new_syms)
        save_master(master)
        print(f"{why} — added {len(new_syms)} new listing(s) WITHOUT a "
              f"classification (filled on a later run): {new_syms[:40]}")
    else:
        print(f"{why} — no new listings to add.")
    sys.exit(0)


def save_master(rows):
    normalise(rows)                  # every write uses the standard spelling
    tmp = MASTER + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, MASTER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list new symbols, no browser")
    ap.add_argument("--headful", action="store_true", help="show the browser window")
    ap.add_argument("--stubs-only", action="store_true",
                    help="append new listings without a classification (no browser)")
    args = ap.parse_args()

    master = load_master_rows()

    # Fast path: plain HTTP.  NSE geo-blocks many IPs (403) — then we fall back
    # to fetching the list inside the validated browser session below.
    live = fetch_equity_list()
    if live:
        master = reconcile(master, live, dry_run=args.dry_run)
    have = {r["symbol"].upper() for r in master}
    if not args.dry_run and normalise(master):
        save_master(master)

    if args.dry_run:
        if live is None:
            print("NSE equity list is blocked from this IP (HTTP 403 — geo-block).")
            print("--dry-run cannot list new symbols; use a VPN / Indian IP.")
            sys.exit(1)
        new_syms = [s for s in live if s not in have]
        unfilled = [r["symbol"].upper() for r in master if not is_classified(r)]
        todo = list(dict.fromkeys(new_syms + unfilled))
        print(f"Master: {len(master)} stocks. NSE list: {len(live)}. "
              f"New: {len(new_syms)}. Unfilled existing: {len(unfilled)}. "
              f"To fetch: {len(todo)}.")
        if new_syms:
            print("  new symbols:", new_syms[:40], "..." if len(new_syms) > 40 else "")
        print("(dry run — no browser, nothing changed)")
        return

    sync_holidays()

    new_from_http = [s for s in live if s not in have] if live else []
    if args.stubs_only:
        if live is None:
            sys.exit("NSE equity list blocked from this IP — cannot add stubs.")
        save_stubs_and_exit(master, live, new_from_http, "--stubs-only")

    if live is not None and not new_from_http and all(is_classified(r) for r in master):
        print(f"Master: {len(master)} stocks — up to date, nothing to fetch.")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed (pip install playwright && "
              "playwright install chromium) — classifications can't be fetched.")
        if live is None:
            sys.exit(1)
        save_stubs_and_exit(master, live, new_from_http, "No browser")

    filled = 0
    misses = []
    with sync_playwright() as p:
        # channel="chromium" uses the full build's new headless mode — the
        # headless-shell build gets fingerprint-detected by Akamai and
        # connection-reset (ERR_HTTP2_PROTOCOL_ERROR).
        browser = p.chromium.launch(headless=not args.headful, channel="chromium")
        ctx = browser.new_context(user_agent=NSE_UA, locale="en-US",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        print("Warming up NSE session (Akamai validation) ...")
        warmed = False
        for attempt in range(3):
            try:
                page.goto(WARMUP_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)   # let the Akamai sensor run + _abck validate
                warmed = True
                break
            except Exception as e:
                print(f"  warm-up attempt {attempt + 1}/3 failed: {type(e).__name__}")
                time.sleep(4)
        if not warmed:
            print("NSE is refusing connections from this IP (HTTP2 reset / geo-block).")
            print("Try a VPN / Indian IP, or skip the refresh for now.")
            browser.close()
            if live is None:
                sys.exit(1)
            save_stubs_and_exit(master, live, new_from_http, "NSE session failed")

        if live is None:
            print("Plain HTTP blocked — fetching equity list via browser ...")
            live = fetch_equity_list_via_browser(page)
            if not live:
                print("NSE blocks this IP on every endpoint (403 — geo-block).")
                print("Refresh listings from an Indian IP / VPN, or skip for now.")
                sys.exit(1)
            print(f"Browser fetch OK: {len(live)} symbols.")
            master = reconcile(master, live)
            have = {r["symbol"].upper() for r in master}

        new_syms = [s for s in live if s not in have]
        # also flag master rows still missing a classification (e.g. earlier misses)
        unfilled = [r["symbol"].upper() for r in master if not is_classified(r)]
        todo = list(dict.fromkeys(new_syms + unfilled))

        print(f"Master: {len(master)} stocks. NSE list: {len(live)}. "
              f"New: {len(new_syms)}. Unfilled existing: {len(unfilled)}. "
              f"To fetch: {len(todo)}.")
        if new_syms:
            print("  new symbols:", new_syms[:40], "..." if len(new_syms) > 40 else "")
        if not todo:
            print("Up to date — nothing to fetch.")
            browser.close()
            return

        # index master rows by symbol for in-place update; add stubs for new ones
        add_stubs(master, live, new_syms)
        by_sym = {r["symbol"].upper(): r for r in master}

        for i, sym in enumerate(todo, 1):
            series = (live.get(sym, {}).get("series")
                      or by_sym.get(sym, {}).get("series") or "EQ")
            si = None
            try:
                si = page.evaluate(FETCH_JS, [sym, series])
            except Exception as e:
                print(f"  [{i}/{len(todo)}] {sym} eval error: {type(e).__name__}")
            row = by_sym.get(sym)
            got = {"macro": si.get("macro"), "sector": si.get("sector"),
                   "industry": si.get("industryInfo"),          # Industry lives here
                   "basicIndustry": si.get("basicIndustry")} if si else {}
            got = {k: standard_name(v or "") for k, v in got.items()}
            if got and row is not None and got["macro"] in CURRENT_MACROS:
                row.update(got)
                filled += 1
                tag = "ok"
            elif got:
                misses.append(sym)
                tag = (f"MISS — retired NSE scheme ({got['macro']} > "
                       f"{got['basicIndustry']}); add it to {os.path.basename(OVERRIDES)}")
            else:
                misses.append(sym)
                tag = "MISS"
            print(f"  [{i}/{len(todo)}] {sym} {tag}")
            if i % 20 == 0:
                save_master(master)   # checkpoint
            page.wait_for_timeout(300)
        browser.close()

    save_master(master)
    print(f"\nDone. Filled {filled}, missed {len(misses)}. "
          f"Master now {len(master)} stocks.")
    if misses:
        print("  still missing (rerun later / check if suspended):", misses[:30])


if __name__ == "__main__":
    main()
