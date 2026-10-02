"""One-page printable daily digest (daily_report.html)."""

def write_daily_report(path, meta, breadth, levels, ipo):
    """One-page printable HTML digest of today's snapshot."""
    def pct(v):
        return f"{v * 100:.0f}%"
    macro = next((it for key, _l, items in levels if key == "macro"
                  for it in items), None)
    sector = [it for key, _l, items in levels if key == "sector" for it in items]
    rows = "".join(
        f"<tr><td>{g['name']}</td><td>{pct(g['pct'])}</td>"
        f"<td>{g['n']}</td></tr>"
        for g in sorted(sector, key=lambda x: -x["pct"])[:10])
    bot = "".join(
        f"<tr><td>{g['name']}</td><td>{pct(g['pct'])}</td>"
        f"<td>{g['n']}</td></tr>"
        for g in sorted(sector, key=lambda x: x["pct"])[:5])
    div = breadth.get("divergence") or {"state": "none"}
    src = meta.get("src") or {}
    html = f"""<!doctype html><meta charset="utf-8">
<title>NSE RS daily digest — {meta['drange']}</title>
<style>body{{font:14px system-ui;max-width:780px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:20px}} h2{{font-size:15px;margin-top:22px}}
table{{border-collapse:collapse}} td,th{{border:1px solid #ddd;padding:5px 12px;font-size:13px}}
.num{{font-variant-numeric:tabular-nums}} .muted{{color:#777;font-size:12px}}</style>
<h1>NSE Relative Strength — daily digest</h1>
<p class="muted">{meta['gen']} · window {meta['drange']} · {meta['n_window']}/{meta['n_stocks']} stocks in view</p>
<h2>Market breadth</h2>
<p>Latest oscillator: <b>{breadth['osc'][-1]:+.1f}</b> · divergence: <b>{div['state']}</b>
{div.get('note', '')}</p>
<h2>Macro RS_STS%</h2>
<p>{macro['name'] if macro else '—'}: <b>{pct(macro['pct']) if macro else '—'}</b>
(macro group RS ranking)</p>
<h2>Strongest sectors (RS_STS%)</h2>
<table><tr><th>Sector</th><th>RS%</th><th>n</th></tr>{rows}</table>
<h2>Weakest sectors</h2>
<table><tr><th>Sector</th><th>RS%</th><th>n</th></tr>{bot}</table>
<h2>New listings awaiting first ranking</h2>
<p>{len(ipo)} stock(s): {', '.join(i['s'] for i in ipo[:12]) or 'none'}</p>
<h2>Data provenance</h2>
<p class="muted">{len(src)} date(s) not from Yahoo daily bars:
{', '.join(f'{d} ({s})' for d, s in sorted(src.items())[:8]) or 'all Yahoo'}</p>
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


