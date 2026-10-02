"""Tests for build_rs.py — focused on the benchmark-gap fallback chain
(the July 28, 2026 incident: Yahoo returned null OHLC for Indian indices,
the Investing.com scraper silently matched 0 rows after a site redesign, and
the equal-weight synthetic fill wrote a wrong close, 22,979.79 instead of
23,114.90, into the benchmark cache).

Layers:
  1. Unit tests for the scraper, Yahoo parser, fill chain, and RS maths
     (all network mocked out).
  2. Integration tests over the generated artifacts (.yh_price_cache.json,
     rs_data.json) — RS view + market breadth correctness.
"""
import json
import datetime as dt
from pathlib import Path

import pytest

import build_rs
from build_rs import (
    _scrape_investing_com,
    yahoo_closes,
    fill_benchmark_gaps,
    percentrank_inc,
    IST,
    WINDOW,
)

ROOT = Path(__file__).resolve().parent.parent
PRICE_CACHE = Path(build_rs.PRICE_CACHE)   # cache dir can move (see build_rs)
RS_DATA = ROOT / "rs_data.json"


# --------------------------------------------------------------------------- #
#  Helpers / fakes
# --------------------------------------------------------------------------- #
class FakeResp:
    def __init__(self, status_code=200, text="", payload=None, content=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.content = content if content is not None else text.encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Duck-typed requests.Session returning queued responses."""
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = exc is None and resp or None, exc

    def get(self, *a, **kw):
        if self.exc is not None:
            raise self.exc
        return self.resp


def patch_session(monkeypatch, session):
    monkeypatch.setattr(build_rs, "_session", lambda: session)


def inv_html(rows):
    """Minimal page HTML embedding the historicalData JSON blob."""
    body = ",".join(
        '{{"direction_color":"redFont","rowDate":"Jul {day}, 2026","rowDateRaw":0,'
        '"rowDateTimestamp":"2026-07-{day}T00:00:00Z","last_close":"{c}",'
        '"last_closeRaw":"{raw}","change_precent":"-0.16","note":"bracket ] test"}}'
        .format(day=day, c=c, raw=raw)
        for day, c, raw in rows
    )
    return '<html>"historicalData":{"data":[' + body + ']},"other":[1,2]}</html>'


# --------------------------------------------------------------------------- #
#  1. Investing.com scraper
# --------------------------------------------------------------------------- #
def test_scraper_parses_embedded_json(monkeypatch):
    html = inv_html([("29", "23,352.60", "23352.59960937500000"),
                     ("28", "23,114.90", "23114.90039062500000"),
                     ("27", "23,153.10", "23153.09960937500000")])
    patch_session(monkeypatch, FakeSession(FakeResp(200, text=html)))
    out = _scrape_investing_com()
    assert out == {
        "2026-07-29": 23352.599609375,
        "2026-07-28": 23114.900390625,
        "2026-07-27": 23153.099609375,
    }


def test_scraper_returns_none_when_blob_absent(monkeypatch):
    """Regression: the site redesign removed the old <time datetime=...> table;
    the old regex silently matched 0 rows.  The scraper must return None (so
    the synthetic fallback is a *visible* choice), never an empty/garbage dict."""
    patch_session(monkeypatch, FakeSession(FakeResp(200, text="<html><table>"
        '<td><time datetime="2026-07-29">Jul 29, 2026</time></td>'
        "<td>23,352.60</td></table></html>")))
    assert _scrape_investing_com() is None


def test_scraper_returns_none_on_http_error(monkeypatch):
    patch_session(monkeypatch, FakeSession(FakeResp(403, text="denied")))
    assert _scrape_investing_com() is None


def test_scraper_returns_none_on_network_error(monkeypatch):
    import requests
    patch_session(monkeypatch, FakeSession(exc=requests.ConnectionError("down")))
    assert _scrape_investing_com() is None


def test_scraper_returns_none_on_truncated_json(monkeypatch):
    patch_session(monkeypatch, FakeSession(FakeResp(
        200, text='"historicalData":{"data":[{"rowDateTimestamp":"2026-07-28T')))
    assert _scrape_investing_com() is None


# --------------------------------------------------------------------------- #
#  2. Yahoo parser — null handling (the exact July 28 case)
# --------------------------------------------------------------------------- #
def _ts(y, m, d):
    return int(dt.datetime(y, m, d, 9, 15, tzinfo=IST).timestamp())


def test_yahoo_closes_skips_null_close(monkeypatch):
    """Index timestamp exists but OHLC is null (Yahoo's Jul 28 gap): the date
    must be absent from the result so a previously filled value is never
    overwritten by a null."""
    payload = {"chart": {"result": [{
        "timestamp": [_ts(2026, 7, 27), _ts(2026, 7, 28), _ts(2026, 7, 29)],
        "indicators": {"quote": [{
            "close": [23153.10, None, 23352.60],
            "high":  [23200.0,  None, 23376.85],
            "low":   [23050.0,  None, 23236.40],
        }]},
    }]}}
    patch_session(monkeypatch, FakeSession(FakeResp(200, payload=payload)))
    closes, highs, lows, err = yahoo_closes("^CRSLDX", "1mo")
    assert err is None
    assert closes == {"2026-07-27": 23153.10, "2026-07-29": 23352.60}
    assert "2026-07-28" not in closes
    assert "2026-07-28" not in highs and "2026-07-28" not in lows


def test_yahoo_closes_null_highlow_falls_back_to_close(monkeypatch):
    payload = {"chart": {"result": [{
        "timestamp": [_ts(2026, 7, 27)],
        "indicators": {"quote": [{"close": [100.0], "high": [None], "low": [None]}]},
    }]}}
    patch_session(monkeypatch, FakeSession(FakeResp(200, payload=payload)))
    closes, highs, lows, err = yahoo_closes("X.NS", "1mo")
    assert closes == {"2026-07-27": 100.0}
    assert highs == {"2026-07-27": 100.0}
    assert lows == {"2026-07-27": 100.0}


# --------------------------------------------------------------------------- #
#  2c. NSE holiday calendar + bhavcopy (Phase-1 hardening)
# --------------------------------------------------------------------------- #
from build_rs import is_holiday, fetch_bhavcopy, fetch_bhav_indices


def test_holiday_calendar():
    assert is_holiday("2026-05-28")        # Bakri Id
    assert is_holiday("2025-10-22")        # Diwali Balipratipada
    assert is_holiday("2026-01-15")        # Maharashtra election day
    assert not is_holiday("2026-08-28")    # Raksha Bandhan — trading day
    assert not is_holiday("2025-02-01")    # Union Budget Saturday session
    assert not is_holiday("2026-08-31")    # plain Monday


def test_fill_skips_calendar_holiday():
    """A holiday must never enter the benchmark even with full stock coverage
    (Yahoo emits fake flat bars on holidays)."""
    have, cache = _stock_cache(150, ["2026-05-27", "2026-05-28"], step=1.0)
    bench = {"2026-05-27": 1000.0}
    assert fill_benchmark_gaps(bench, cache, have, thresh=100, inv={}) == []
    assert "2026-05-28" not in bench


def test_repair_skips_calendar_holiday(monkeypatch, tmp_path):
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(tmp_path / "p.json"))
    monkeypatch.setattr(build_rs, "HIGH_CACHE", str(tmp_path / "h.json"))
    monkeypatch.setattr(build_rs, "LOW_CACHE", str(tmp_path / "l.json"))
    cache = {"__BENCH__": {"2026-05-27": 1000.0}, "AAA": {"2026-05-27": 100.0}}

    def boom(*a, **k):
        raise AssertionError("no network calls on a calendar holiday")
    monkeypatch.setattr(build_rs, "intraday_day", boom)
    monkeypatch.setattr(build_rs, "fetch_bhavcopy", boom)
    from build_rs import repair_intraday_gap
    assert repair_intraday_gap(cache, {}, {}, ["AAA"], thresh=1,
                               today=dt.date(2026, 5, 29)) == []


def test_fetch_bhavcopy_parses_new_format(monkeypatch):
    import io as _io
    import zipfile as _zipfile
    csv_text = ("SYMBOL,SERIES,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE\n"
                "RELIANCE,EQ,1291.5,1280,1287\n"
                "TCS,EQ,2260,2230,2250\n"
                "RELIANCE,BE,999,999,999\n"      # must not overwrite the EQ row
                "GOLDBEES,N1,50,49,49.5\n")      # non-equity series ignored
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm28AUG2026bhav.csv", csv_text)
    patch_session(monkeypatch, FakeSession(FakeResp(200, content=buf.getvalue())))
    out = fetch_bhavcopy("2026-08-28")
    assert out["RELIANCE"] == {"close": 1287.0, "high": 1291.5, "low": 1280.0}
    assert out["TCS"]["close"] == 2250.0
    assert "GOLDBEES" not in out


def test_fetch_bhavcopy_legacy_columns(monkeypatch):
    import io as _io
    import zipfile as _zipfile
    csv_text = "SYMBOL,SERIES,HIGH,LOW,CLOSE\nRELIANCE,EQ,1291.5,1280,1287\n"
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm28AUG2026bhav.csv", csv_text)
    patch_session(monkeypatch, FakeSession(FakeResp(200, content=buf.getvalue())))
    out = fetch_bhavcopy("2026-08-28")
    assert out["RELIANCE"]["close"] == 1287.0


def test_fetch_bhavcopy_modern_camelcase_columns(monkeypatch):
    """NSE's modernized bhavcopy schema (2024+) — the one actually served now."""
    import io as _io
    import zipfile as _zipfile
    csv_text = ("TradDt,TckrSymb,SctySrs,FinInstrmTp,HghPric,LwPric,ClsPric\n"
                "2026-10-01,RELIANCE,EQ,STK,1183.9,1160.8,1167.7\n"
                "2026-10-01,SGBJUN28,GB,STK,90,89,89.5\n"          # non-equity series
                "2026-10-01,NIFTYBEES,EQ,ETF,250,248,249\n")      # ETF instrument
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy.csv", csv_text)
    patch_session(monkeypatch, FakeSession(FakeResp(200, content=buf.getvalue())))
    out = fetch_bhavcopy("2026-10-01")
    assert out["RELIANCE"] == {"close": 1167.7, "high": 1183.9, "low": 1160.8}
    assert "SGBJUN28" not in out and "NIFTYBEES" not in out


def test_purge_flat_carries_keeps_real_movers(monkeypatch, tmp_path):
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(tmp_path / "p.json"))
    monkeypatch.setattr(build_rs, "HIGH_CACHE", str(tmp_path / "h.json"))
    monkeypatch.setattr(build_rs, "LOW_CACHE", str(tmp_path / "l.json"))
    from build_rs import purge_flat_carries
    # 200 stocks with a flat carry on 2025-03-18, 10 with a real move,
    # 10 absent that day (coverage <98%, like the real outage day)
    cache = {}
    for i in range(200):
        cache[f"F{i}"] = {"2025-03-17": 100.0, "2025-03-18": 100.0}
    for i in range(10):
        cache[f"M{i}"] = {"2025-03-17": 100.0, "2025-03-18": 102.0}
    for i in range(10):
        cache[f"A{i}"] = {"2025-03-17": 100.0}
    have = sorted(cache)
    purged = purge_flat_carries(cache, {}, {}, have)
    assert purged == ["2025-03-18"]
    assert "2025-03-18" not in cache["F0"]          # flat carry gone
    assert cache["M0"]["2025-03-18"] == 102.0       # real mover kept


def test_fetch_bhavcopy_blocked_returns_none(monkeypatch):
    patch_session(monkeypatch, FakeSession(FakeResp(403, text="denied")))
    assert fetch_bhavcopy("2026-08-28") is None
    assert fetch_bhav_indices("2026-08-28") is None


def test_repair_prefers_bhavcopy_and_tags_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(tmp_path / "p.json"))
    monkeypatch.setattr(build_rs, "HIGH_CACHE", str(tmp_path / "h.json"))
    monkeypatch.setattr(build_rs, "LOW_CACHE", str(tmp_path / "l.json"))
    cache = {"__BENCH__": {"2026-08-27": 20000.0}, "AAA": {"2026-08-27": 100.0}}
    monkeypatch.setattr(build_rs, "fetch_bhavcopy", lambda day: (
        {"AAA": {"close": 101.0, "high": 102.0, "low": 99.0}}
        if day == "2026-08-28" else None))
    monkeypatch.setattr(build_rs, "fetch_bhav_indices", lambda day: (
        {"Nifty 500": 20100.0} if day == "2026-08-28" else None))

    def boom(*a, **k):
        raise AssertionError("intraday must not run when bhavcopy succeeds")
    monkeypatch.setattr(build_rs, "intraday_day", boom)
    from build_rs import repair_intraday_gap
    prov = {}
    repaired = repair_intraday_gap(cache, {}, {}, ["AAA"], thresh=1,
                                   today=dt.date(2026, 8, 29), prov=prov)
    assert repaired == ["2026-08-28"]
    assert cache["AAA"]["2026-08-28"] == 101.0
    assert cache["__BENCH__"]["2026-08-28"] == 20100.0
    assert prov == {"2026-08-28": "bhavcopy"}


# --------------------------------------------------------------------------- #
#  2b. Intraday repair (Yahoo null-daily-bar gaps: Aug 28, Jul 28 patterns)
# --------------------------------------------------------------------------- #
from build_rs import intraday_day, repair_intraday_gap


def _intraday_payload(times):
    """5m-bar payload for `times`: list of (y, m, d, hour, min, close)."""
    ts, cl, hg, lw = [], [], [], []
    for y, mo, d, h, mi, c in times:
        ts.append(int(dt.datetime(y, mo, d, h, mi, tzinfo=IST).timestamp()))
        cl.append(c)
        hg.append(c + 1.0)
        lw.append(c - 1.0)
    return {"chart": {"result": [{
        "timestamp": ts,
        "indicators": {"quote": [{"close": cl, "high": hg, "low": lw}]},
    }]}}


def test_intraday_day_extracts_close_high_low(monkeypatch):
    times = [
        (2026, 8, 28, 9, 15, 100.0),
        (2026, 8, 28, 15, 25, 103.5),       # last bar of the day
        (2026, 8, 29, 9, 15, 104.0),        # next day must NOT leak in
    ]
    patch_session(monkeypatch, FakeSession(FakeResp(200, payload=_intraday_payload(times))))
    assert intraday_day("RELIANCE.NS", "2026-08-28") == (103.5, 104.5, 99.0)


def test_intraday_day_returns_none_when_day_absent(monkeypatch):
    times = [(2026, 8, 27, 9, 15, 100.0)]
    patch_session(monkeypatch, FakeSession(FakeResp(200, payload=_intraday_payload(times))))
    assert intraday_day("X.NS", "2026-08-28") is None


def test_repair_intraday_gap_fills_missing_day(monkeypatch, tmp_path):
    # NEVER let the repair persist into the real caches during tests
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(tmp_path / "price.json"))
    monkeypatch.setattr(build_rs, "HIGH_CACHE", str(tmp_path / "high.json"))
    monkeypatch.setattr(build_rs, "LOW_CACHE", str(tmp_path / "low.json"))
    cache = {"__BENCH__": {"2026-08-27": 20000.0},
             "AAA": {"2026-08-27": 100.0}, "BBB": {"2026-08-27": 50.0}}
    highs, lows = {}, {}

    def fake_intraday(ysym, day):
        if day != "2026-08-28":
            return None
        return {"AAA.NS": (101.0, 102.0, 99.0),
                "BBB.NS": (51.0, 52.0, 49.0),
                "^CRSLDX": (20100.0, 20150.0, 19950.0)}.get(ysym)

    monkeypatch.setattr(build_rs, "intraday_day", fake_intraday)
    monkeypatch.setattr(build_rs, "fetch_bhavcopy", lambda day: None)  # force intraday path
    monkeypatch.setattr(build_rs, "YH_WORKERS", 1)
    repaired = repair_intraday_gap(cache, highs, lows, ["AAA", "BBB"], thresh=1,
                                   today=dt.date(2026, 8, 29))
    assert repaired == ["2026-08-28"]
    assert cache["AAA"]["2026-08-28"] == 101.0
    assert cache["BBB"]["2026-08-28"] == 51.0
    assert cache["__BENCH__"]["2026-08-28"] == 20100.0
    assert highs["AAA"]["2026-08-28"] == 102.0
    assert lows["AAA"]["2026-08-28"] == 99.0


def test_repair_intraday_gap_skips_holiday(monkeypatch):
    cache = {"__BENCH__": {"2026-08-27": 20000.0}, "AAA": {"2026-08-27": 100.0}}
    # no intraday bars anywhere for the gap day (holiday) -> nothing filled
    monkeypatch.setattr(build_rs, "intraday_day", lambda ysym, day: None)
    monkeypatch.setattr(build_rs, "fetch_bhavcopy", lambda day: None)
    assert repair_intraday_gap(cache, {}, {}, ["AAA"], thresh=1,
                               today=dt.date(2026, 8, 29)) == []
    assert "2026-08-28" not in cache["AAA"]


# --------------------------------------------------------------------------- #
#  3. Benchmark gap-fill chain
# --------------------------------------------------------------------------- #
def _stock_cache(n, dates, start=100.0, step=1.0):
    """n synthetic stocks, each +step%/day over the given dates."""
    syms, cache = [], {}
    for i in range(n):
        s = f"S{i}"
        syms.append(s)
        cache[s] = {d: start * (1 + step / 100) ** k for k, d in enumerate(dates)}
    return syms, cache


def test_fill_prefers_investing_com_over_synthetic():
    """THE regression test for the Jul 28 incident: when Investing.com has the
    date, its real index close must win — the equal-weight synthetic (which was
    off by 135 pts that day) must not be used."""
    bench = {"2026-07-27": 23153.10}
    have, cache = _stock_cache(150, ["2026-07-27", "2026-07-28"], step=-0.749)
    inv = {"2026-07-28": 23114.900390625}
    filled = fill_benchmark_gaps(bench, cache, have, thresh=100, inv=inv)
    assert filled == [("2026-07-28", "investing.com")]
    assert bench["2026-07-28"] == pytest.approx(23114.900390625)


def test_fill_synthetic_used_when_investing_lacks_date():
    bench = {"2026-07-27": 20000.0}
    have, cache = _stock_cache(150, ["2026-07-27", "2026-07-28"], step=0.5)
    filled = fill_benchmark_gaps(bench, cache, have, thresh=100, inv={})
    assert filled == [("2026-07-28", "synthetic")]
    # 20000 * (1 + 0.5%) — every stock rose exactly 0.5%
    assert bench["2026-07-28"] == pytest.approx(20100.0, abs=0.01)


def test_fill_synthetic_averages_equal_weight_returns():
    bench = {"2026-07-27": 1000.0}
    cache = {
        **{f"A{i}": {"2026-07-27": 100.0, "2026-07-28": 110.0} for i in range(60)},   # +10%
        **{f"B{i}": {"2026-07-27": 100.0, "2026-07-28": 95.0} for i in range(60)},    # -5%
    }
    have = list(cache)
    filled = fill_benchmark_gaps(bench, cache, have, thresh=50, inv={})
    assert filled == [("2026-07-28", "synthetic")]
    # mean of +10% (60 stocks) and -5% (60 stocks) = +2.5%
    assert bench["2026-07-28"] == pytest.approx(1025.0, abs=0.01)


def test_fill_skips_date_with_too_few_stocks():
    bench = {"2026-07-27": 1000.0}
    have, cache = _stock_cache(50, ["2026-07-27", "2026-07-28"])   # < 100 stocks
    filled = fill_benchmark_gaps(bench, cache, have, thresh=10, inv={})
    assert filled == []
    assert "2026-07-28" not in bench


def test_fill_respects_coverage_threshold():
    """A date only a handful of stocks traded (e.g. a pre-listing straggler in
    history) must not be treated as a missing benchmark day."""
    bench = {"2026-07-27": 1000.0, "2026-07-28": 1001.0}
    have, cache = _stock_cache(200, ["2026-07-27", "2026-07-28"])
    cache["ODD"] = {"2026-07-27": 5.0, "2026-07-20": 5.0}   # one stock, old date
    have.append("ODD")
    filled = fill_benchmark_gaps(bench, cache, have, thresh=100, inv={})
    assert filled == []          # 2026-07-20 covered by 1 stock < thresh


def test_fill_nothing_missing_does_not_scrape(monkeypatch):
    def boom():
        raise AssertionError("scraper must not be called when nothing is missing")
    monkeypatch.setattr(build_rs, "_scrape_investing_com", boom)
    bench = {"2026-07-27": 1.0, "2026-07-28": 1.1}
    have, cache = _stock_cache(120, ["2026-07-27", "2026-07-28"])
    assert fill_benchmark_gaps(bench, cache, have, thresh=100) == []


def test_fill_skips_fake_flat_holiday_bars():
    """Yahoo's flat duplicate bars on holidays (100% of closes equal the
    previous day) must never be filled into the benchmark — they're not
    trading days."""
    from build_rs import is_fake_flat_day
    have, cache = _stock_cache(150, ["2026-06-25", "2026-06-26"])   # real days
    # add a "holiday": every stock's 06-27 bar equals its 06-26 close
    for s in have:
        cache[s]["2026-06-27"] = cache[s]["2026-06-26"]
    assert is_fake_flat_day(cache, have, "2026-06-27") is True
    bench = {"2026-06-26": 1000.0}
    assert fill_benchmark_gaps(bench, cache, have, thresh=100, inv={}) == []
    assert "2026-06-27" not in bench


def test_is_fake_flat_day_real_day_moves(monkeypatch):
    from build_rs import is_fake_flat_day
    # a real day: nearly all closes differ from the previous close
    have, cache = _stock_cache(150, ["2026-06-25", "2026-06-26"], step=1.0)
    assert is_fake_flat_day(cache, have, "2026-06-26") is False


def test_fill_chains_multiple_missing_days_from_last_known():
    """Two consecutive missing days: the second day's synthetic anchors to the
    last *originally known* benchmark close (documented behaviour)."""
    bench = {"2026-07-27": 1000.0}
    have, cache = _stock_cache(150, ["2026-07-27", "2026-07-28", "2026-07-29"], step=1.0)
    filled = fill_benchmark_gaps(bench, cache, have, thresh=100, inv={})
    assert [d for d, _ in filled] == ["2026-07-28", "2026-07-29"]
    assert bench["2026-07-28"] == pytest.approx(1010.0, abs=0.01)
    assert bench["2026-07-29"] == pytest.approx(1010.0 * 1.01, abs=0.02)


# --------------------------------------------------------------------------- #
#  4. RS maths
# --------------------------------------------------------------------------- #
def test_percentrank_inc_flat_series_is_one():
    assert percentrank_inc([5.0, 5.0, 5.0], 5.0) == 1.0


def test_percentrank_inc_extremes():
    arr = [1.0, 2.0, 3.0, 4.0]
    assert percentrank_inc(arr, 1.0) == 0.0
    assert percentrank_inc(arr, 4.0) == 1.0


def test_percentrank_inc_interpolates():
    # 2.5 sits halfway between ranks 1 and 2 of [1,2,3,4] -> (1+0.5)/3
    assert percentrank_inc([1.0, 2.0, 3.0, 4.0], 2.5) == pytest.approx(0.5)


def test_percentrank_inc_ignores_nones():
    assert percentrank_inc([None, 1.0, 2.0, 3.0], 3.0) == 1.0


# --------------------------------------------------------------------------- #
#  4a. Cache durability (the Aug 29 corruption incident: two concurrent builds
#  interleaved writes and left a cache half-garbage; the build must survive)
# --------------------------------------------------------------------------- #
def test_write_json_atomic_leaves_no_tmp(tmp_path):
    p = tmp_path / "c.json"
    build_rs.write_json_atomic(str(p), {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert not (tmp_path / "c.json.tmp").exists()


def test_load_json_cache_survives_corruption(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"a": 1, "corrupt')
    assert build_rs.load_json_cache(str(p)) == {}          # warns, returns fresh


def test_load_json_cache_missing_file(tmp_path):
    assert build_rs.load_json_cache(str(tmp_path / "nope.json")) == {}


# --------------------------------------------------------------------------- #
#  4b. RS line vs EMA21 (TradingView-style ratio = stock / benchmark)
# --------------------------------------------------------------------------- #
from build_rs import rs_ema_flag


def _series(values, start="2026-01-05"):
    """{date: value} over consecutive calendar days (gaps irrelevant here)."""
    base = dt.date.fromisoformat(start)
    return {(base + dt.timedelta(days=i)).isoformat(): v for i, v in enumerate(values)}


def test_rs_ema_flag_above_when_ratio_rising():
    bench = _series([100.0] * 60)
    stock = _series([50.0 + i * 0.5 for i in range(60)])   # steady outperformance
    assert rs_ema_flag(stock, bench) == 1


def test_rs_ema_flag_below_when_ratio_falling():
    bench = _series([100.0] * 60)
    stock = _series([80.0 - i * 0.5 for i in range(60)])   # steady underperformance
    assert rs_ema_flag(stock, bench) == 0


def test_rs_ema_flag_flat_ratio_is_above():
    bench = _series([100.0 + i for i in range(60)])
    stock = _series([2.0 * (100.0 + i) for i in range(60)])  # constant 2x ratio
    assert rs_ema_flag(stock, bench) == 1                    # >= holds on a flat line


def test_rs_ema_flag_insufficient_history():
    bench = _series([100.0] * 10)
    stock = _series([50.0] * 10)                             # < 21 common dates
    assert rs_ema_flag(stock, bench) == -1


def test_rs_ema_flag_uses_only_common_dates():
    bench = _series([100.0] * 60, start="2026-01-05")
    stock = _series([50.0 + i * 0.5 for i in range(40)], start="2026-01-25")  # joins late
    assert rs_ema_flag(stock, bench) == 1                    # 40 common dates ≥ 21


def test_rs_ema_flag_detects_recent_crossover():
    # ratio falls for 45 days then rips for 15 — latest must be back above EMA21
    bench = _series([100.0] * 60)
    stock = _series([100.0 - i for i in range(45)] + [55.0 + 4.0 * i for i in range(15)])
    assert rs_ema_flag(stock, bench) == 1


# --------------------------------------------------------------------------- #
#  5. Integration: generated artifacts (require cache + rs_data.json)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def price_cache():
    if not PRICE_CACHE.exists():
        pytest.skip("price cache not generated yet")
    with open(PRICE_CACHE) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def rs_data():
    if not RS_DATA.exists():
        pytest.skip("rs_data.json not generated yet")
    with open(RS_DATA) as f:
        return json.load(f)


def _require_synced(price_cache, rs_data):
    """Skip when the price cache moved on since the build — background updates
    make artifact-vs-cache recomputation racy."""
    ref = (rs_data["meta"].get("window_dates")
           or rs_data["breadth"]["dates"][-WINDOW:])
    if ref and max(price_cache["__BENCH__"]) != ref[-1]:
        pytest.skip("price cache updated since the build — run build_rs.py to resync")


def test_cache_jul28_2026_benchmark_value(price_cache):
    """The incident value: must be the real NIFTY 500 close (23,114.90 from
    Investing.com), not the wrong equal-weight synthetic 22,979.79."""
    bench = price_cache["__BENCH__"]
    assert "2026-07-28" in bench, "Jul 28 missing from benchmark — gap not filled"
    assert bench["2026-07-28"] == pytest.approx(23114.90, abs=0.5)
    assert abs(bench["2026-07-28"] - 22979.79) > 1.0, "stale synthetic fill still cached"


def test_cache_benchmark_recent_values_match_investing(price_cache):
    """End-to-end: live-scrape Investing.com and cross-check the last ~3 weeks
    of cached benchmark closes against it.  Any new Yahoo gap must have been
    filled with the *real* close."""
    inv = _scrape_investing_com()
    if not inv:
        pytest.skip("Investing.com unreachable from this network")
    bench = price_cache["__BENCH__"]
    mismatches = {
        d: (bench[d], v) for d, v in inv.items()
        if d in bench and abs(bench[d] - v) >= 0.5
    }
    assert not mismatches, f"benchmark cache disagrees with Investing.com: {mismatches}"


def test_rs_data_structure(rs_data):
    assert set(rs_data) == {"meta", "breadth", "rotation", "levels"}
    assert rs_data["meta"]["n_stocks"] > 2000
    assert [lv["key"] for lv in rs_data["levels"]] == ["macro", "sector", "industry", "basic"]
    b = rs_data["breadth"]
    assert len(b["dates"]) == len(b["osc"]) > 400
    assert all(isinstance(o, (int, float)) for o in b["osc"])


def test_breadth_dates_strictly_increasing(rs_data):
    dates = rs_data["breadth"]["dates"]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)


def test_breadth_has_no_trading_day_gaps(rs_data):
    """Consecutive breadth points never span more than 4 calendar days (covers
    weekends + a holiday).  This is the check that would have caught the
    missing Jul 28."""
    dates = [dt.date.fromisoformat(d) for d in rs_data["breadth"]["dates"][-90:]]
    gaps = {(p, n): (n - p).days for p, n in zip(dates, dates[1:]) if (n - p).days > 4}
    assert not gaps, f"breadth has trading-day gaps: {gaps}"


def test_rs_window_alignment_and_scores(rs_data):
    """Every group and every member stock has a WINDOW-length RS series and a
    percentile score in [0, 1] (fractional PERCENTRANK.INC).
    `n` = constituents present on the window base date (feeds the group index);
    `members` = stocks with data on every window date — so n >= len(members):
    stocks with suspension gaps inside the window count in n but get no row."""
    for lvl in rs_data["levels"]:
        assert lvl["groups"], f"{lvl['key']} has no groups"
        for g in lvl["groups"]:
            assert len(g["r"]) == WINDOW, (lvl["key"], g["name"])
            assert 0.0 <= g["pct"] <= 1.0 + 1e-9
            assert g["n"] >= len(g["members"]) > 0, (lvl["key"], g["name"])
            for m in g["members"]:
                assert len(m["r"]) == WINDOW, (g["name"], m["s"])
                assert 0.0 <= m["p"] <= 1.0 + 1e-9


def test_meta_drange_end_matches_breadth_last_date(rs_data):
    end = rs_data["meta"]["drange"].split(" → ")[-1]
    assert end == rs_data["breadth"]["dates"][-1]


def test_macro_breadth_present_and_aligned(rs_data):
    """Every macro has a breadth oscillator aligned to the main breadth dates."""
    b = rs_data["breadth"]
    macros = b.get("macros", [])
    assert len(macros) >= 10, [m["name"] for m in macros]   # grows with the universe
    names = sorted(m["name"] for m in macros)
    assert "Financial Services" in names and "Information Technology" in names
    for m in macros:
        assert len(m["dates"]) == len(m["osc"]) == len(b["dates"])
        assert m["dates"] == b["dates"], m["name"]
        assert abs(m["latest"] - m["osc"][-1]) <= 0.0051  # latest is rounded 2dp


def test_macro_breadth_math(price_cache, rs_data):
    """A macro whose stocks mostly advanced recently must have a positive
    latest oscillator; independent recomputation matches the stored series."""
    _require_synced(price_cache, rs_data)
    from build_rs import compute_macro_breadth
    # rebuild from the real caches and compare with the stored series
    import csv
    with open(ROOT / 'nse_stock_master.csv') as f:
        universe = list(csv.DictReader(f))
    n_with_px = sum(1 for u in universe if price_cache.get(u["symbol"]))
    if n_with_px != rs_data["meta"].get("n_stocks"):
        pytest.skip("price cache changed since the build — run build_rs.py to resync")
    for u in universe:
        u["sym"] = u["symbol"]
        u["macro"] = u.get("macro") or ""
    # covered_dates for compute_macro_breadth = dates + warm-up (39 trimmed at start)
    # reconstruct the full covered list from the caches
    cov = {}
    for s, ser in price_cache.items():
        if s == "__BENCH__":
            continue
        for d in ser:
            cov[d] = cov.get(d, 0) + 1
    n_stocks = sum(1 for s in price_cache if s != "__BENCH__" and price_cache[s])
    covered = sorted(d for d, n in cov.items() if n >= n_stocks // 2)
    macros = compute_macro_breadth(universe, price_cache, covered)
    stored = {m["name"]: m for m in rs_data["breadth"]["macros"]}
    assert len(macros) >= 10
    for m in macros[:4]:
        st = stored[m["name"]]
        assert m["dates"] == st["dates"]
        assert [round(v, 2) for v in m["osc"]] == [round(v, 2) for v in st["osc"]]
        assert abs(m["latest"] - st["latest"]) < 0.01


def test_window_coverage_consistent(rs_data, price_cache):
    """n_stocks (universe) ≥ n_window (stocks in the levels), and every
    excluded stock genuinely lacks ≥1 of the 26 window dates — i.e. no stock
    with complete window data is silently dropped."""
    meta = rs_data["meta"]
    union = {m["s"] for lvl in rs_data["levels"] for g in lvl["groups"] for m in g["members"]}
    assert len(union) == meta["n_window"], (len(union), meta["n_window"])
    assert 0 < meta["n_window"] <= meta["n_stocks"]
    assert len(meta["excluded"]) == meta["n_stocks"] - meta["n_window"]
    assert len(set(meta["excluded"])) == len(meta["excluded"])

    ref_dates = rs_data["meta"].get("window_dates") or rs_data["breadth"]["dates"][-WINDOW:]
    bench = price_cache["__BENCH__"]
    if ref_dates and max(bench) != ref_dates[-1]:
        pytest.skip("price cache updated since the build — run build_rs.py to resync")
    for s in meta["excluded"][:50]:
        ser = price_cache.get(s, {})
        missing_day = any(d not in ser or not ser[d] for d in ref_dates)
        # corporate-action break inside the window also justifies exclusion
        cor_break = bool(build_rs.last_break_date(
            {d: ser[d] for d in ref_dates if d in ser}, len(ref_dates)))
        assert missing_day or cor_break, (
            f"{s} excluded but has every window date and no break — investigate")


def test_members_have_rs_ema21_flag(rs_data, price_cache):
    """Every member carries the RS-line-vs-EMA21 flag ('b' in {-1, 0, 1}), and
    an independent recomputation from the raw caches agrees with it."""
    from build_rs import rs_ema_flag
    bench = price_cache["__BENCH__"]
    seen, checked = {1: 0, 0: 0, -1: 0}, 0
    for lvl in rs_data["levels"]:
        for g in lvl["groups"]:
            for m in g["members"]:
                assert m["b"] in (-1, 0, 1), (lvl["key"], g["name"], m["s"], m.get("b"))
                seen[m["b"]] += 1
    assert seen[1] > 0 and seen[0] > 0
    _require_synced(price_cache, rs_data)
    # spot-verify a deterministic sample straight from the caches
    for lvl in rs_data["levels"]:
        for g in lvl["groups"][::17]:
            for m in g["members"][:1]:
                expect = rs_ema_flag(price_cache[m["s"]], bench)
                assert m["b"] == expect, (m["s"], m["b"], expect)
                checked += 1
    assert checked >= 10


def test_rs_pct_extreme_semantics(rs_data):
    """RS_STS% is the percentile rank of the latest RS within its own window:
    0% must mean "latest is the window minimum", 100% "latest is the window
    maximum" (tolerance covers the 3-decimal display rounding of the series)."""
    tol = 2e-3
    n0 = n1 = 0
    for lvl in rs_data["levels"]:
        for g in lvl["groups"]:
            if g["pct"] <= 0.001:
                assert g["r"][-1] <= min(g["r"]) + tol, (lvl["key"], g["name"])
                n0 += 1
            if g["pct"] >= 0.999:
                assert g["r"][-1] >= max(g["r"]) - tol, (lvl["key"], g["name"])
                n1 += 1
    assert n0 > 0 and n1 > 0   # both extremes must exist somewhere in the data


def test_rs_pct_matches_full_precision_recompute(price_cache, rs_data):
    """The stored pct is computed from the FULL-PRECISION RS series (the stored
    series itself is rounded to 3 decimals for display).  Recompute a sample of
    members straight from the raw price cache and demand an exact match."""
    _require_synced(price_cache, rs_data)
    from build_rs import equal_weight_rs, percentrank_inc, WINDOW
    bench = price_cache["__BENCH__"]
    have = [s for s in price_cache if s != "__BENCH__" and price_cache[s]]
    thresh = max(1, int(0.5 * len(have)))
    covered = [d for d in sorted(bench)
               if sum(1 for s in have if d in price_cache[s]) >= thresh]
    ref_dates = covered[-WINDOW:]

    sample = []   # deterministic sample: first member of every 13th group
    for lvl in rs_data["levels"]:
        for i, g in enumerate(lvl["groups"]):
            if i % 13 == 0 and g["members"]:
                m = g["members"][0]
                sample.append((lvl["key"], g["name"], m["s"], m["p"]))
    assert len(sample) >= 15
    for key, gname, sym, stored in sample:
        srs, _ = equal_weight_rs([price_cache[sym]], bench, ref_dates)
        full = round(percentrank_inc(srs, srs[-1]), 4)
        assert full == pytest.approx(stored, abs=1e-9), (key, gname, sym, stored, full)
