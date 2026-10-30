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
