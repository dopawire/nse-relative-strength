"""Watchlist alerts for the evening brief.

The list lives OUTSIDE the repo (the site is public): ~/.config/nse-rs/
watchlist.txt, one symbol per line.  Starring a stock on the local site
(backend mode) writes it; you can also edit the file by hand.

Alerts, per watched stock, from the finished rs_data.json:
  🚀 entered the breakout watch / ↩️ a pullback setup
  ✅ closed back above its 20-day EMA / ⚠️ closed below it  (vs the last brief)
  🏔 at a 52-week high
  📅 results (or another board meeting) within 14 days
"""
import json
import os

from rs_engine.config import CACHE_DIR

WATCHLIST = os.environ.get("NSE_RS_WATCHLIST",
                           os.path.expanduser("~/.config/nse-rs/watchlist.txt"))
STATE = os.path.join(CACHE_DIR, ".watch_state.json")
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def read(path=None):
    path = path or WATCHLIST
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        syms = [x.strip().upper() for x in f if x.strip() and not x.startswith("#")]
    return list(dict.fromkeys(syms))


def write(syms, path=None):
    path = path or WATCHLIST
    os.makedirs(os.path.dirname(path), exist_ok=True)
    clean = [s for s in dict.fromkeys(x.strip().upper() for x in syms)
             if s and s.replace("-", "").replace("&", "").isalnum() and len(s) <= 20]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# nse-rs watchlist — one NSE symbol per line (synced from the site's ☆)\n")
        f.write("".join(s + "\n" for s in clean))
    os.replace(tmp, path)
    return clean


def _load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def alerts(data, watch, state_path=None, save=True):
    """→ list of Telegram-HTML lines for the watched stocks that did something."""
    import html
    state_path = state_path or STATE
    d = data.get("decide") or {}
    asof = d.get("asof")
    ms = {}
    for lv in data.get("levels", []):
        if lv.get("key") == "macro":
            for g in lv["groups"]:
                for m in g["members"]:
                    ms[m["s"]] = m
    brk = {s: i + 1 for i, s in enumerate(d.get("breakouts", []))}
    pb = {s: i + 1 for i, s in enumerate(d.get("pullbacks", []))}
    state = _load_state(state_path)
    out = []
    for s in watch:
        m = ms.get(s)
        if not m:
            continue
        e20 = (m.get("e") or [-1])[0]
        st = state.get(s, {})
        # the flag before this session: the stored "prev" when this session
        # was already seen (a re-run), else the last stored flag
        prev = st.get("prev") if st.get("d") == asof else st.get("e20")
        state[s] = {"d": asof, "e20": e20, "prev": prev}
        what = []
        if s in brk:
            what.append(f"🚀 in the breakout watch (#{brk[s]})")
        elif s in pb:
            what.append(f"↩️ pullback setup (#{pb[s]})")
        if prev == 0 and e20 == 1:
            what.append("✅ closed back above its 20-day EMA")
        elif prev == 1 and e20 == 0:
            what.append("⚠️ closed below its 20-day EMA")
        if m.get("h") is not None and m["h"] <= 0.5:
            what.append("🏔 at a 52-week high")
        if m.get("ev"):
            day, *rest = m["ev"].split()
            y, mo, dd = day.split("-")
            what.append(f"📅 {' '.join(rest)} {int(dd)} {MON[int(mo) - 1]}")
        if what:
            chg = m.get("d1")
            out.append(f"• <b>{html.escape(s)}</b>"
                       f"{'' if chg is None else f' ({chg:+.1f}%)'} — " + "; ".join(what))
    if save and asof:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    return out
