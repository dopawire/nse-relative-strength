"""FII / DII flows: parsing, merging without double counting, chart rows."""
from rs_engine import flows

ROW = "<tr><td>{}</td>" + "<td>{}</td>" * 6 + "</tr>"


def _rec(fn, dn):
    return {"fii_buy": 100.0 + max(fn, 0), "fii_sell": 100.0 - min(fn, 0), "fii_net": float(fn),
            "dii_buy": 50.0 + max(dn, 0), "dii_sell": 50.0 - min(dn, 0), "dii_net": float(dn)}


def test_parse_kotak_months_and_days():
    html = ("<table><tr><th>Date</th><th>Gross Purchase</th></tr>"
            "<tr><td>Month till date</td>" + "<td>1</td>" * 7 + "</tr>"
            + ROW.format("19-Nov-2026", "20,706.95", "13,295.54", "7,411.41", "17,651.50", "19,008.07", "-1,356.57")
            + "</table><table>"
            + ROW.format("Nov 2026", "2,84,582.29", "1,82,941.57", "1,01,640.72", "2,07,668.94", "2,64,596.17", "-56,927.23")
            + ROW.format("Jun 2014", "99,658.61", "92,134.14", "7,524.47", "31,605.44", "36,209.79", "-4,604.35")
            + "</table>")
    months, days = flows.parse_kotak(html)
    assert set(months) == {"2026-11", "2014-06"}
    assert months["2026-11"]["fii_net"] == 101640.72 and months["2026-11"]["dii_net"] == -56927.23
    assert days == {"2026-11-19": {"fii_buy": 20706.95, "fii_sell": 13295.54, "fii_net": 7411.41,
                                   "dii_buy": 17651.5, "dii_sell": 19008.07, "dii_net": -1356.57}}


def test_parse_nse():
    rows = [{"buyValue": "17651.5", "category": "DII", "date": "19-Nov-2026",
             "netValue": "-1356.57", "sellValue": "19008.07"},
            {"buyValue": "20706.95", "category": "FII/FPI", "date": "19-Nov-2026",
             "netValue": "7411.41", "sellValue": "13295.54"}]
    d = flows.parse_nse(rows)
    assert d["2026-11-19"]["fii_net"] == 7411.41 and d["2026-11-19"]["dii_buy"] == 17651.5
    assert flows.parse_nse([rows[0]]) == {}          # one side only → incomplete


def _kotak_months(n=flows.MIN_MONTHS):
    ms = {}
    y, m = 2014, 6
    for _ in range(n):
        ms[f"{y}-{m:02d}"] = _rec(10, 5)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return ms


def test_merge_kotak_replaces_and_adds_newer_nse_day():
    km = _kotak_months()
    last_m = max(km)
    kd = {f"{last_m}-03": _rec(10, 5)}
    nd = {f"{last_m}-04": _rec(7, -2)}               # Kotak not updated yet
    months, days = flows.merge({}, {}, km, kd, nd)
    assert months[last_m]["fii_net"] == 17 and months[last_m]["dii_net"] == 3
    assert set(days) == set(kd) | set(nd)


def test_merge_without_kotak_never_double_counts():
    old_m = {"2026-11": _rec(100, 50)}
    nd = {"2026-11-20": _rec(7, -2)}
    m1, d1 = flows.merge(old_m, {}, {}, {}, nd)
    assert m1["2026-11"]["fii_net"] == 107
    m2, _ = flows.merge(m1, d1, {}, {}, nd)          # same day fetched again
    assert m2["2026-11"]["fii_net"] == 107
    m3, _ = flows.merge(m1, d1, {}, {}, {"2026-12-01": _rec(3, 4)})   # new month
    assert m3["2026-12"]["fii_net"] == 3 and m3["2026-11"]["fii_net"] == 107


def test_merge_ignores_truncated_kotak_page():
    old_m = _kotak_months()
    km = {"2026-11": _rec(1, 1)}                     # broken page: one month
    months, _ = flows.merge(old_m, {}, km, {"2026-11-19": _rec(1, 1)}, {})
    assert months == old_m


def test_csv_roundtrip_and_series(tmp_path):
    p = tmp_path / "m.csv"
    flows.write_csv(str(p), "month", {"2026-10": _rec(-5, 9), "2026-11": _rec(3, -1)})
    m = flows.read_csv(str(p), "month")
    rows = flows.monthly_series(m, {"2026-11-19": _rec(3, -1)})
    assert [r["m"] for r in rows] == ["2026-10", "2026-11"]
    assert rows[0]["fii"] == -5 and rows[0]["to"] is None
    assert rows[1]["to"] == "2026-11-19" and rows[1]["dii"] == -1
