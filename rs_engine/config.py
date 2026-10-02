"""Constants + configuration for the RS pipeline.

Defaults live in code; a `config.toml` next to the project root can override
them (all keys optional, section [rs]).  The NSE trading-holiday calendar
lives in nse_holidays.csv.
"""
import os
import csv
import datetime as dt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Price caches live OUTSIDE the repo (the project can sit on a fuseblk/NTFS
# volume that strips exec bits and corrupted a cache once).
CACHE_DIR = os.environ.get("NSE_RS_CACHE_DIR") or os.path.join(
    os.path.expanduser("~"), ".cache", "nse-rs")
os.makedirs(CACHE_DIR, exist_ok=True)


def _load_overrides():
    try:
        import tomllib
    except ImportError:                       # python < 3.11
        return {}
    path = os.path.join(HERE, "config.toml")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as fh:
            return (tomllib.load(fh) or {}).get("rs", {})
    except Exception:
        return {}


_CFG = _load_overrides()


def cfg(key, default):
    return _CFG.get(key, default)


WINDOW = int(cfg("window", 26))                 # RS window (matches the sheet)
FULL_RANGE = str(cfg("full_range", "2y"))       # first-fetch history depth
APPEND_RANGE = str(cfg("append_range", "1mo"))  # incremental daily top-up
MIN_BARS = int(cfg("min_bars", 200))            # below → refetch FULL_RANGE
EMA_PERIODS = [int(x) for x in cfg("ema_periods", [20, 50, 100, 150, 200])]
ADR_PERIOD = int(cfg("adr_period", 20))         # ADR% lookback (Qullamaggie 20)
CORP_ACTION_JUMP = float(cfg("corp_action_jump", 0.40))
BENCHMARK_NAME = str(cfg("benchmark", "NIFTY 500"))
BENCH_YSYM = str(cfg("bench_symbol", "^CRSLDX"))
YH_WORKERS = int(cfg("yahoo_workers", 8))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))   # NSE trading day

HOLIDAYS_CSV = os.path.join(HERE, "nse_holidays.csv")
_holidays_cache = None


def load_holidays():
    """NSE trading-holiday calendar from nse_holidays.csv (date,description)."""
    global _holidays_cache
    if _holidays_cache is None:
        _holidays_cache = set()
        if os.path.exists(HOLIDAYS_CSV):
            with open(HOLIDAYS_CSV, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    d = (row.get("date") or "").strip()
                    if d:
                        _holidays_cache.add(d)
    return _holidays_cache


def is_holiday(iso_date):
    """True when the NSE was closed on this date (official holiday calendar)."""
    return iso_date in load_holidays()
