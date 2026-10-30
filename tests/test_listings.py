"""Tests for new-listing / rename / delisting handling and per-stock gap fills."""
import csv

import pytest

import build_rs
import refresh_classification as rc


def _row(sym, isin, macro=""):
    r = {k: "" for k in rc.FIELDS}
    r.update(symbol=sym, company=sym + " Ltd", series="EQ", isin=isin, macro=macro)
    return r


def _live(*pairs):
    return {s: {"symbol": s, "company": s + " Ltd", "series": "EQ", "isin": i}
            for s, i in pairs}


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "MASTER", str(tmp_path / "master.csv"))
    monkeypatch.setattr(rc, "CHANGES", str(tmp_path / "changes.csv"))
    monkeypatch.setattr(rc, "DELISTED", str(tmp_path / "delisted.csv"))


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_reconcile_renames_merges_and_archives(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    master = [_row("KEEP", "I1", "Energy"),
              _row("OLDNAME", "I2", "Finance"),      # renamed → NEWNAME (not in master)
              _row("OLDDUP", "I3", "Telecom"),       # renamed → NEWDUP (stub already added)
              _row("NEWDUP", "I3"),
              _row("GONE", "I4", "Metals")]          # delisted
    filler = [(f"F{i}", f"FI{i}") for i in range(30)]   # clear the truncation guard
    master += [_row(s, i) for s, i in filler]
    live = _live(("KEEP", "I1"), ("NEWNAME", "I2"), ("NEWDUP", "I3"), *filler)
    out = rc.reconcile(master, live)
    by = {r["symbol"]: r for r in out if not r["symbol"].startswith("F")}
    assert sorted(by) == ["KEEP", "NEWDUP", "NEWNAME"]
    assert by["NEWNAME"]["macro"] == "Finance"      # classification carried over
    assert by["NEWDUP"]["macro"] == "Telecom"       # empty stub filled from the old row
    assert [(c["old"], c["new"]) for c in _read(rc.CHANGES)] == [
        ("OLDNAME", "NEWNAME"), ("OLDDUP", "NEWDUP")]
    gone = _read(rc.DELISTED)
    assert [g["symbol"] for g in gone] == ["GONE"] and gone[0]["macro"] == "Metals"
    assert [r["symbol"] for r in _read(rc.MASTER)] == [r["symbol"] for r in out]


def test_reconcile_skips_truncated_list(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    master = [_row(f"S{i}", f"I{i}") for i in range(10)]
    out = rc.reconcile(master, _live(("S0", "I0")))
    assert out is master
    assert not (tmp_path / "delisted.csv").exists()


def test_stitch_renamed_prepends_history_only():
    cache = {"OLD": {"2026-01-01": 10.0, "2026-01-02": 11.0, "2026-01-03": 99.0},
             "NEW": {"2026-01-03": 12.0, "2026-01-04": 13.0}}
    build_rs.stitch_renamed((cache,), [("OLD", "NEW")])
    assert cache["NEW"] == {"2026-01-01": 10.0, "2026-01-02": 11.0,
                            "2026-01-03": 12.0, "2026-01-04": 13.0}


def _official(prices):
    """fake fetch_bhavcopy over {day: {sym: close}} (high/low = close ± 1)."""
    def fetch(day):
        rows = prices.get(day)
        return {s: {"close": c, "high": c + 1, "low": c - 1}
                for s, c in rows.items()} if rows else None
    return fetch


def test_fill_stock_gaps_fills_holes_not_suspensions(tmp_path, monkeypatch):
    for name in ("PRICE_CACHE", "HIGH_CACHE", "LOW_CACHE"):
        monkeypatch.setattr(build_rs, name, str(tmp_path / f"{name}.json"))
    days = ["2026-10-27", "2026-10-28", "2026-10-29"]
    cache = {"__BENCH__": {d: 1.0 for d in days},
             "HOLE": {"2026-10-27": 1.0, "2026-10-29": 3.0},     # 28th missing
             "LATEST": {"2026-10-27": 1.0, "2026-10-28": 2.0},   # 29th missing
             "SUSP": {"2026-10-27": 1.0}}                         # suspended
    monkeypatch.setattr(build_rs, "fetch_bhavcopy", _official({
        "2026-10-27": {"HOLE": 1.0, "LATEST": 1.0, "SUSP": 1.0},
        "2026-10-28": {"HOLE": 2.0, "LATEST": 2.0},
        "2026-10-29": {"HOLE": 3.0, "LATEST": 2.5}}))
    highs, lows = {}, {}
    filled = build_rs.fill_stock_gaps(cache, highs, lows, ["HOLE", "LATEST", "SUSP"],
                                      today="2026-10-30")
    assert filled == {"2026-10-28": 1, "2026-10-29": 1}
    assert cache["HOLE"]["2026-10-28"] == 2.0 and highs["HOLE"]["2026-10-28"] == 3.0
    assert cache["LATEST"]["2026-10-29"] == 2.5
    assert "2026-10-28" not in cache["SUSP"]          # no later bar → not a hole


def test_official_fill_follows_yahoo_split_adjustment(tmp_path, monkeypatch):
    """The bhavcopy is RAW, Yahoo's history split/bonus-ADJUSTED: a filled bar
    must be scaled to Yahoo's level (HDFCBANK 1:1 bonus: 1732 raw → 866), and
    re-scaled when Yahoo later adjusts its history again."""
    for name in ("PRICE_CACHE", "HIGH_CACHE", "LOW_CACHE"):
        monkeypatch.setattr(build_rs, name, str(tmp_path / f"{name}.json"))
    cache = {"__BENCH__": {"2025-03-17": 1.0, "2025-03-18": 1.0, "2025-03-19": 1.0},
             "HDFC": {"2025-03-17": 855.2, "2025-03-19": 872.05}}   # Yahoo: adjusted
    monkeypatch.setattr(build_rs, "fetch_bhavcopy", _official({
        "2025-03-17": {"HDFC": 1710.4}, "2025-03-18": {"HDFC": 1732.2},
        "2025-03-19": {"HDFC": 1744.1}}))                           # NSE: raw
    highs, lows = {}, {}
    build_rs.fill_stock_gaps(cache, highs, lows, ["HDFC"], today="2025-03-20",
                             extra_days=["2025-03-18"])
    assert cache["HDFC"]["2025-03-18"] == pytest.approx(866.1, abs=0.01)
    # a later 1:2 split: Yahoo re-adjusts its own bars; ours must follow
    cache["HDFC"] = {d: v / 2 for d, v in cache["HDFC"].items() if d != "2025-03-18"}
    build_rs.fill_stock_gaps(cache, highs, lows, ["HDFC"], today="2025-03-20")
    assert cache["HDFC"]["2025-03-18"] == pytest.approx(433.05, abs=0.01)


def test_sync_holidays_adds_weekdays_only(tmp_path, monkeypatch):
    path = tmp_path / "hol.csv"
    path.write_text("date,description\n2026-12-25,Christmas\n")
    monkeypatch.setattr(rc, "HOLIDAYS", str(path))

    class Resp:
        status_code = 200

        def json(self):
            return {"CM": [{"tradingDate": "25-Dec-2026", "description": "Christmas"},
                           {"tradingDate": "26-Jan-2027", "description": "Republic Day"},
                           {"tradingDate": "07-Nov-2027", "description": "Muhurat (Sun)"}]}

    monkeypatch.setattr(rc.requests, "get", lambda *a, **k: Resp())
    rc.sync_holidays()
    assert [r["date"] for r in _read(path)] == ["2026-12-25", "2027-01-26"]


def test_standard_name_spelling():
    from rs_engine.config import standard_name as s
    assert s("Port & Port services") == "Port & Port Services"
    assert s("Gems Jewellery And Watches") == "Gems Jewellery and Watches"
    assert s("Agricultural Food & other Products") == "Agricultural Food & Other Products"
    assert s("HEALTHCARE") == "Healthcare"
    assert s("IT - Services") == "IT - Services"                 # acronyms kept
    assert s("Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO)") \
        == "Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO)"
    assert s("Dealers���Commercial Vehicles") == "Dealers - Commercial Vehicles"
    assert s("") == ""


def test_normalise_applies_overrides_and_spelling(tmp_path, monkeypatch):
    ov = tmp_path / "ov.csv"
    ov.write_text("symbol,macro,sector,industry,basicIndustry,note\n"
                  "OLDSCHEME,Industrials,Capital Goods,Industrial Products,Castings,x\n")
    monkeypatch.setattr(rc, "OVERRIDES", str(ov))
    legacy = _row("OLDSCHEME", "I1", "MANUFACTURING")
    spelling = _row("PORT", "I2", "Services")
    spelling["basicIndustry"] = "Port & Port services"
    fine = _row("FINE", "I3", "Energy")
    master = [legacy, spelling, fine]
    assert rc.normalise(master) == 2
    assert legacy["macro"] == "Industrials" and legacy["basicIndustry"] == "Castings"
    assert spelling["basicIndustry"] == "Port & Port Services"
    assert rc.normalise(master) == 0                               # idempotent


def test_retired_scheme_counts_as_unclassified():
    assert not rc.is_classified(_row("A", "I", "MANUFACTURING"))
    assert not rc.is_classified(_row("B", "I", ""))
    assert rc.is_classified(_row("C", "I", "Healthcare"))


def test_standard_company_keeps_acronyms():
    from rs_engine.config import standard_company as f
    assert f("ANDHRA PAPER LIMITED") == "Andhra Paper Limited"
    assert f("GMR AIRPORTS LIMITED") == "GMR Airports Limited"          # acronym
    assert f("DMCC SPECIALITY CHEMICALS LIMITED") == "DMCC Speciality Chemicals Limited"
    assert f("GLOBE ENTERPRISES (INDIA) LIMITED") == "Globe Enterprises (India) Limited"
    assert f("DHARAN INFRA-EPC LIMITED") == "Dharan Infra-EPC Limited"
    assert f("SKY GOLD AND DIAMONDS LIMITED") == "Sky Gold and Diamonds Limited"
    assert f("HDFC Bank Limited") == "HDFC Bank Limited"                # mixed: untouched
