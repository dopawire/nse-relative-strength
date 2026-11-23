"""Tests for new-listing / rename / delisting handling and per-stock gap fills."""
import csv
import datetime as dt

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
    prices = {"__BENCH__": {"2026-11-17": 1.0}}          # GONE has no prices: stopped
    out = rc.reconcile(master, live, prices=prices)
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


def test_period_return_and_corporate_action_guard():
    from rs_engine.maths import period_return
    days = [f"2026-10-{d:02d}" for d in range(1, 31)]
    ser = {d: 100.0 + i for i, d in enumerate(days)}          # 30 bars
    assert period_return(ser, 21) == pytest.approx((129 / 108 - 1) * 100)
    assert period_return(ser, 63) is None                      # too short
    ser[days[-5]] = ser[days[-6]] * 3                          # +200% "day" inside
    assert period_return(ser, 21) is None                      # demerger ≠ gain


def test_cap_class_by_index_and_history():
    caps = {"TCS": "Large", "PERSISTENT": "Mid", "KAYNES": "Small"}
    assert build_rs.cap_class("TCS", caps, 500) == "Large"
    assert build_rs.cap_class("OLDCO", caps, 62) == "Micro"      # e.g. moved from BSE
    assert build_rs.cap_class("JPL", caps, 15) == "New"          # < 1 month: no class


def test_cap_classes_not_rewritten_from_a_partial_download(tmp_path, monkeypatch):
    path = tmp_path / "caps.csv"
    path.write_text("symbol,cap\nTCS,Large\n")
    monkeypatch.setattr(rc, "CAP_CLASSES", str(path))

    class Resp:
        def __init__(self, n):
            self.status_code, self.text = 200, "Symbol\n" + "\n".join(f"S{i}" for i in range(n))

    sizes = iter([100, 150, 12])                              # smallcap list truncated
    monkeypatch.setattr(rc.requests, "get", lambda *a, **k: Resp(next(sizes)))
    rc.sync_cap_classes()
    assert path.read_text() == "symbol,cap\nTCS,Large\n"      # unchanged
    sizes = iter([100, 150, 250])
    rc.sync_cap_classes()
    rows = _read(path)
    assert len(rows) == 500 and {r["cap"] for r in rows} == {"Large", "Mid", "Small"}


def test_reconcile_keeps_listed_off_list_stocks_that_still_trade(tmp_path, monkeypatch):
    """NSE's list drops thin BE/BZ stocks on some days: a stock missing from it
    but still printing prices stays; a frozen / silent one is archived; with no
    price data nothing is archived."""
    _patch_paths(tmp_path, monkeypatch)
    bench = {f"2026-11-{d:02d}": 1.0 for d in range(2, 18) if dt.date(2026, 11, d).weekday() < 5}
    days = sorted(bench)
    prices = {"__BENCH__": bench,
              "THIN": {d: 10.0 + (i % 3) for i, d in enumerate(days)},      # trades
              "FROZEN": {d: 5.0 for d in days},                              # carry
              "SILENT": {d: 7.0 + i for i, d in enumerate(days[:3])}}        # stopped
    filler = [(f"F{i}", f"FI{i}") for i in range(30)]
    master = [_row("THIN", "I1", "Energy"), _row("FROZEN", "I2", "Energy"),
              _row("SILENT", "I3", "Energy")] + [_row(s, i) for s, i in filler]
    live = _live(*filler)
    out = {r["symbol"] for r in rc.reconcile(list(master), live, prices=prices)}
    assert "THIN" in out and not {"FROZEN", "SILENT"} & out
    assert [r["symbol"] for r in _read(rc.DELISTED)] == ["FROZEN", "SILENT"]
    assert {r["symbol"] for r in rc.reconcile(list(master), live, prices=None)} >= {"FROZEN", "SILENT"}


def test_archived_stock_comes_back_with_its_classification(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    (tmp_path / "delisted.csv").write_text(
        ",".join(rc.FIELDS + ["delisted_on"]) + "\n"
        "LASA,Lasa Ltd,BE,INE670X01014,Healthcare,Healthcare,Pharmaceuticals & Biotechnology,"
        "Pharmaceuticals,2026-11-03\n")
    master = []
    rc.add_stubs(master, _live(("LASA", "INE670X01014")), ["LASA"])
    assert master[0]["macro"] == "Healthcare" and rc.is_classified(master[0])
    assert _read(rc.DELISTED) == []                    # left the archive


def test_find_bad_bars_only_flags_isolated_mismatches():
    """A single wrong Yahoo close (neighbours agree with NSE) is flagged; an
    adjusted history (every earlier bar scaled alike) and a missing bhavcopy
    row are not."""
    import build_rs as b
    days = ["2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23"]
    nse = {d: 100.0 + i for i, d in enumerate(days)}
    cache = {"__BENCH__": {d: 1 for d in days},
             "BAD": dict(nse), "ADJ": {d: v * 0.9 for d, v in nse.items()}, "THIN": dict(nse)}
    cache["BAD"]["2026-11-20"] = nse["2026-11-19"]           # copy of the day before
    cache["ADJ"]["2026-11-23"] = nse["2026-11-23"]           # ex-date today: older bars scaled
    cache["THIN"]["2026-11-19"] = 50.0
    bhav = {d: {"BAD": {"close": nse[d]}, "ADJ": {"close": nse[d]}} for d in days}

    bad = b.find_bad_bars(cache, ["BAD", "ADJ", "THIN"], {}, bhav.get, sessions=4)
    assert bad == {"2026-11-20": ["BAD"]}
    # already recorded → not flagged again
    assert b.find_bad_bars(cache, ["BAD"], {"BAD": {"2026-11-20": []}}, bhav.get, 4) == {}
