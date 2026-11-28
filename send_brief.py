#!/usr/bin/env python3
"""Evening brief → Telegram: the Focus answer, the market regime, the top
breakouts / pullbacks, results warnings and the track record — from the
finished rs_data.json (rs_engine.decide), so it says what the site says.

Setup (free): message @BotFather → /newbot → copy the token; send your bot
any message; then

    TELEGRAM_BOT_TOKEN=<token> python send_brief.py --chat-id

prints your chat id.  Put both in ~/.config/nse-rs/notify.env:

    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...

cron_daily.sh sends the brief once per session after the build.

    python send_brief.py --dry-run     # print the message, send nothing
    python send_brief.py --force       # send even if today's was sent
"""
import argparse
import html
import json
import os
import sys

import requests

import watchlist
from rs_engine.config import CACHE_DIR, data_path
from rs_engine.decide import crore

HERE = os.path.dirname(os.path.abspath(__file__))
RS_DATA = data_path("rs_data.json")
SENT = os.path.join(CACHE_DIR, ".brief_sent")
SITE = os.environ.get("NSE_RS_SITE", "https://dopawire.github.io/nse-relative-strength/")
API = "https://api.telegram.org/bot{token}/{method}"

DOT = {"on": "🟢", "mixed": "🟡", "off": "🔴"}
WORD = {"on": "Risk-on", "mixed": "Mixed", "off": "Risk-off"}
ADVICE = {"on": "normal size, act on breakouts in leading groups",
          "mixed": "half size, only the best setups",
          "off": "protect capital — mostly cash"}
CAP = {"Large": "large caps", "Mid": "mid caps", "Small": "small caps", "Micro": "micro caps"}
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def day_txt(d):
    y, m, dd = d.split("-")
    return f"{int(dd)} {MON[int(m) - 1]} {y}"


def pct(v, dp=1):
    return "—" if v is None else f"{'+' if v >= 0 else '−'}{abs(v):.{dp}f}%"


def members(data):
    out = {}
    for lv in data.get("levels", []):
        if lv.get("key") == "macro":
            for g in lv["groups"]:
                for m in g["members"]:
                    out[m["s"]] = m
    return out


def compose(data, watch=None, save=True):
    """The brief as Telegram HTML."""
    d = data.get("decide") or {}
    if not d.get("regime"):
        return None
    e = html.escape
    ms = members(data)
    reg = d["regime"]
    tags = d.get("tags") or {}
    lines = [f"<b>📊 NSE evening brief — {day_txt(d['asof'])}</b>", "",
             f"{DOT[reg['level']]} <b>{WORD[reg['level']]}</b> ({reg['pass']}/{reg['known']} checks) — "
             f"{ADVICE[reg['level']]}"]
    focus = ", ".join(d.get("focus") or [])
    cap = CAP.get(d.get("cap"), "")
    lines.append(f"🎯 <b>Focus:</b> {e(focus)}{' · ' + cap if cap else ''}")
    if d.get("turning"):
        lines.append(f"↗️ <b>Turning up:</b> {e(', '.join(d['turning']))}")
    if d.get("avoid"):
        lines.append(f"⛔ <b>Avoid:</b> {e(', '.join(d['avoid']))}")

    fl = (data.get("flows") or {}).get("months") or []
    if fl:
        cur = fl[-1]
        lines.append(f"💰 <b>FII</b> {crore(cur['fii'])} · <b>DII</b> {crore(cur['dii'])} "
                     f"this month{' (to ' + day_txt(cur['to']) + ')' if cur.get('to') else ''}")

    def row(s):
        m = ms.get(s, {})
        bits = [f"RS {m['rr']}" if m.get("rr") is not None else "IPO"]
        if m.get("h") is not None:
            bits.append(f"{m['h']:.1f}% off high")
        t = [x for x in tags.get(s, []) if x in ("tight", "dry", "dhi")]
        if t:
            bits.append("/".join({"tight": "tight", "dry": "vol dry", "dhi": "hi deliv"}[x] for x in t))
        warn = " ⚠️ results " + day_txt(m["ev"].split()[0]) if m.get("ev") and "Results" in m["ev"] else ""
        return f"• <b>{e(s)}</b> {e(', '.join(bits))}{warn}"
    if d.get("breakouts"):
        lines += ["", f"<b>Breakout watch</b> ({len(d['breakouts'])}) — top 5:"]
        lines += [row(s) for s in d["breakouts"][:5]]
    if d.get("pullbacks"):
        lines += ["", f"<b>Pullbacks in leaders</b> ({len(d['pullbacks'])}) — top 3:"]
        lines += [row(s) for s in d["pullbacks"][:3]]
    if d.get("ipos"):
        lines += ["", f"<b>IPO bases</b> ({len(d['ipos'])}) — top 3:"]
        for s in d["ipos"][:3]:
            i = ms.get(s, {}).get("ipo") or {}
            extra = f" · {pct(i['g'], 0)} vs issue, listed {day_txt(i['d'])}" if i.get("g") is not None else ""
            lines.append(row(s) + e(extra))
    if d.get("weekly"):
        lines += ["", f"<b>Weekly trend — above the 10-week SMA</b> ({len(d['weekly'])}) — top 3:"]
        for s in d["weekly"][:3]:
            w = ms.get(s, {}).get("wk") or {}
            extra = f" · {pct(w['d'])} vs 10W, {w['n']} wk above" if w.get("d") is not None else ""
            lines.append(row(s) + e(extra))
    if d.get("htf"):
        lines += ["", f"<b>High tight flags</b> ({len(d['htf'])}) — top 3:"]
        for s in d["htf"][:3]:
            h = ms.get(s, {}).get("htf") or {}
            if not h:
                continue
            state = ("in the flag, " + f"{-h['dist']:.1f}% below pivot" if h.get("bo") is None
                     else f"broke out {day_txt(h['bod'])[:-5]}" if h.get("bod")
                     else "broke out")
            dry = ", vol drying" if h.get("dry") is not None and h["dry"] < 0.7 else ""
            if h.get("bo") is None and h.get("et") is not None:
                state += (f", early trigger {h['et']:g} hit {day_txt(h['ebd'])[:-5]}" if h.get("ebd")
                          else f", early trigger {h['et']:g}") + f" (stop {h['es']:g})"
            lines.append(row(s) + e(f" · pole +{h['g']:.0f}%, flag −{h['fd']:.0f}%, {state}{dry} · ASM?"))
    if reg["level"] == "off":
        lines.append("<i>Risk-off: breakouts have only matched NIFTY on such days — be very selective.</i>")

    wl = watchlist.alerts(data, watch, save=save) if watch else []
    if wl:
        lines += ["", "<b>⭐ Your watchlist</b>"] + wl

    s20 = ((data.get("track") or {}).get("summary") or {}).get("20") or {}
    if s20.get("brk") and s20.get("focus"):
        ipo = f"IPO bases {pct(s20['ipo']['ex'] * 100)}, " if s20.get("ipo") else ""
        ipo += f"weekly trend {pct(s20['wkl']['ex'] * 100)}, " if s20.get("wkl") else ""
        ipo += f"HTF {pct(s20['htf']['ex'] * 100)}, " if s20.get("htf") else ""
        lines += ["", f"📈 <i>Track record (20 sessions): breakouts {pct(s20['brk']['ex'] * 100)} vs NIFTY 500, "
                      f"{ipo}focus sectors {pct(s20['focus']['avg'] * 100)} vs the average stock "
                      f"({s20['focus']['hit'] * 100:.0f}% of days).</i>"]
    lines += ["", f'<a href="{SITE}#/focus">Focus</a> · <a href="{SITE}#/swing">Swing</a> · not investment advice']
    return "\n".join(lines)


def send(token, chat, text):
    r = requests.post(API.format(token=token, method="sendMessage"), timeout=20,
                      data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": "true"})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, don't send")
    ap.add_argument("--force", action="store_true", help="send even if already sent today")
    ap.add_argument("--chat-id", action="store_true", help="print the chat id(s) that messaged your bot")
    args = ap.parse_args()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")

    if args.chat_id:
        if not token:
            sys.exit("set TELEGRAM_BOT_TOKEN first (from @BotFather)")
        r = requests.get(API.format(token=token, method="getUpdates"), timeout=20).json()
        ids = {(u.get("message") or {}).get("chat", {}).get("id") for u in r.get("result", [])}
        ids.discard(None)
        print("\n".join(map(str, ids)) or "no messages yet — send your bot a message, then rerun")
        return 0

    with open(RS_DATA, encoding="utf-8") as f:
        data = json.load(f)
    text = compose(data, watchlist.read(), save=not args.dry_run)
    if not text:
        print("brief: no decisions in rs_data.json — nothing to send")
        return 0
    session = data["decide"]["asof"]
    if args.dry_run:
        print(text)
        return 0
    if not token or not chat:
        print("brief: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipped (see send_brief.py)")
        return 0
    if not args.force and os.path.exists(SENT) and open(SENT).read().strip() == session:
        print(f"brief: already sent for {session}")
        return 0
    send(token, chat, text)
    os.makedirs(os.path.dirname(SENT), exist_ok=True)
    with open(SENT, "w") as f:
        f.write(session)
    print(f"brief: sent for {session}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
