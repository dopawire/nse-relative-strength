"""FII / DII cash-market flows (NSE provisional figures, ₹ crore).

Two files in the repo hold the history; refresh_flows.py updates them and
build_rs.py reads them (no network) into rs_data.json["flows"]:

  nse_fii_dii_monthly.csv  month, FII buy/sell/net, DII buy/sell/net
  nse_fii_dii_daily.csv    date,  FII buy/sell/net, DII buy/sell/net

The monthly history (Jun 2014 →) comes from Kotak Neo's FII/DII page, which
republishes NSE's provisional numbers (they reconcile to the paisa with NSE's
own daily figures).  NSE's API only serves the latest session, so it is
recorded daily as the official cross-check / fallback for the current month.

Daily history before the first recorded session was backfilled once
(`refresh_flows.py --backfill`) from stockezee's day-by-day archive, which
carries the net figures only — those rows have no gross buy / sell.  Its
days agree to the paisa with NSE's own for every session both have.
"""
import csv
import datetime as dt
import os
import re

from rs_engine.config import data_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTHLY = data_path("nse_fii_dii_monthly.csv")
DAILY = data_path("nse_fii_dii_daily.csv")

KOTAK_URL = "https://www.kotakneo.com/share-market-today/fii-dii-data/"
NSE_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
ARCHIVE_URL = "https://www.stockezee.com/fii-dii-historical-data"

FIELDS = ["fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"]
MIN_MONTHS = 100          # a sane Kotak page has ~150 months since 2014


def _num(s):
    s = re.sub(r"<[^>]+>", "", s).replace(",", "").replace("₹", "").strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def _cells(row_html):
    return [re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def parse_kotak(html):
    """→ (months, days): {"YYYY-MM": {field: v}}, {"YYYY-MM-DD": {field: v}}.
    Rows are 'Mon YYYY' (monthly table) or 'DD-Mon-YYYY' (daily table), each
    followed by FII buy, sell, net, DII buy, sell, net."""
    months, days = {}, {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        c = _cells(row)
        if len(c) < 7:
            continue
        vals = [_num(x) for x in c[1:7]]
        if any(v is None for v in vals):
            continue
        rec = dict(zip(FIELDS, vals))
        for fmt, out, key in (("%b %Y", months, "%Y-%m"), ("%d-%b-%Y", days, "%Y-%m-%d")):
            try:
                out[dt.datetime.strptime(c[0], fmt).strftime(key)] = rec
                break
            except ValueError:
                continue
    return months, days


def parse_nse(rows):
    """NSE fiidiiTradeReact JSON → {"YYYY-MM-DD": {field: v}} (one session)."""
    out = {}
    for x in rows or []:
        cat = (x.get("category") or "").upper()
        who = "fii" if cat.startswith("FII") else "dii" if cat.startswith("DII") else None
        try:
            d = dt.datetime.strptime(x["date"], "%d-%b-%Y").strftime("%Y-%m-%d")
            vals = [float(x[k]) for k in ("buyValue", "sellValue", "netValue")]
        except (KeyError, TypeError, ValueError):
            continue
        if who:
            out.setdefault(d, {}).update(dict(zip((f"{who}_buy", f"{who}_sell", f"{who}_net"), vals)))
    return {d: r for d, r in out.items() if len(r) == len(FIELDS)}


def parse_archive(html):
    """stockezee's day-by-day archive (Next.js page data) → {"YYYY-MM-DD":
    {fii_net, dii_net, and None for the gross buy / sell it doesn't carry}}."""
    out = {}
    text = html.replace('\\"', '"')
    for m in re.finditer(r'"date":"(\d{4}-\d\d-\d\d)T00:00:00","fii_cash":\[(.*?)\]', text):
        fii = re.search(r'"FII/FPI","net_value":(-?\d+(?:\.\d+)?)', m.group(2))
        dii = re.search(r'"DII","net_value":(-?\d+(?:\.\d+)?)', m.group(2))
        if fii and dii:
            rec = dict.fromkeys(FIELDS)
            rec.update(fii_net=float(fii.group(1)), dii_net=float(dii.group(1)))
            out[m.group(1)] = rec
    return out


def read_csv(path, key):
    """Blank cells (net-only archive days) read as None."""
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r[key]: {k: float(r[k]) if r.get(k) not in ("", None) else None for k in FIELDS}
                for r in csv.DictReader(f) if r.get(key)}


def write_csv(path, key, data):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([key] + FIELDS)
        for k in sorted(data):
            w.writerow([k] + ["" if data[k][x] is None else f"{data[k][x]:.2f}" for x in FIELDS])
    os.replace(tmp, path)


def backfill(days, archive):
    """Archive days not recorded yet (never overwrites a recorded day)."""
    out = dict(days)
    for d, rec in archive.items():
        out.setdefault(d, rec)
    return out


def merge(months_old, days_old, kotak_months, kotak_days, nse_days):
    """New (monthly, daily) history.

    A complete Kotak page replaces the monthly table; sessions newer than its
    daily table (Kotak lagging NSE) are added to their month.  Without Kotak
    the old table stays and only sessions never seen before are added, so a
    day is never counted twice.  Days merge, NSE's own figures winning."""
    days = dict(days_old)
    days.update(kotak_days)
    days.update(nse_days)
    if len(kotak_months) >= MIN_MONTHS and kotak_days:
        months = {m: dict(v) for m, v in kotak_months.items()}
        last = max(kotak_days)
        extra = [d for d in days if d > last]
    else:
        months = {m: dict(v) for m, v in months_old.items()}
        extra = [d for d in nse_days if d not in days_old and d not in kotak_days]
    for d in sorted(extra):
        row = months.setdefault(d[:7], {k: 0.0 for k in FIELDS})
        for k in FIELDS:
            row[k] += days[d][k]
    return months, days


def monthly_series(months, days):
    """Chart rows, oldest first.  `to` = last recorded session of the month
    (shown as "month to date" for the running month)."""
    last_day = {}
    for d in sorted(days):
        last_day[d[:7]] = d
    return [{"m": m,
             "fb": round(r["fii_buy"], 2), "fs": round(r["fii_sell"], 2),
             "fii": round(r["fii_net"], 2),
             "db": round(r["dii_buy"], 2), "ds": round(r["dii_sell"], 2),
             "dii": round(r["dii_net"], 2),
             "to": last_day.get(m)}
            for m, r in sorted(months.items())]


def daily_series(days):
    """Daily chart rows, oldest first; fb/fs/db/ds are None on net-only days."""
    r2 = lambda v: None if v is None else round(v, 2)  # noqa: E731
    return [{"d": d, "fii": r2(r["fii_net"]), "dii": r2(r["dii_net"]),
             "fb": r2(r["fii_buy"]), "fs": r2(r["fii_sell"]),
             "db": r2(r["dii_buy"]), "ds": r2(r["dii_sell"])}
            for d, r in sorted(days.items())]


def build_flows():
    """rs_data.json["flows"] from the two CSVs — {} when there is no data."""
    months, days = read_csv(MONTHLY, "month"), read_csv(DAILY, "date")
    if not months and not days:
        return {}
    rows = monthly_series(months, days)
    return {"months": rows, "days": daily_series(days), "asof": max(days) if days else None,
            "src": "NSE provisional (cash market), ₹ crore"}
