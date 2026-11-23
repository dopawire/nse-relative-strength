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
