# NSE Relative-Strength — Sectors & Industries

Ranks all **four NSE classification levels** — Macro, Sector, Industry, Basic
Industry — **equally weighted**, by relative strength against the **NIFTY 500**,
with a McClellan-style **Market Breadth** oscillator.

100% free data: **Yahoo Finance** for prices, **NSE** for the classification.
No API keys, no paid subscriptions.  Released under the [MIT License](LICENSE) —
free to use, modify and share.

## What it produces

A website (FastAPI backend + vanilla JS frontend, served on `localhost:8000`)
with:
- Four tabs (Macro / Sector / Industry / Basic Industry), each an equal-weight
  RS ranking of its groups; expand any group to see its constituent stocks.
- Per-stock: RS sparkline, `RS_STS%`, LTP, EMA20/50/100/150/200 flags, the
  **RS line vs its 21-day EMA** (above/below), % off 52-week high, ADR%.
- Filters: search, price-above-EMA, %-off-high, ADR, **RS ≥ N%**, **RS above
  EMA21**, **★ watchlist** — combined with TradingView / **CSV export**.
- Per-stock **RS line + EMA21 chart** (TradingView-style) — click any stock.
- Daily **RS_STS% deltas** vs the previous snapshot, per group and stock.
- **Market Breadth** oscillator (advancers − decliners, RANA-based), plus a
  **per-macro breadth dashboard** — the same oscillator computed for each of
  the macro groups as a card grid with hover tooltips and RS% badges, and
  **divergence alerts** (index at highs while breadth fades, and the reverse).
- **Rotation** tab — daily RS lines per sector vs NIFTY 500 (one point per
  trading session), with a 3M / 6M / 1Y / All period selector.
- **New Listings** tab — IPOs awaiting their first 26-day ranking, split into
  **Outperformers** (best first) and **Underperformers** (worst first) by
  their return since the listing-day close vs NIFTY 500 over the same dates
  (the issue price isn't in the free data, so the listing-day close is the
  base).  They also
  appear inside their Macro / Sector / Industry / Basic Industry groups,
  badged **NEW · Nd** and ranked over their days since listing — sorted by
  RS% together with the other stocks, but kept out of the group index until they have a full
  window (so a 2-day-old stock can't swing its group).
- **Scans** tab — scan summary of the **1-month gainers** (up ≥ 14% over 20
  sessions, average daily traded value ≥ ₹10 crore, price ≥ ₹100 — the rule
  that best reproduced a reference scan), by Sector, Sub-industry or **Market
  cap**: a donut of the split plus stock count, share of the list, "x of N"
  of the whole group, median **RS rating** (1-99, weighted 12-month
  performance vs all stocks) and median 3M return, plus the **whole group's**
  1-day and 1-week change (equal-weight average of all its stocks).  Size
  classes come from NSE's NIFTY 100 / Midcap 150 / Smallcap 250 lists
  (`nse_cap_classes.csv`, refreshed daily); other stocks are Micro, or "No
  market cap" in their first month.
- **FII / DII** tab — monthly **net** cash-market flows of foreign (FII/FPI)
  and domestic (DII) institutions since Jun 2014 as paired bars (1Y / 3Y /
  5Y / All), the running month marked "to <date>", with totals and a
  month-by-month table (net, combined, gross buy / sell).
- **Focus** tab — the one-shot answer: which sectors and which market-cap
  class to focus on next, with a one-liner each.  Sectors (≥ 5 stocks) are
  ranked on 1M / 3M median return vs the average stock, share above the
  50-day EMA, share of RS ≥ 80 leaders and RS_STS%, and tagged Leading /
  Improving / Weakening / Lagging; plus "turning up" and "avoid" lists and
  the market regime.
- **Swing** tab — an evening swing-trading desk: market regime checklist
  (NIFTY 500 vs its 20/50/200-day EMAs, breadth level and direction, share of
  stocks above the 50-day EMA, FII flows) with exposure guidance, leading
  industries, breakout candidates (RS ≥ 80 leaders in a full uptrend within
  10% of the high, liquid, tradeable ADR, not extended), pullbacks in leaders,
  extended stocks not to chase, and risk rules.  Stocks with a board meeting
  in the next 14 days carry a badge — **⚠ Results** in amber (results can gap
  a stock past any stop), dividends / splits / fund raising in grey — from
  NSE's event calendar (`refresh_events.py` → `nse_events.csv`, daily).
  Each candidate shows its **10-day range**, today's **volume ×** its 50-day
  average and setup tags: *Tight* (10-day range within 2.5 ADRs) and *Vol
  dry-up* (10-day volume < 85% of the prior 50) rank a stock higher, *Vol
  surge* (≥ 1.5×) ranks it lower — in the 250-session backtest tight, quiet
  candidates beat NIFTY 500 by +2.4% over 20 sessions vs +1.6% for all,
  while buying the close of a surge day lagged (+1.2%).  **Delivery %** (NSE
  `sec_bhavdata_full`, EQ series; from the NSE daily archive below)
  shows today's and the 20-day average: steady 50%+ delivery nudges a
  breakout up, a weak-delivery day nudges it down (a small effect in the
  backtest, so a small weight; none for pullbacks, where it didn't help).
- **Track record** (on both pages) — every build logs the day's calls to
  `nse_picks.jsonl` and scores them 5 / 10 / 20 sessions later: focus /
  avoid sectors and the size pick vs the average stock, the breakout and
  pullback lists vs NIFTY 500 (also split by regime), and NIFTY 500 after
  each regime.  `backfill_picks.py` rebuilt the year before live logging from
  price history with the same rules (marked as such).  The rules live in
  `rs_engine/decide.py`, so the pages, the log and the brief always agree.
- **Evening Telegram brief** (`send_brief.py`, after each build) — the Focus
  answer, regime, top breakouts / pullbacks with results warnings, FII / DII
  and the track record, plus **watchlist alerts** for your ☆ stocks: entered
  the breakout / pullback list, crossed the 20-day EMA, 52-week high, results
  ahead.  Stars on the local site sync to `~/.config/nse-rs/watchlist.txt`
  (outside the public repo; editable by hand).  Setup: message @BotFather →
  `/newbot` → token; message your bot; `TELEGRAM_BOT_TOKEN=… python
  send_brief.py --chat-id`; put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in
  `~/.config/nse-rs/notify.env`.  `--dry-run` prints the message.
- A printable **daily digest** (`daily_report.html`) after every build.

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
- Days where Yahoo served stale, unchanged prices (2025-03-18) are purged and
  refilled from the bhavcopy; bhavcopy prices are raw, so every filled bar is
  scaled to Yahoo's split/bonus-adjusted series and re-scaled on later
  adjustments (`~/.cache/nse-rs/.nse_official_fills.json`).
- **FII / DII flows:** NSE provisional cash-market figures (₹ crore).  NSE's
  API serves only the latest session, so the monthly history comes from Kotak
  Neo's FII/DII page, which republishes the same numbers (they reconcile
  exactly with NSE's daily figures); NSE's own day is recorded too, and
  counted in the running month when Kotak hasn't caught up.  NSE posts the
  day's figures between ~18:00 and 21:00, so the hourly catch-up runs also
  fetch them and patch `rs_data.json` without a full rebuild.
- **NSE daily archive → official prices** (`rs_engine/nse_archive.py`,
  cache `~/.cache/nse-rs/.nse_archive.json`, last 300 sessions of NSE's
  `sec_bhavdata_full`: close, high, low, quantity, delivery).  Every build
  rebuilds each stock's archived sessions from NSE's own prices and keeps
  Yahoo's adjustment only across genuine corporate actions (a clean ≥ 7%
  factor step where NSE's raw price made the move).  This fixes Yahoo's
  *partial* split / bonus adjustments (TRENT's 1:2 bonus was adjusted only
  back to 1-Jan-2026, leaving a fake −33% day; SILVERTUC a fake −90%), stale
  or wrong bars, and history Yahoo lacks (≈220 stocks start at Yahoo on
  18-Aug-2026 but traded on NSE for months).  Untraded sessions carry NSE's
  last close.  Idempotent; a no-op when NSE is unreachable (cloud runner).
- **Market sessions only:** stock bars on non-session days (Yahoo's holiday
  carry-forwards, the Sunday Muhurat hour) are dropped, and 1W / 1M / 3M
  returns and the 52-week high count market sessions — a stock that skipped
  days isn't measured over a longer stretch.
- **Wrong single bars:** Yahoo occasionally serves a bad close for a thin
  stock on one day (SAPPL 20-Nov-2026: 318.40 vs NSE's 330.00).  Each build
  compares the last 5 sessions with the bhavcopy and replaces a close that
  differs while the days around it agree (an isolated miss — a split or
  dividend adjustment shifts every earlier bar and is left alone);
  `build_rs.py --recheck 63` sweeps further back.
- **Single-stock** null bars (common for fresh listings and renamed tickers)
  inside the RS window are filled from the bhavcopy too, so one missing Yahoo
  day doesn't drop a stock out of the rankings.

## Scripts

| Script | Purpose |
|---|---|
| `build_rs.py` | Fetch Yahoo prices, append history, rebuild `rs_data.json` (+ the `daily_report.html` digest). |
| `refresh_classification.py` | When NSE lists new stocks: fetch their 4-level classification (headless browser) and append to the master. |
| `refresh_flows.py` | Update the FII / DII cash-flow history (`nse_fii_dii_monthly.csv`, `nse_fii_dii_daily.csv`). Best effort: keeps the files on failure. |
| `backfill_picks.py` | Rebuild past Focus / Swing calls from price history into `nse_picks.jsonl` (one-off; live builds log each day). |
| `refresh_events.py` | Update `nse_events.csv` — NSE board meetings (results, dividends, splits…) for the next 30 days. Best effort. |
| `send_brief.py` | Evening Telegram brief + watchlist alerts (once per session; no-op without a bot token). |
| `watchlist.py` | Watchlist file + alert rules for the brief. |
| `audit_data.py` | Data-integrity audit (cache validity, holiday calendar, fake bars, freshness) — exits non-zero on issues, cron-ready. |
| `run_daily.sh` | Wrapper that runs `build_rs.py` and logs to `run.log`. |
| `run_server.sh` | Serve the website (FastAPI backend + frontend) on `localhost:8000` (`NSE_RS_HOST=0.0.0.0` to expose it on the LAN). |
| `cron_daily.sh` | Cron entry point: daily build + audit (+ optional Telegram failure alerts). |
| `install_cron.sh` | Installs the cron entries (18:30 build, 19:30 stale-retry, weekdays). |
| `export_static.py` | Build a read-only static site into `site/` (no backend needed). |
| `publish_site.sh` | Commit + push the current `rs_data.json` snapshot (triggers the public site deploy). |

## Daily use

```
bash run_daily.sh     # 1. fetch today's prices, rebuild data (~few min)
bash run_server.sh    # 2. start the website
# 3. open http://localhost:8000
```

Or, with the server running, click **"Update Prices"** / **"Refresh Stocks"**
in the website header.

### Automation (optional)

`bash install_cron.sh` installs the weekday cron entries (system timezone):

- **18:30** — `cron_daily.sh`: new-listing + FII/DII refresh, daily build + data audit
- **19:30** — `cron_daily.sh --if-stale`: retries once if Yahoo published late
  and the 18:30 run missed the session
- **hourly + @reboot** — `cron_daily.sh --if-stale`: catch-up when the machine
  was off at 18:30 (no-op while the data is current)

Each run first calls `refresh_classification.py`, so new NSE listings reach
the **New Listings** tab the day they trade.  Without a working browser (or
from a geo-blocked IP) they are added unclassified and classified on a later
run; renamed symbols (same ISIN) are merged and logged in
`nse_symbol_changes.csv`, and symbols that left NSE's list **and** stopped
trading are archived to `nse_delisted.csv` (NSE's list drops some thin BE/BZ
stocks on some days; those stay, and an archived stock that trades or is
listed again comes back with its classification).

Optional free Telegram failure alerts: create a bot via @BotFather, then put
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `~/.config/nse-rs/notify.env`
(set `TELEGRAM_NOTIFY_OK=1` for success pings too).  CI runs the test suite on
every push via GitHub Actions (`.github/workflows/ci.yml`).

### Public site (free, for everyone)

`bash publish_site.sh` commits the current `rs_data.json` snapshot (plus the
stock master, which the cloud fallback build reads) and pushes —
GitHub Actions deploys it as a **read-only** copy of the dashboard to GitHub
Pages (works without any backend; Update/Refresh buttons are hidden).  Set
`PUBLISH_SITE=1` in `~/.config/nse-rs/notify.env` to publish automatically
after every successful daily build.  Requires the repository to be public
(GitHub Pages is free for public repos only).

## Build options

```
python3 build_rs.py               # full fetch + rebuild (default)
python3 build_rs.py --refresh     # force full ~2y re-fetch of every stock
python3 build_rs.py --html-only   # rebuild from cache only (no fetching)
python3 build_rs.py --fast        # incremental top-up (what "Update Prices" uses)
python3 refresh_classification.py --dry-run   # list new symbols, no browser
python3 refresh_classification.py --headful  # show the browser window
python3 refresh_classification.py --stubs-only  # add new listings unclassified
```

## Tests

```
PY=~/.venvs/nse-rs/bin/python
$PY -m pytest tests/ -q          # all (89)
$PY -m pytest tests/ -q -m smoke # frontend smoke only
NO_BROWSER=1 $PY -m pytest tests/ -q   # skip browser tests
$PY -m ruff check .              # lint (also runs in CI)
$PY audit_data.py                # daily data health check
```

Covers the benchmark gap-fill fallback chain (Yahoo index gaps → Investing.com
scrape → synthetic equal-weight), Yahoo null-OHLC handling, the intraday/bhavcopy
repair chain, RS maths, the RS-vs-EMA21 flag, the NSE holiday calendar, and
integrity of the generated artifacts (RS window alignment, market-breadth
continuity, window-coverage consistency).  Frontend smoke tests boot the real
server and load the page in headless Chromium.

## Setup (first time)

```
python3 -m venv ~/.venvs/nse-rs
~/.venvs/nse-rs/bin/pip install -r requirements.txt -r backend/requirements.txt
~/.venvs/nse-rs/bin/python -m playwright install chromium   # for refresh_classification.py
~/.venvs/nse-rs/bin/python build_rs.py                      # initial build
```

The venv lives **outside** the repo on purpose: on an NTFS/fuseblk volume the
exec bits are stripped, so an in-repo `.venv` (and Playwright's bundled
driver) cannot run.  The shell scripts pick the interpreter via
`find_python.sh`: `$NSE_RS_PY` → `~/.venvs/nse-rs` → `./.venv` → `python3`.

## Configuration & layout

- `config.toml` — optional tunables (window size, benchmark symbol, EMA
  periods, fetch ranges…).  Delete it to use the built-in defaults.
- `nse_holidays.csv` — the official NSE trading-holiday calendar used by the
  build and the audit.
- `nse_stock_master.csv` — the universe + 4-level classification;
  `nse_symbol_changes.csv` (renames — the build stitches the old ticker's
  history onto the new one) and `nse_delisted.csv` (archived rows) are
  maintained by `refresh_classification.py`.  Names are stored in one
  standard spelling (Title Case classification names, ALL-CAPS company names
  normalised with acronyms kept).  `nse_classification_overrides.csv` holds
  hand-checked classifications for the few stocks NSE still reports under its
  retired scheme (MANUFACTURING, CONSUMER…) — the audit fails if such a value
  or a non-standard spelling reaches the master.
- `nse_fii_dii_monthly.csv` / `nse_fii_dii_daily.csv` — FII / DII cash
  flows (buy, sell, net in ₹ crore), maintained by `refresh_flows.py`.
- `rs_engine/` — computation core (config, RS maths, breadth, rotation,
  FII/DII flows, snapshots, digest); `build_rs.py` holds the data layer
  (caches, Yahoo/bhavcopy fetchers, gap-fills) and the CLI.

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
  cache. `daily_report.html` is generated and git-ignored;
  `rs_data.json` is generated too but **committed** — it is the snapshot the
  public site serves.
- `nse_holidays.csv` is the official NSE trading-holiday calendar — the build
  and audit use it to skip holidays and to validate the trading calendar.
  `refresh_classification.py` merges NSE's published list into it daily; the
  audit fails from December on if next year's holidays are still missing.
