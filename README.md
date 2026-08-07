# NSE Relative-Strength view — Sectors & Industries

Replicates the `RS.xlsx` Relative-Strength view (see `image1.png`) across **all
four NSE classification levels** — Macro, Sector, Industry, Basic Industry —
**equally weighted**, as a single self-contained `rs_view.html`.

100% free data: **Yahoo Finance** for prices, **NSE** for the classification.
No API keys, no paid subscriptions.

## What it produces

`rs_view.html` — an interactive page with:
- Four tabs (Macro / Sector / Industry / Basic Industry), each an equal-weight
  RS ranking of its groups; expand any group to see its constituent stocks.
- Per-stock RS sparkline, `RS_STS%`, **LTP**, and EMA20/50/100/150/200 above/below
  flags, with search + "price above EMA" filters and a TradingView watchlist export.
- A **Market Breadth** oscillator (McClellan-style) with an interactive
  crosshair/tooltip.

## Method (mirrors RS.xlsx)

- Daily closes per stock from Yahoo (`SYMBOL.NS`); benchmark = **NIFTY 500**
  (`^CRSLDX`).
- Equal-weight index per group: each stock base-100 on day 0 of the window,
  averaged across constituents each day.
- `RS[t] = group_index[t] / benchmark_norm[t]` (both base-100).
- `RS_STS% = PERCENTRANK.INC(RS_series, latest RS)` — identical to the sheet.

## Data sources

- **Universe + classification:** `nse_stock_master.csv` — all ~2381 NSE stocks
  with their 4-level industry classification, built directly from NSE.
- **Prices:** Yahoo Finance chart API (free, no key). The cache
  (`.yh_price_cache.json`) grows over time: the first run pulls ~2y per symbol,
  later runs only top up the last month and append, so daily runs are fast.
  Yahoo occasionally publishes null OHLC for index symbols on days stocks
  traded fine — such benchmark gaps are filled from **Investing.com** (real
  index close), with an equal-weight synthetic from stock returns as last
  resort.

## Scripts

| Script | Purpose |
|---|---|
| `build_rs.py` | Daily: fetch Yahoo prices, append history, rebuild `rs_view.html` + `rs_data.json`. |
| `refresh_classification.py` | When NSE lists new stocks: fetch their 4-level classification (headless browser) and append to the master. |
| `run_daily.sh` | Wrapper that runs `build_rs.py` and logs to `run.log`. |
| `run_server.sh` | Serve the website (FastAPI backend + frontend) on localhost:8000. |

## Tests

```
.venv/bin/python -m pytest tests/ -q
```

Covers the benchmark gap-fill fallback chain (Yahoo index gaps → Investing.com
scrape → synthetic equal-weight), Yahoo null-OHLC handling, RS maths, and
integrity of the generated artifacts (RS window alignment, market-breadth
continuity).

## Setup & usage

See **`COMMANDS.txt`** for the exact commands. In short:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # only needed for refresh_classification.py
python3 build_rs.py                 # build the view
```

## Notes

- `refresh_classification.py` needs a real browser because NSE's classification
  API sits behind Akamai (which needs JS-validated cookies); Playwright handles
  that automatically — no manual steps.
- `rs_view.html` and `.yh_price_cache.json` are generated and git-ignored.
