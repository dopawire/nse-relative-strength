"""Tests for audit_data.py — the daily integrity audit."""
import json
import datetime as dt

import build_rs
import audit_data


def test_stale_check_current(tmp_path, monkeypatch):
    p = tmp_path / "price.json"
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(p))
    today = dt.datetime.now(build_rs.IST).date()
    p.write_text(json.dumps({"__BENCH__": {today.isoformat(): 1.0}}))
    assert audit_data.check_data_covers_latest_session() == []


def test_stale_check_detects_gap(tmp_path, monkeypatch):
    p = tmp_path / "price.json"
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(p))
    p.write_text(json.dumps({"__BENCH__": {"2020-01-02": 1.0}}))
    issues = audit_data.check_data_covers_latest_session()
    assert issues and "stale" in issues[0]


def test_stale_check_unreadable_cache(tmp_path, monkeypatch):
    p = tmp_path / "price.json"
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(p))
    p.write_text("{corrupt")
    issues = audit_data.check_data_covers_latest_session()
    assert issues  # must not crash


def test_stale_check_before_close_requires_previous_session(tmp_path, monkeypatch):
    """Before today's session ends, the PREVIOUS session must be present —
    the morning catch-up cron relies on this to rebuild a missed evening."""
    p = tmp_path / "price.json"
    monkeypatch.setattr(build_rs, "PRICE_CACHE", str(p))

    class FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 30, 6, 0, tzinfo=tz)   # Fri 06:00 IST

    monkeypatch.setattr(audit_data.dt, "datetime", FakeDT)
    p.write_text(json.dumps({"__BENCH__": {"2026-10-28": 1.0}}))
    issues = audit_data.check_data_covers_latest_session()
    assert issues and "2026-10-29" in issues[0]
    p.write_text(json.dumps({"__BENCH__": {"2026-10-29": 1.0}}))
    assert audit_data.check_data_covers_latest_session() == []


def test_latest_session_skips_weekend_and_waits_for_close():
    from rs_engine.config import latest_session, IST
    assert latest_session(dt.datetime(2026, 10, 30, 17, 0, tzinfo=IST)) == "2026-10-30"
    assert latest_session(dt.datetime(2026, 10, 30, 9, 0, tzinfo=IST)) == "2026-10-29"
    assert latest_session(dt.datetime(2026, 11, 1, 12, 0, tzinfo=IST)) == "2026-10-30"  # Sun


def test_holiday_calendar_flags_missing_next_year(monkeypatch):
    monkeypatch.setattr(audit_data, "load_holidays", lambda: {"2026-12-25"})
    assert audit_data.check_holiday_calendar(dt.date(2026, 11, 30)) == []
    assert "2027" in audit_data.check_holiday_calendar(dt.date(2026, 12, 1))[0]
    monkeypatch.setattr(audit_data, "load_holidays", lambda: {"2027-01-26"})
    assert audit_data.check_holiday_calendar(dt.date(2026, 12, 1)) == []


def test_coverage_ignores_symbols_outside_universe():
    cache = {"__BENCH__": {}, "LIVE": {"d": 1.0}, "DELISTED": {"d": 1.0}}
    assert audit_data._have(cache) == ["LIVE", "DELISTED"]
    assert audit_data._have(cache, ["LIVE", "NOPRICES"]) == ["LIVE"]


def test_classification_check_flags_retired_scheme_and_spelling(tmp_path, monkeypatch):
    p = tmp_path / "master.csv"
    p.write_text("symbol,company,series,isin,macro,sector,industry,basicIndustry\n"
                 "OK,a,EQ,I1,Energy,Oil Gas & Consumable Fuels,Gas,LPG/CNG/PNG/LNG Supplier\n"
                 "OLD,b,EQ,I2,MANUFACTURING,AUTOMOBILE,AUTO ANCILLARIES,AUTO ANCILLARIES\n"
                 "CASE,c,EQ,I3,Services,Services,Transport Infrastructure,Port & Port services\n")
    monkeypatch.setattr(build_rs, "MASTER_CSV", str(p))
    issues = audit_data.check_classification()
    assert any("OLD" in i and "retired" in i for i in issues)
    assert any("CASE" in i and "Port & Port services" in i for i in issues)
    assert not any(i.startswith("OK:") for i in issues)
