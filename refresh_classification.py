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

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(HERE, "nse_stock_master.csv")
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


def save_master(rows):
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
    args = ap.parse_args()

    master = load_master_rows()
    have = {r["symbol"].upper() for r in master}

    # Fast path: plain HTTP.  NSE geo-blocks many IPs (403) — then we fall back
    # to fetching the list inside the validated browser session below.
    live = fetch_equity_list()

    if args.dry_run:
        if live is None:
            print("NSE equity list is blocked from this IP (HTTP 403 — geo-block).")
            print("--dry-run cannot list new symbols; use a VPN / Indian IP.")
            sys.exit(1)
        new_syms = [s for s in live if s not in have]
        unfilled = [r["symbol"].upper() for r in master
                    if not (r.get("macro") or r.get("sector") or r.get("basicIndustry"))]
        todo = list(dict.fromkeys(new_syms + unfilled))
        print(f"Master: {len(master)} stocks. NSE list: {len(live)}. "
              f"New: {len(new_syms)}. Unfilled existing: {len(unfilled)}. "
              f"To fetch: {len(todo)}.")
        if new_syms:
            print("  new symbols:", new_syms[:40], "..." if len(new_syms) > 40 else "")
        print("(dry run — no browser, nothing changed)")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright not installed. Run:\n"
                 "    pip install playwright && playwright install chromium")

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
            sys.exit(1)

        if live is None:
            print("Plain HTTP blocked — fetching equity list via browser ...")
            live = fetch_equity_list_via_browser(page)
            if not live:
                print("NSE blocks this IP on every endpoint (403 — geo-block).")
                print("Refresh listings from an Indian IP / VPN, or skip for now.")
                sys.exit(1)
            print(f"Browser fetch OK: {len(live)} symbols.")

        new_syms = [s for s in live if s not in have]
        # also flag master rows still missing a classification (e.g. earlier misses)
        unfilled = [r["symbol"].upper() for r in master
                    if not (r.get("macro") or r.get("sector") or r.get("basicIndustry"))]
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
        by_sym = {r["symbol"].upper(): r for r in master}
        for s in new_syms:
            stub = {k: "" for k in FIELDS}
            stub.update(live[s])
            by_sym[s] = stub
            master.append(stub)

        for i, sym in enumerate(todo, 1):
            series = (live.get(sym, {}).get("series")
                      or by_sym.get(sym, {}).get("series") or "EQ")
            si = None
            try:
                si = page.evaluate(FETCH_JS, [sym, series])
            except Exception as e:
                print(f"  [{i}/{len(todo)}] {sym} eval error: {type(e).__name__}")
            row = by_sym.get(sym)
            if si and row is not None:
                row["macro"] = si.get("macro", "") or ""
                row["sector"] = si.get("sector", "") or ""
                row["industry"] = si.get("industryInfo", "") or ""   # Industry lives here
                row["basicIndustry"] = si.get("basicIndustry", "") or ""
                filled += 1
                tag = "ok"
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
