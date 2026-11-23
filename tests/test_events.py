"""Upcoming corporate events (rs_engine.events)."""
from rs_engine import events


def test_parse_merges_rows_and_shortens_purpose():
    rows = [{"bm_symbol": "BCSSL", "bm_date": "23-Nov-2026", "bm_purpose": "Board Meeting Intimation"},
            {"bm_symbol": "BCSSL", "bm_date": "23-Nov-2026", "bm_purpose": "Financial Results"},
            {"symbol": "ENRIN", "date": "25-Nov-2026", "purpose": "Financial Results/Dividend/Other business matters"},
            {"bm_symbol": "HDBFS", "bm_date": "23-Nov-2026", "bm_purpose": "Board Meeting Intimation"},
            {"bm_symbol": "BAD", "bm_date": "not a date"}]
    ev = events.parse_nse(rows)
    assert ev == {("BCSSL", "2026-11-23"): "Results",
                  ("ENRIN", "2026-11-25"): "Results, Dividend",
                  ("HDBFS", "2026-11-23"): "Board meeting"}


def test_next_events_window_and_results_flag():
    ev = {("A", "2026-11-23"): "Results",          # on the as-of day: already out
          ("A", "2026-11-26"): "Dividend",
          ("A", "2026-12-01"): "Results",
          ("B", "2026-12-20"): "Results"}           # beyond 14 days
    nxt = events.next_events(ev, "2026-11-23")
    assert nxt == {"A": "2026-11-26 Dividend"}
    assert events.is_results("2026-12-01 Results, Dividend") and not events.is_results("2026-11-26 Dividend")


def test_merge_keeps_recent_past_and_replaces_future(tmp_path):
    old = {("A", "2026-11-10"): "Results", ("A", "2026-11-20"): "Results", ("B", "2026-11-30"): "Results"}
    new = {("C", "2026-11-28"): "Results"}
    out = events.merge(old, new, "2026-11-23")
    assert out == {("A", "2026-11-20"): "Results", ("C", "2026-11-28"): "Results"}
    p = str(tmp_path / "ev.csv")
    events.write_events(out, p)
    assert events.read_events(p) == out


def test_refresh_events_main(tmp_path, monkeypatch):
    import datetime as dt
    import refresh_events as re_
    from rs_engine.config import IST
    d1 = dt.datetime.now(IST).date() + dt.timedelta(days=7)
    d2 = d1 + dt.timedelta(days=1)

    class R:
        status_code = 200

        def __init__(self, rows):
            self.rows = rows

        def json(self):
            return self.rows

    class S:
        headers = {}

        def get(self, url, timeout, headers=None):
            if "past-issues" in url:
                return R([{"symbol": "NEWIPO", "securityType": "Equity",
                           "listingDate": "03-NOV-2026", "issuePrice": "150"}])
            if "board-meetings" in url:
                return R([{"bm_symbol": "AAA", "bm_date": d1.strftime("%d-%b-%Y"), "bm_purpose": "Financial Results"}])
            return R([{"symbol": "BBB", "date": d2.strftime("%d-%b-%Y"), "purpose": "Dividend"}])
    monkeypatch.setattr(events, "EVENTS", str(tmp_path / "ev.csv"))
    from rs_engine import ipos
    monkeypatch.setattr(ipos, "IPOS", str(tmp_path / "ipos.csv"))
    monkeypatch.setattr(re_.requests, "Session", S)
    assert re_.main() == 0
    assert ipos.read()["NEWIPO"] == {"listed": "2026-11-03", "price": 150.0}
    ev = events.read_events()
    assert ev[("AAA", d1.isoformat())] == "Results" and ev[("BBB", d2.isoformat())] == "Dividend"


def test_parse_ipos_mainboard_only(tmp_path):
    from rs_engine import ipos
    rows = [{"symbol": "JPL", "securityType": "Equity", "listingDate": "28-OCT-2026", "issuePrice": "  1119"},
            {"symbol": "SMEX", "securityType": "SME", "listingDate": "28-OCT-2026", "issuePrice": "50"},
            {"symbol": "SOON", "securityType": "Equity", "listingDate": "-", "issuePrice": "-"},
            {"symbol": "OLD", "securityType": "Equity", "listingDate": "18-Sep-2012", "issuePrice": None}]
    got = ipos.parse_nse(rows)
    assert got == {"JPL": {"listed": "2026-10-28", "price": 1119.0},
                   "OLD": {"listed": "2012-09-18", "price": None}}
    p = str(tmp_path / "ipos.csv")
    ipos.write(got, p)
    assert ipos.read(p) == got


def test_read_ipos_follows_renames(tmp_path, monkeypatch):
    import build_rs as B
    from rs_engine import ipos
    p = str(tmp_path / "ipos.csv")
    ipos.write({"OLDSYM": {"listed": "2026-05-01", "price": 100.0}}, p)
    monkeypatch.setattr(ipos, "IPOS", p)
    assert B.read_ipos([("OLDSYM", "NEWSYM")]) == {"NEWSYM": {"listed": "2026-05-01", "price": 100.0}}
