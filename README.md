# NSE Relative-Strength — Sectors & Industries

Ranks all **four NSE classification levels** — Macro, Sector, Industry, Basic
Industry — **equally weighted**, by relative strength against the **NIFTY 500**,
with a McClellan-style **Market Breadth** oscillator.

100% free data: **Yahoo Finance** for prices, **NSE** for the classification.
No API keys, no paid subscriptions.

## What it produces

A website (FastAPI backend + vanilla JS frontend, served on `localhost:8000`)
with:
- Four tabs (Macro / Sector / Industry / Basic Industry), each an equal-weight
  RS ranking of its groups; expand any group to see its constituent stocks.
- Per-stock: RS sparkline, `RS_STS%`, LTP, EMA20/50/100/150/200 flags, the
  **RS line vs its 21-day EMA** (above/below), % off 52-week high, ADR%.
- Filters: search, price-above-EMA, %-off-high, ADR, **RS ≥ N%**, **RS above
  EMA21** — combined with a TradingView watchlist export.
- **Market Breadth** oscillator (advancers − decliners, RANA-based), plus a
  **per-macro breadth dashboard** — the same oscillator computed for each of
  the 12 macro groups as a card grid with hover tooltips and RS% badges.

## Method

- Daily closes per stock from Yahoo (`SYMBOL.NS`); benchmark = **NIFTY 500**
  (`^CRSLDX`).
- Equal-weight index per group: each stock base-100 on day 0 of the window,
  averaged across constituents each day.
- `RS[t] = group_index[t] / benchmark_norm[t]` (both base-100).
- `RS_STS% = PERCENTRANK.INC(RS_series, latest RS)` over the 26-day window.
- Stocks without a close every window day (suspensions, halts, new listings)
  are excluded from the view — the window count is reported in the UI.

## Data sources

- **Universe + classification:** `nse_stock_master.csv` — all ~2,400 NSE stocks
  with their 4-level industry classification, built directly from NSE.
- **Prices:** Yahoo Finance chart API (free, no key). The cache
  (`.yh_price_cache.json`) grows over time: the first run pulls ~2y per symbol,
  later runs only top up the last month and append, so daily runs are fast.
- Yahoo occasionally publishes null OHLC for index symbols on days stocks
  traded fine — such benchmark gaps are filled from **Investing.com** (real
  index close), with an equal-weight synthetic from stock returns as last
  resort.
- When Yahoo's **daily bars are null but intraday bars exist** (whole-market
  gaps like Aug 28, 2026), the build repairs the missing day automatically:
  **NSE official bhavcopy** first (Indian IPs, authoritative closes), then
  Yahoo 5-minute bars. Flat duplicate bars (Yahoo's holiday artifacts) are
  detected and never enter the benchmark.

## Scripts

| Script | Purpose |
|---|---|
| `build_rs.py` | Fetch Yahoo prices, append history, rebuild `rs_data.json` + `rs_view.html`. |
| `refresh_classification.py` | When NSE lists new stocks: fetch their 4-level classification (headless browser) and append to the master. |
| `audit_data.py` | Data-integrity audit (cache validity, holiday calendar, fake bars, freshness) — exits non-zero on issues, cron-ready. |
| `run_daily.sh` | Wrapper that runs `build_rs.py` and logs to `run.log`. |
| `run_server.sh` | Serve the website (FastAPI backend + frontend) on `localhost:8000`. |

## Daily use

```
bash run_daily.sh     # 1. fetch today's prices, rebuild data (~few min)
bash run_server.sh    # 2. start the website
# 3. open http://localhost:8000
```

Or, with the server running, click **"Update Prices"** / **"Refresh Stocks"**
in the website header.

## Build options

```
python3 build_rs.py               # full fetch + rebuild (default)
python3 build_rs.py --refresh     # force full ~2y re-fetch of every stock
python3 build_rs.py --html-only   # rebuild from cache only (no fetching)
python3 build_rs.py --fast        # incremental top-up (what "Update Prices" uses)
python3 refresh_classification.py --dry-run   # list new symbols, no browser
python3 refresh_classification.py --headful  # show the browser window
```

## Tests

```
.venv/bin/python -m pytest tests/ -q          # all (56)
.venv/bin/python -m pytest tests/ -q -m smoke # frontend smoke only
NO_BROWSER=1 .venv/bin/python -m pytest tests/ -q   # skip browser tests
.venv/bin/python audit_data.py                # daily data health check
```

Covers the benchmark gap-fill fallback chain (Yahoo index gaps → Investing.com
scrape → synthetic equal-weight), Yahoo null-OHLC handling, the intraday/bhavcopy
repair chain, RS maths, the RS-vs-EMA21 flag, the NSE holiday calendar, and
integrity of the generated artifacts (RS window alignment, market-breadth
continuity, window-coverage consistency).  Frontend smoke tests boot the real
server and load the page in headless Chromium.

## Setup (first time)

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium       # only needed for refresh_classification.py
python3 build_rs.py               # initial build
```

## Notes

- `refresh_classification.py` needs a real browser because NSE's classification
  API sits behind Akamai. Use the **full Chromium build** (`channel="chromium"`)
  — the headless-shell is fingerprint-detected and connection-reset by Akamai.
- **NSE geo-blocks non-Indian IPs** (403 on every endpoint). Run
  `refresh_classification.py` from an Indian IP / VPN; the equity list falls
  back to a browser-session fetch if plain HTTP is blocked. Yahoo-based steps
  (prices, RS, breadth) work from anywhere.  The **bhavcopy** repair source is
  likewise Indian-IP-only (it is a fallback, not a requirement).
- **Price caches live in `~/.cache/nse-rs/`** (override with `NSE_RS_CACHE_DIR`)
  — outside the repo, safe from the fuseblk/NTFS quirks that once corrupted a
  cache. `rs_data.json` and `rs_view.html` are generated and git-ignored.
- `nse_holidays.csv` is the official NSE trading-holiday calendar — the build
  and audit use it to skip holidays and to validate the trading calendar.
