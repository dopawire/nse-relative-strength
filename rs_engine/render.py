"""rs_view.html template + SVG helpers (legacy single-file view)."""

import html
import json
import math
import datetime as dt

from rs_engine.config import EMA_PERIODS, WINDOW, BENCHMARK_NAME


def render_breadth_svg(dates, osc, n_stocks):
    if not osc or len(osc) < 2:
        return ('<div class="brdempty">Not enough price history cached for the breadth '
                'oscillator. Run <code>python3 build_rs.py --refresh</code> to pull ~6+ '
                'months, then reopen.</div>')
    n = len(osc)
    # width scales with time so ~2 years breathe (horizontal scroll); ~4.2px/day
    L, R, T, B = 52, 44, 18, 46   # R roomy so the right-side y-labels aren't clipped
    ph = 300
    pw = max(640.0, 4.2 * (n - 1))
    W, H = L + pw + R, T + ph + B
    amax = max(abs(min(osc)), abs(max(osc)))
    ymax = max(20.0, math.ceil(amax / 10.0) * 10.0)

    def X(i): return L + pw * i / (n - 1)
    def Y(v): return T + ph * (1 - (v + ymax) / (2 * ymax))

    p = []
    # overbought / oversold zones
    if 40 < ymax:
        p.append(f'<rect x="{L}" y="{T}" width="{pw:.1f}" height="{Y(40)-T:.1f}" fill="#eaf7f0"/>')
        p.append(f'<rect x="{L}" y="{Y(-40):.1f}" width="{pw:.1f}" '
                 f'height="{T+ph-Y(-40):.1f}" fill="#fdeceb"/>')
    # horizontal gridlines + y-scale on BOTH ends (left stays visible at scroll start)
    step = 20 if ymax <= 80 else 40
    v = -ymax
    while v <= ymax + 0.1:
        y = Y(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw:.1f}" y2="{y:.1f}" '
                 f'stroke="{"#9aa6b2" if v==0 else "#edf1f4"}" '
                 f'stroke-width="{1.4 if v==0 else 1}"/>')
        p.append(f'<text x="{L-7}" y="{y+3:.1f}" font-size="10" fill="#7a8794" '
                 f'text-anchor="end">{int(v):+d}</text>')
        p.append(f'<text x="{L+pw+6:.1f}" y="{y+3:.1f}" font-size="10" '
                 f'fill="#7a8794">{int(v):+d}</text>')
        v += step
    # dashed +/-40 reversal guides
    for g in (40, -40):
        if abs(g) < ymax:
            p.append(f'<line x1="{L}" y1="{Y(g):.1f}" x2="{L+pw:.1f}" y2="{Y(g):.1f}" '
                     f'stroke="#c0392b" stroke-width="1" stroke-dasharray="4 4" opacity="0.45"/>')

    # ---- time axis: month gridlines + labels (spaced), year boundaries + labels ----
    first_idx, order = {}, []
    for i, d in enumerate(dates):
        ym = d[:7]
        if ym not in first_idx:
            first_idx[ym] = i
            order.append(ym)
    last_label_x = -1e9
    prev_year = None
    for k, ym in enumerate(order):
        i0 = first_idx[ym]
        i1 = (first_idx[order[k + 1]] - 1) if k + 1 < len(order) else n - 1
        span = i1 - i0 + 1
        mx = X(i0)
        year = ym[:4]
        is_year_start = year != prev_year
        prev_year = year
        # month gridline (year boundary is a touch stronger)
        p.append(f'<line x1="{mx:.1f}" y1="{T}" x2="{mx:.1f}" y2="{T+ph}" '
                 f'stroke="{"#d3dae1" if is_year_start else "#eef1f4"}" '
                 f'stroke-width="{1.3 if is_year_start else 1}"/>')
        # month label at the month's midpoint; skip tiny partial edge months and
        # anything that would collide with the previous label
        midx = X((i0 + i1) / 2)
        mon = dt.date.fromisoformat(ym + "-01").strftime("%b")
        if span >= 6 and (midx - last_label_x) >= 24:
            p.append(f'<text x="{midx:.1f}" y="{T+ph+16}" font-size="10" fill="#7a8794" '
                     f'text-anchor="middle">{mon}</text>')
            last_label_x = midx
        # year label under the first month of each year (and the very first month)
        if is_year_start:
            p.append(f'<text x="{mx:.1f}" y="{T+ph+34}" font-size="11" font-weight="700" '
                     f'fill="#46505c" text-anchor="middle">{year}</text>')

    # oscillator line, coloured green above zero / red below
    for i in range(1, n):
        col = "#1e7a4d" if (osc[i-1] + osc[i]) / 2 >= 0 else "#c0392b"
        p.append(f'<line x1="{X(i-1):.1f}" y1="{Y(osc[i-1]):.1f}" '
                 f'x2="{X(i):.1f}" y2="{Y(osc[i]):.1f}" stroke="{col}" stroke-width="1.6"/>')
    # last point marker
    lx, ly = X(n - 1), Y(osc[-1])
    p.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="#111"/>')
    # interactive crosshair + hover dot (moved by JS)
    p.append(f'<line id="brdcross" x1="0" y1="{T}" x2="0" y2="{T+ph}" '
             f'stroke="#5a6672" stroke-width="1" stroke-dasharray="3 3" '
             f'style="visibility:hidden"/>')
    p.append('<circle id="brddot" r="3.5" fill="#111" stroke="#fff" '
             'stroke-width="1.5" style="visibility:hidden"/>')

    svg = (f'<svg id="brdsvg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" class="brdsvg">{"".join(p)}</svg>')
    # data + geometry for the hover layer
    cfg = json.dumps({"dates": dates, "osc": [round(o, 2) for o in osc],
                      "L": L, "T": T, "pw": pw, "ph": ph, "ymax": ymax, "W": W, "H": H})
    script = (
        '<script>(function(){'
        f'var C={cfg};'
        'var svg=document.getElementById("brdsvg"),cross=document.getElementById("brdcross"),'
        'dot=document.getElementById("brddot"),tip=document.getElementById("brdtip"),'
        'scroll=document.getElementById("brdscroll");'
        'var n=C.osc.length;'
        'function X(i){return C.L+C.pw*i/(n-1);}'
        'function Y(v){return C.T+C.ph*(1-(v+C.ymax)/(2*C.ymax));}'
        'function fmt(s){var m=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];'
        'var a=s.split("-");return a[2]+" "+m[+a[1]-1]+" "+a[0];}'
        'function move(e){'
        'var r=svg.getBoundingClientRect(),sx=C.W/r.width;'
        'var x=(e.clientX-r.left)*sx;'
        'var i=Math.round((x-C.L)/C.pw*(n-1));if(i<0)i=0;if(i>n-1)i=n-1;'
        'var px=X(i),py=Y(C.osc[i]);'
        'cross.setAttribute("x1",px);cross.setAttribute("x2",px);cross.style.visibility="visible";'
        'dot.setAttribute("cx",px);dot.setAttribute("cy",py);dot.style.visibility="visible";'
        'var val=C.osc[i];'
        'tip.innerHTML="<b>"+fmt(C.dates[i])+"</b><span>"+(val>=0?"+":"")+val.toFixed(1)+"</span>";'
        'tip.style.visibility="visible";'
        'var cx=(e.clientX-scroll.getBoundingClientRect().left)+scroll.scrollLeft;'
        'tip.style.left=cx+"px";tip.style.top=(py*(r.height/C.H)-34)+"px";'
        '}'
        'function hide(){cross.style.visibility="hidden";dot.style.visibility="hidden";'
        'tip.style.visibility="hidden";}'
        'svg.addEventListener("mousemove",move);svg.addEventListener("mouseleave",hide);'
        '})();</script>')
    return (f'<div class="brdscroll" id="brdscroll">{svg}'
            f'<div class="brdtip" id="brdtip"></div></div>{script}')


# --------------------------------------------------------------------------- #
#  HTML rendering
# --------------------------------------------------------------------------- #
def sparkline_svg(series, w=150, h=34):
    if not series:
        return ""
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1.0
    n = len(series)
    hi_idx = max(range(n), key=lambda i: series[i])   # highest bar -> bright
    gap = 1.5
    bw = (w - gap * (n - 1)) / n
    bars = []
    for i, v in enumerate(series):
        bh = 3 + (v - lo) / rng * (h - 4)
        x = i * (bw + gap)
        y = h - bh
        color = "#1e7a4d" if i == hi_idx else "#a9dcc0"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                    f'height="{bh:.1f}" fill="{color}" rx="0.6"/>')
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'preserveAspectRatio="none">{"".join(bars)}</svg>')


def green_bg(pct):
    """pct in 0..1 -> white..green background like the sheet's gradient."""
    r = round(255 + (46 - 255) * pct)
    g = round(255 + (158 - 255) * pct)
    b = round(255 + (110 - 255) * pct)
    text = "#0a3d24" if pct < 0.55 else "#ffffff"
    return f"background:rgb({r},{g},{b});color:{text};"


EMA_HEAD_JS = "".join(f'<th class=\\"eh\\">{p}</th>' for p in EMA_PERIODS)


def render_rows(items, gid, members_out):
    """items: list of dicts {name, n, rs, pct, members}. Pre-sorted desc by pct.

    Each group is its own <tbody> holding a clickable header row plus an EMPTY
    hidden sub-row. The constituent stock rows are NOT emitted here — instead the
    member data for each group is stashed in `members_out[gid]` (embedded as JSON)
    and the sub-table is built lazily in the browser on expand/filter. This keeps
    the initial DOM tiny (just the group headers) so the page loads instantly
    instead of choking on ~9,500 inline SVG sparklines.

    Returns the next free gid so ids stay unique across all level tabs."""
    out = []
    for it in items:
        spark = sparkline_svg(it["rs"])
        bg = green_bg(it["pct"])
        nm = html.escape(it["name"])
        gidv = f"g{gid}"
        members_out[gidv] = [
            {"n": m["name"], "s": m["sym"], "p": round(m["pct"], 4),
             "r": [round(x, 3) for x in m["rs"]],
             "e": m.get("ema") or [-1] * len(EMA_PERIODS),
             "b": m.get("rse", -1),
             "l": (round(m["ltp"], 2) if m.get("ltp") else None),
             "h": (round(m["hi52"], 1) if m.get("hi52") is not None else None),
             "a": (round(m["adr"], 2) if m.get("adr") is not None else None)}
            for m in it["members"]
        ]
        out.append(
            f'<tbody class="gb" data-gid="{gidv}" data-pct="{it["pct"]:.6f}" data-name="{nm}">'
            f'<tr class="grp">'
            f'<td class="nm"><input type="checkbox" class="gpick" '
            f'title="select all stocks in this group"><span class="car">&#9656;</span>{nm}'
            f'<span class="cnt">{it["n"]}</span></td>'
            f'<td class="sp">{spark}</td>'
            f'<td class="pc" style="{bg}">{it["pct"]*100:.0f}%</td></tr>'
            f'<tr class="sub hide"><td colspan="3" class="subcell"></td></tr>'
            f'</tbody>'
        )
        gid += 1
    return "\n".join(out), gid


def build_html(levels, meta, breadth=None):
    """levels: ordered list of (key, label, items) — one grouping tab each."""
    if breadth and breadth.get("osc"):
        svg = render_breadth_svg(breadth["dates"], breadth["osc"], breadth["n"])
        last = breadth["osc"][-1]
        span = (f'{breadth["dates"][0]} → {breadth["dates"][-1]}'
                if breadth["dates"] else "")
        brd_html = (
            f'<div class="brdhead">NSE Market Breadth Oscillator'
            f'<span> &middot; McClellan-style: 19- vs 39-day EMA of ratio-adjusted '
            f'(advancers &minus; decliners) across {breadth["n"]} stocks &middot; {span}</span></div>'
            f'{svg}'
            f'<div class="brdcap">Latest reading <b>{last:+.1f}</b>. '
            f'Extreme lows (&approx; &minus;40 and below) flag oversold / possible bottoms; '
            f'extreme highs (&approx; +40 and above) flag overbought &mdash; reversal warnings, '
            f'the way Dan Zanger reads advance&ndash;decline breadth.</div>'
            f'<blockquote class="brdq">Zanger: &ldquo;I use one custom oscillator in particular '
            f'which uses market breadth advance-decline data to give me a heads up on trend '
            f'strength and potential reversals. When it hits extreme lows or highs, it usually '
            f'means a reversal of some sort is ahead and it&rsquo;s time to take some profits.&rdquo;'
            f'<span>More often than not, the number of advancing versus declining issues provides '
            f'a leading indicator of where stocks are headed.</span></blockquote>')
    else:
        brd_html = ('<div class="brdempty">Not enough price history cached for the breadth '
                    'oscillator. Run <code>python3 build_rs.py --refresh</code> to pull ~6+ '
                    'months, then reopen.</div>')
    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relative Strength &mdash; Sectors &amp; Industries</title>
<style>
 :root{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;}
 body{margin:0;background:#f4f6f8;color:#1f2733;}
 header{padding:18px 24px;background:#fff;border-bottom:1px solid #e3e8ee;}
 header h1{margin:0;font-size:19px;}
 header .meta{margin-top:4px;font-size:12px;color:#6b7785;}
 .tabs{display:flex;gap:8px;padding:14px 24px 0;}
 .tab{padding:8px 16px;border:1px solid #d4dbe3;border-bottom:none;border-radius:8px 8px 0 0;
      background:#e9edf2;cursor:pointer;font-size:13px;font-weight:600;color:#46505c;}
 .tab.active{background:#fff;color:#1f2733;}
 .wrap{padding:0 24px 40px;}
 table{width:100%;max-width:860px;border-collapse:collapse;background:#fff;
       border:1px solid #e3e8ee;border-top:none;}
 thead th{position:sticky;top:0;background:#fafbfc;text-align:left;font-size:11px;
          letter-spacing:.04em;text-transform:uppercase;color:#7a8794;
          padding:10px 12px;border-bottom:1px solid #e3e8ee;cursor:pointer;user-select:none;}
 thead th.pc,td.pc{text-align:right;width:74px;}
 td{padding:7px 12px;border-bottom:1px solid #eef1f4;font-size:13px;vertical-align:middle;}
 td.nm{font-weight:600;color:#222b36;}
 td.nm .cnt{color:#9aa6b2;font-weight:400;font-size:11px;margin-left:7px;}
 td.sp{width:160px;}
 td.pc{font-weight:700;font-variant-numeric:tabular-nums;}
 .hide{display:none;}
 .note{max-width:760px;margin:14px 0 0;font-size:11.5px;color:#8a94a0;}
 tr.grp{cursor:pointer;}
 tr.grp:hover td{background:#f5f9f6;}
 td.nm .car{display:inline-block;width:11px;color:#9aa6b2;font-size:10px;
            margin-right:5px;transition:transform .12s;}
 td.nm .car.open{transform:rotate(90deg);}
 td.subcell{padding:0;background:#fbfcfd;border-bottom:1px solid #e3e8ee;}
 table.mtbl{width:100%;border:none;background:transparent;margin:0;}
 table.mtbl td{border-bottom:1px solid #eef2f5;padding:4px 12px;font-size:12px;}
 td.mnm{padding-left:4px!important;color:#3a4654;font-weight:500;}
 td.mnm .msym{color:#aab4c0;font-weight:400;font-size:10.5px;margin-left:7px;}
 td.msp{width:140px;}
 td.mpc{text-align:right;width:74px;font-weight:600;font-variant-numeric:tabular-nums;}
 td.mlt{text-align:right;width:78px;font-weight:600;font-variant-numeric:tabular-nums;
   color:#2b3542;}
 td.mhi{text-align:right;width:66px;font-weight:600;font-variant-numeric:tabular-nums;
   color:#b06a2c;}
 td.madr{text-align:right;width:62px;font-weight:600;font-variant-numeric:tabular-nums;
   color:#4a5bb0;padding-right:14px;}
 .searchbar{padding:14px 24px 0;display:flex;align-items:center;gap:10px;}
 .searchbar input{width:100%;max-width:420px;padding:9px 12px;font-size:13px;
   border:1px solid #d4dbe3;border-radius:8px;outline:none;}
 .searchbar input:focus{border-color:#1e7a4d;box-shadow:0 0 0 2px rgba(30,122,77,.12);}
 .searchbar #qinfo{font-size:12px;color:#8a94a0;white-space:nowrap;}
 .seltools{padding:10px 24px 0;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
 .seltools #selcount{font-size:12px;color:#46505c;font-weight:600;margin-right:4px;}
 .seltools button{padding:7px 12px;font-size:12px;font-weight:600;cursor:pointer;
   border:1px solid #d4dbe3;border-radius:7px;background:#fff;color:#46505c;}
 .seltools button:hover{border-color:#1e7a4d;color:#1e7a4d;}
 .seltools button.primary{background:#1e7a4d;border-color:#1e7a4d;color:#fff;}
 .seltools button.primary:hover{background:#176039;color:#fff;}
 .seltools #flash{font-size:12px;color:#1e7a4d;font-weight:600;}
 td.mck{width:26px;text-align:center;padding-left:14px!important;}
 td.nm input.gpick{margin-right:7px;vertical-align:middle;}
 input.pick,input.gpick{cursor:pointer;}
 .brdwrap{max-width:1000px;background:#fff;border:1px solid #e3e8ee;padding:16px 18px;}
 .brdhead{font-size:14px;font-weight:700;color:#222b36;margin-bottom:10px;}
 .brdhead span{font-weight:400;font-size:11.5px;color:#7a8794;}
 .brdscroll{position:relative;overflow-x:auto;overflow-y:hidden;
   border:1px solid #eef1f4;border-radius:6px;}
 .brdsvg{display:block;}
 .brdtip{position:absolute;transform:translateX(-50%);pointer-events:none;
   visibility:hidden;background:#111a24;color:#fff;font-size:11px;padding:4px 8px;
   border-radius:5px;white-space:nowrap;z-index:5;box-shadow:0 2px 8px rgba(0,0,0,.28);}
 .brdtip b{font-weight:700;margin-right:7px;}
 .brdtip span{font-variant-numeric:tabular-nums;}
 .brdcap{font-size:12px;color:#46505c;margin-top:10px;max-width:900px;line-height:1.5;}
 .brdq{margin:14px 0 0;padding:10px 14px;border-left:3px solid #1e7a4d;background:#f6faf8;
   font-size:12px;color:#46505c;font-style:italic;max-width:900px;line-height:1.5;}
 .brdq span{display:block;margin-top:8px;font-style:normal;color:#6b7785;}
 .brdempty{padding:30px;color:#8a94a0;font-size:13px;}
 .brdempty code{background:#eef1f4;padding:2px 5px;border-radius:4px;}
 .emabar{padding:10px 24px 0;display:flex;align-items:center;gap:7px;flex-wrap:wrap;}
 .emabar .lbl{font-size:12px;color:#46505c;font-weight:600;}
 .ematog{padding:6px 11px;font-size:12px;font-weight:600;cursor:pointer;
   border:1px solid #d4dbe3;border-radius:7px;background:#fff;color:#46505c;}
 .ematog:hover{border-color:#1e7a4d;color:#1e7a4d;}
 .ematog.on{background:#1e7a4d;border-color:#1e7a4d;color:#fff;}
 .emabar #emainfo{font-size:12px;color:#8a94a0;margin-left:2px;}
 table.mtbl thead th{position:static;background:#fbfcfd;color:#93a0ad;font-size:10px;
   text-transform:none;letter-spacing:0;padding:5px 6px;border-bottom:1px solid #eef2f5;text-align:center;}
 table.mtbl thead th.ehn{text-align:left;padding-left:6px;}
 table.mtbl thead th.ehp{text-align:right;}
 table.mtbl thead th.ehl{text-align:right;}
 table.mtbl thead th.ehh{text-align:right;width:66px;}
 table.mtbl thead th.eha{text-align:right;padding-right:14px;width:62px;}
 table.mtbl thead th.eh{width:30px;color:#7a8794;font-weight:700;}
 .hifilt{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#46505c;
   font-weight:600;padding:5px 11px;border:1px solid #d4dbe3;border-radius:7px;background:#fff;
   margin-left:6px;}
 .hifilt.on{border-color:#b06a2c;color:#8a4d1c;background:#fff8f1;}
 .hifilt.adr.on{border-color:#4a5bb0;color:#334090;background:#f5f6fd;}
 .hifilt input[type=number]{width:46px;padding:2px 4px;font-size:12px;font-weight:700;
   border:1px solid #d4dbe3;border-radius:5px;text-align:right;font-variant-numeric:tabular-nums;}
 .hifilt input[type=checkbox]{cursor:pointer;}
 td.e{width:30px;text-align:center;font-size:11px;font-weight:700;padding:4px 2px;}
 td.e[data-a="1"]{background:#e6f5ec;color:#1e7a4d;}
 td.e[data-a="1"]::after{content:"\\2713";}
 td.e[data-a="0"]{background:#fdecea;color:#e0a9a2;}
 td.e[data-a="0"]::after{content:"\\2717";}
 td.e[data-a="-1"]{color:#cdd5de;}
 td.e[data-a="-1"]::after{content:"\\2013";}
</style></head>
<body>
<header>
 <h1>Relative Strength &mdash; Sectors &amp; Industries</h1>
 <div class="meta">Equal-weighted &middot; benchmark __BENCH__ &middot; __WINDOW__-day window
   &middot; window __DRANGE__ &middot; generated __GEN__</div>
</header>
<div class="searchbar">
 <input id="q" type="search" placeholder="Search stock, sector or industry&hellip;" autocomplete="off">
 <span id="qinfo"></span>
</div>
<div class="seltools">
 <span id="selcount">0 selected</span>
 <button id="selvis">Select all shown</button>
 <button id="selclear">Clear</button>
 <button id="btncopy" class="primary">Copy for TradingView</button>
 <button id="btndl" class="primary">Download .txt</button>
 <span id="flash"></span>
</div>
<div class="emabar">
 <span class="lbl">Price above:</span>
__EMATOGS__
 <button class="ematog" id="emaclear" style="border-style:dashed;">clear</button>
 <label class="hifilt" id="hifilt" title="show only stocks within this % of their 52-week high">
   <input type="checkbox" id="hion"> within
   <input type="number" id="himax" value="20" min="0" max="100" step="1"> % of 52W high</label>
 <label class="hifilt adr" id="adrfilt" title="show only stocks whose 20-day Average Daily Range is at least this %">
   <input type="checkbox" id="adron"> ADR&#8805;
   <input type="number" id="adrmin" value="3" min="0" max="50" step="0.5"> %</label>
 <span id="emainfo"></span>
</div>
<div class="tabs">
__TABS__
 <div class="tab" data-t="brd">Market Breadth</div>
</div>
<div class="wrap">
__TABLES__
 <div id="brd" class="hide brdwrap">
__BRD__
 </div>
 <p class="note">RS_STS% = PERCENTRANK of the latest relative-strength ratio within its trailing
   __WINDOW__-day range. Count beside each name = constituents used. Click a row to expand its
   stocks; click a header to re-sort.</p>
</div>
<script>var MEMBERS=__MEMBERS__;var EMAHEAD='__EMAHEAD__';</script>
<script>
 // ---- constituent rows are built lazily in the browser (the data lives in
 //      MEMBERS as JSON) so the initial page is tiny and never hangs ----
 function esc(s){return String(s).replace(/[&<>"]/g,function(c){
   return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
 function spark(series,w,h){
   if(!series||!series.length) return '';
   var lo=Math.min.apply(null,series),hi=Math.max.apply(null,series);
   var rng=(hi-lo)||1,n=series.length,gap=1.5,bw=(w-gap*(n-1))/n,hiIdx=0;
   for(var i=1;i<n;i++) if(series[i]>series[hiIdx]) hiIdx=i;
   var bars='';
   for(var i=0;i<n;i++){
     var bh=3+(series[i]-lo)/rng*(h-4),x=i*(bw+gap),y=h-bh;
     var col=(i===hiIdx)?'#1e7a4d':'#a9dcc0';
     bars+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+
           '" height="'+bh.toFixed(1)+'" fill="'+col+'" rx="0.6"/>';
   }
   return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+
          '" preserveAspectRatio="none">'+bars+'</svg>';
 }
 function greenBg(pct){
   var r=Math.round(255+(46-255)*pct),g=Math.round(255+(158-255)*pct),
       b=Math.round(255+(110-255)*pct),text=pct<0.55?'#0a3d24':'#ffffff';
   return 'background:rgb('+r+','+g+','+b+');color:'+text+';';
 }
 function buildMembers(gid){
   var arr=MEMBERS[gid]||[],rows='';
   for(var j=0;j<arr.length;j++){
     var m=arr[j],sp=spark(m.r,120,22),bg=greenBg(m.p),ema='';
     for(var k=0;k<m.e.length;k++) ema+='<td class="e" data-a="'+m.e[k]+'"></td>';
     var ltp=(m.l!=null)?Number(m.l).toLocaleString(undefined,
       {minimumFractionDigits:2,maximumFractionDigits:2}):'&ndash;';
     var off=(m.h!=null)?('-'+m.h.toFixed(1)+'%'):'&ndash;';
     var adr=(m.a!=null)?(m.a.toFixed(1)+'%'):'&ndash;';
     var ck=sel.has(m.s)?' checked':'';
     rows+='<tr>'+
       '<td class="mck"><input type="checkbox" class="pick" data-sym="'+esc(m.s)+'"'+ck+'></td>'+
       '<td class="mnm">'+esc(m.n)+'<span class="msym">'+esc(m.s)+'</span></td>'+
       '<td class="msp">'+sp+'</td>'+
       '<td class="mpc" style="'+bg+'">'+Math.round(m.p*100)+'%</td>'+
       '<td class="mlt">'+ltp+'</td>'+
       '<td class="mhi">'+off+'</td>'+
       '<td class="madr">'+adr+'</td>'+ema+'</tr>';
   }
   var head='<thead><tr><th></th><th class="ehn">Stock</th><th>RS</th>'+
     '<th class="ehp">RS%</th><th class="ehl">LTP</th><th class="ehh">Off Hi</th>'+
     '<th class="eha">ADR%</th>'+EMAHEAD+'</tr></thead>';
   return '<table class="mtbl">'+head+'<tbody>'+rows+'</tbody></table>';
 }
 function ensureBuilt(body){
   if(body.dataset.built) return;
   body.querySelector('td.subcell').innerHTML=buildMembers(body.dataset.gid);
   body.dataset.built='1';
 }

 document.querySelectorAll('.tab').forEach(function(t){
   t.onclick=function(){
     document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
     t.classList.add('active');
     __TABIDS__.forEach(function(id){
       document.getElementById(id).classList.toggle('hide', t.dataset.t!==id);
     });
     var onTable = t.dataset.t!=='brd';   // search/select/filter only apply to the tables
     document.querySelector('.searchbar').style.display=onTable?'':'none';
     document.querySelector('.seltools').style.display=onTable?'':'none';
     document.querySelector('.emabar').style.display=onTable?'':'none';
     if(onTable) runSearch();
   };
 });
 // expand / collapse a group -> build its constituent stocks on first open
 document.querySelectorAll('table').forEach(function(tbl){
   tbl.addEventListener('click',function(e){
     if(e.target.tagName==='INPUT')return;   // don't toggle when ticking a checkbox
     var grp=e.target.closest('tr.grp'); if(!grp||!tbl.contains(grp))return;
     var body=grp.parentNode, sub=body.querySelector('tr.sub');
     if(sub.classList.contains('hide')) ensureBuilt(body);
     sub.classList.toggle('hide');
     grp.querySelector('.car').classList.toggle('open');
   });
 });

 // ---- filter: text search + "price above EMA(s)" + "near 52W high" (all AND) ----
 var qbox=document.getElementById('q'), qinfo=document.getElementById('qinfo');
 var emaSel=new Set();               // indices of active EMA toggles (AND logic)
 var emainfo=document.getElementById('emainfo');
 var hion=document.getElementById('hion'), himax=document.getElementById('himax');
 var hifilt=document.getElementById('hifilt');
 var adron=document.getElementById('adron'), adrmin=document.getElementById('adrmin');
 var adrfilt=document.getElementById('adrfilt');
 var hiOn=false, hiMax=20, adrOn=false, adrMin=3;
 function memberMatch(m,q,gmatch){
   if(!(q==='' || gmatch || (m.n+' '+m.s).toLowerCase().indexOf(q)>=0)) return false;
   for(var i of emaSel){ if(m.e[i]!==1) return false; }      // above ALL selected EMAs
   if(hiOn){ if(m.h==null || m.h>hiMax) return false; }      // within hiMax% of 52W high
   if(adrOn){ if(m.a==null || m.a<adrMin) return false; }    // ADR% at or above adrMin
   return true;
 }
 // members of a group that pass the CURRENT filter (all of them when no filter is on)
 function groupMatches(body){
   var arr=MEMBERS[body.dataset.gid]||[];
   var q=qbox.value.trim().toLowerCase();
   if(q==='' && !emaSel.size && !hiOn && !adrOn) return arr;
   var gmatch = q!=='' && body.dataset.name.toLowerCase().indexOf(q)>=0;
   return arr.filter(function(m){ return memberMatch(m,q,gmatch); });
 }
 function activeTable(){       // the visible LEVEL table (never an inner member table)
   var t=document.querySelector('.tab.active');
   if(!t || t.dataset.t==='brd') return null;
   return document.getElementById(t.dataset.t);
 }
 function runSearch(){
   var q=qbox.value.trim().toLowerCase();
   var filtering = q!=='' || emaSel.size>0 || hiOn || adrOn;
   var tbl=activeTable(); if(!tbl) return;
   var shown=0, stocks=0;
   tbl.querySelectorAll('tbody.gb').forEach(function(body){
     var grp=body.querySelector('tr.grp'), sub=body.querySelector('tr.sub');
     var car=grp.querySelector('.car'), cnt=grp.querySelector('.cnt');
     var arr=MEMBERS[body.dataset.gid]||[];
     if(cnt && cnt.dataset.orig===undefined) cnt.dataset.orig=cnt.textContent;
     if(!filtering){                 // reset to default collapsed view
       body.style.display=''; sub.classList.add('hide'); car.classList.remove('open');
       if(cnt) cnt.textContent=cnt.dataset.orig;   // restore full constituent count
       if(body.dataset.built)
         body.querySelectorAll('table.mtbl tbody tr').forEach(r=>r.style.display='');
       return;
     }
     var gmatch = q!=='' && body.dataset.name.toLowerCase().indexOf(q)>=0;
     var hits=[];
     for(var j=0;j<arr.length;j++){ if(memberMatch(arr[j],q,gmatch)) hits.push(j); }
     if(hits.length){
       ensureBuilt(body);
       var set={}; hits.forEach(function(i){set[i]=1;});
       body.querySelectorAll('table.mtbl tbody tr').forEach(function(r,idx){
         r.style.display=set[idx]?'':'none';
       });
       body.style.display=''; sub.classList.remove('hide'); car.classList.add('open');
       if(cnt) cnt.textContent=hits.length;   // show how many match the active filter
       shown++; stocks+=hits.length;
     } else { body.style.display='none'; }
   });
   qinfo.textContent = filtering ? (shown+' group(s), '+stocks+' stock(s)') : '';
   var bits=[];
   if(emaSel.size) bits.push('above '+emaSel.size+' EMA'+(emaSel.size>1?'s':''));
   if(hiOn) bits.push('\\u2264'+hiMax+'% off high');
   if(adrOn) bits.push('ADR\\u2265'+adrMin+'%');
   emainfo.textContent = bits.join(' \\u00b7 ');
 }
 qbox.addEventListener('input', runSearch);
 qbox.addEventListener('keydown', function(e){ if(e.key==='Escape'){qbox.value='';runSearch();} });

 // ---- "price above EMA" toggles ----
 document.querySelectorAll('.ematog[data-i]').forEach(function(btn){
   btn.onclick=function(){
     var i=+btn.dataset.i;
     if(emaSel.has(i)){ emaSel.delete(i); btn.classList.remove('on'); }
     else { emaSel.add(i); btn.classList.add('on'); }
     runSearch();
   };
 });
 document.getElementById('emaclear').onclick=function(){
   emaSel.clear();
   document.querySelectorAll('.ematog[data-i]').forEach(b=>b.classList.remove('on'));
   runSearch();
 };

 // ---- "within X% of 52-week high" filter ----
 function syncHi(){
   hiOn=hion.checked; hiMax=parseFloat(himax.value); if(isNaN(hiMax)) hiMax=0;
   hifilt.classList.toggle('on', hiOn); runSearch();
 }
 hion.addEventListener('change', syncHi);
 himax.addEventListener('input', function(){
   if(himax.value!=='' && !hion.checked){ hion.checked=true; }  // a real number auto-enables
   syncHi();
 });

 // ---- "ADR% >= X" (Average Daily Range) filter ----
 function syncAdr(){
   adrOn=adron.checked; adrMin=parseFloat(adrmin.value); if(isNaN(adrMin)) adrMin=0;
   adrfilt.classList.toggle('on', adrOn); runSearch();
 }
 adron.addEventListener('change', syncAdr);
 adrmin.addEventListener('input', function(){
   if(adrmin.value!=='' && !adron.checked){ adron.checked=true; }
   syncAdr();
 });

 // ---- multi-select -> TradingView export (state keyed by symbol) ----
 var sel=new Set();
 var selcount=document.getElementById('selcount'), flash=document.getElementById('flash');
 function syncDup(sym,on){    // mirror onto any already-built duplicate rows
   document.querySelectorAll('input.pick[data-sym="'+CSS.escape(sym)+'"]').forEach(x=>x.checked=on);
 }
 function updateCount(){ selcount.textContent=sel.size+' selected'; }
 function showFlash(msg){ flash.textContent=msg; setTimeout(()=>{flash.textContent='';},2200); }
 document.addEventListener('change',function(e){
   var t=e.target;
   if(t.classList.contains('pick')){
     if(t.checked) sel.add(t.dataset.sym); else sel.delete(t.dataset.sym);
     syncDup(t.dataset.sym,t.checked); updateCount();
   } else if(t.classList.contains('gpick')){
     var body=t.closest('tbody.gb');
     var matches=groupMatches(body);          // respect the active filter, not all constituents
     var pick={}; matches.forEach(function(m){ pick[m.s]=1;
       if(t.checked) sel.add(m.s); else sel.delete(m.s); });
     ensureBuilt(body);
     body.querySelectorAll('input.pick').forEach(function(cb){
       if(pick[cb.dataset.sym]) cb.checked=t.checked;   // only tick the filtered rows
     });
     matches.forEach(function(m){ syncDup(m.s,t.checked); });
     updateCount();
   }
 });
 function selectVisible(on){
   var tbl=activeTable(); if(!tbl) return;
   tbl.querySelectorAll('table.mtbl tr').forEach(function(r){
     if(r.offsetParent===null)return;            // only rows actually on screen
     var cb=r.querySelector('input.pick'); if(!cb)return;
     cb.checked=on;
     if(on) sel.add(cb.dataset.sym); else sel.delete(cb.dataset.sym);
     syncDup(cb.dataset.sym,on);
   });
   updateCount();
 }
 function clearSel(){
   sel.clear();
   document.querySelectorAll('input.pick,input.gpick').forEach(x=>x.checked=false);
   updateCount();
 }
 function tvText(){ return Array.from(sel).map(s=>'NSE:'+s+',').join('\\n'); }
 function copyTV(){
   if(!sel.size){ showFlash('nothing selected'); return; }
   var txt=tvText();
   if(navigator.clipboard && navigator.clipboard.writeText){
     navigator.clipboard.writeText(txt).then(()=>showFlash('copied '+sel.size),fallbackCopy.bind(null,txt));
   } else fallbackCopy(txt);
 }
 function fallbackCopy(txt){
   var ta=document.createElement('textarea'); ta.value=txt; document.body.appendChild(ta);
   ta.select(); try{document.execCommand('copy'); showFlash('copied '+sel.size);}catch(e){showFlash('copy failed');}
   document.body.removeChild(ta);
 }
 function downloadTV(){
   if(!sel.size){ showFlash('nothing selected'); return; }
   var blob=new Blob([tvText()],{type:'text/plain'});
   var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
   a.download='tradingview_watchlist.txt'; document.body.appendChild(a); a.click();
   document.body.removeChild(a); URL.revokeObjectURL(a.href); showFlash('downloaded '+sel.size);
 }
 document.getElementById('selvis').onclick=function(){selectVisible(true);};
 document.getElementById('selclear').onclick=clearSel;
 document.getElementById('btncopy').onclick=copyTV;
 document.getElementById('btndl').onclick=downloadTV;
 // sort whole groups (each group is one tbody.gb)
 document.querySelectorAll('th[data-k]').forEach(function(th){
   th.onclick=function(){
     var tbl=th.closest('table');
     var k=th.dataset.k, asc=th.dataset.asc==='1'; th.dataset.asc=asc?'0':'1';
     var bodies=[].slice.call(tbl.querySelectorAll('tbody.gb'));
     bodies.sort(function(a,b){
       var va=k==='pct'?parseFloat(a.dataset.pct):a.dataset.name.toLowerCase();
       var vb=k==='pct'?parseFloat(b.dataset.pct):b.dataset.name.toLowerCase();
       if(va<vb)return asc?-1:1; if(va>vb)return asc?1:-1; return 0;
     });
     bodies.forEach(b=>tbl.appendChild(b));
   };
 });
</script>
</body></html>"""
    ematogs = "\n".join(
        f' <button class="ematog" data-i="{i}">EMA{p}</button>'
        for i, p in enumerate(EMA_PERIODS))
    tabs = "\n".join(
        f' <div class="tab{" active" if i == 0 else ""}" data-t="{key}">'
        f'{label} ({len(items)})</div>'
        for i, (key, label, items) in enumerate(levels))
    members_out, gid = {}, 0
    table_parts = []
    for i, (key, label, items) in enumerate(levels):
        rows_html, gid = render_rows(items, gid, members_out)
        cls = "" if i == 0 else ' class="hide"'
        table_parts.append(
            f' <table id="{key}"{cls}><thead><tr>'
            f'<th data-k="name">{label}</th><th>Relative Strength</th>'
            f'<th class="pc" data-k="pct">RS_STS%</th></tr></thead>\n'
            f'{rows_html}\n </table>')
    tables = "\n".join(table_parts)
    # embed member data as JSON (built into rows lazily in the browser). Escape
    # "</" so a symbol/name can never prematurely close the <script> tag.
    members_json = json.dumps(members_out, separators=(",", ":")).replace("</", "<\\/")
    tabids = "[" + ",".join(f"'{k}'" for k, _, _ in levels) + ",'brd']"
    return (template
            .replace("__MEMBERS__", members_json)
            .replace("__EMAHEAD__", EMA_HEAD_JS)
            .replace("__EMATOGS__", ematogs)
            .replace("__TABS__", tabs)
            .replace("__TABLES__", tables)
            .replace("__TABIDS__", tabids)
            .replace("__BRD__", brd_html)
            .replace("__BENCH__", BENCHMARK_NAME)
            .replace("__WINDOW__", str(WINDOW))
            .replace("__DRANGE__", meta["drange"])
            .replace("__GEN__", meta["gen"]))


# --------------------------------------------------------------------------- #
#  JSON export for the FastAPI backend
# --------------------------------------------------------------------------- #
