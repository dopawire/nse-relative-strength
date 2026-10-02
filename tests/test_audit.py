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
