"""Frontend smoke tests — the real server (login ON, a test user) and the
built React app (frontend/dist) in headless Chromium.  Catches UI regressions
that API / unit tests can't see: every page renders without JS errors, the
filters, selections, exports and charts work, and access needs a login.

Skipped when NO_BROWSER=1, Playwright is missing, or the app isn't built
(cd frontend && npm ci && npm run build).
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.smoke
USER, PW = "smoke", "smoke test password"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if os.environ.get("NO_BROWSER") == "1":
        pytest.skip("NO_BROWSER=1 set")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        pytest.skip("frontend not built (cd frontend && npm run build)")
    if not (ROOT / "rs_data.json").exists():
        pytest.skip("no rs_data.json")
    tmp = tmp_path_factory.mktemp("auth")
    env = dict(os.environ, NSE_RS_AUTH="1", NSE_RS_USERS=str(tmp / "users.json"),
               NSE_RS_SECRET="smoke-secret", NSE_RS_COOKIE_SECURE="0")
    subprocess.run([sys.executable, "-m", "backend.users", "add", USER, "--admin"], cwd=ROOT,
                   env=dict(env, NSE_RS_PASSWORD=PW), check=True, capture_output=True)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
                             "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip("server did not start")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chromium")
        yield b
        b.close()


def new_page(browser, server, width=1440, height=900, login=True):
    ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True)
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    if login:
        page.goto(server + "/login", wait_until="networkidle")
        page.fill("#u", USER)
        page.fill("#p", PW)
        page.click("button.btn.primary")
        page.wait_for_url(server + "/", timeout=15000)
    return ctx, page


def decide():
    return json.loads((ROOT / "rs_data.json").read_text())["decide"]


def test_login_required_and_wrong_password(server, browser):
    ctx, page = new_page(browser, server, login=False)
    page.goto(server + "/swing", wait_until="networkidle")
    assert "/login" in page.url                                    # bounced to the login page
    assert urllib.request.urlopen(server + "/api/health").status == 200
    try:
        urllib.request.urlopen(server + "/api/meta")
        raise AssertionError("API answered without a login")
    except urllib.error.HTTPError as e:
        assert e.code == 401
    page.fill("#u", USER)
    page.fill("#p", "wrong password!!")
    page.click("button.btn.primary")
    page.wait_for_selector(".err")
    assert "wrong username or password" in page.inner_text(".err")
    page.fill("#p", PW)
    page.click("button.btn.primary")
    page.wait_for_url("**/swing", timeout=15000)                   # back where it started
    assert page.errors == [], page.errors
    ctx.close()


def test_overview(server, browser):
    ctx, page = new_page(browser, server)
    page.wait_for_selector("[data-testid=stat-regime]")
    assert page.inner_text("[data-testid=overview-answer]").startswith("Focus on ")
    assert page.inner_text("[data-testid=stat-stocks]").split("\n")[1].replace(",", "").isdigit()
    assert page.query_selector("[data-testid=regime-chip]")
    assert page.errors == [], page.errors
    ctx.close()


def test_rankings_master_detail(server, browser):
    ctx, page = new_page(browser, server)
    page.goto(server + "/rankings/sector", wait_until="networkidle")
    page.wait_for_selector("[data-testid=level-table] tr.grp-row")
    n_groups = len(page.query_selector_all("tr.grp-row"))
    assert n_groups > 5
    tabs = [b.inner_text() for b in page.query_selector_all("[data-testid=level-tabs] button")]
    assert len(tabs) == 4 and tabs[0].startswith("Macro")
    # the top group is selected and its stocks are shown on the right
    assert page.locator("tr.grp-row.sel").count() == 1
    page.wait_for_selector("[data-testid^=members-] tbody tr")
    first = page.locator("tr.grp-row").nth(1)
    first.click()
    gid = first.get_attribute("data-gid")
    page.wait_for_selector(f"[data-testid=members-{gid}] tbody tr")
    assert page.locator("tr.grp-row.sel").get_attribute("data-gid") == gid
    assert len(page.query_selector_all(f"[data-testid=members-{gid}] tbody tr:first-child .emas i")) == 5
    assert page.locator(".dh-chart svg").count() == 1                 # group RS line over the window
    page.keyboard.press("Escape")
    page.focus("[data-testid=level-table]")
    page.keyboard.press("ArrowDown")                                  # keyboard moves the selection
    assert page.locator("tr.grp-row.sel").get_attribute("data-gid") != gid
    for b in page.query_selector_all("[data-testid=ema-filters] button"):
        b.click()                                                    # above all 5 EMAs
    page.wait_for_timeout(200)
    info = page.inner_text("[data-testid=filter-info]")
    assert "group(s)" in info
    page.fill("[data-testid=rank-search]", "zzzz-no-such-stock")
    page.wait_for_timeout(200)
    assert "No stocks match" in page.inner_text("main")
    page.fill("[data-testid=rank-search]", "")
    page.click("text=Select visible")
    sel = int(page.inner_text("[data-testid=sel-count] b"))
    assert sel > 0
    page.goto(server + "/rankings/macro", wait_until="networkidle")
    page.wait_for_selector("tr.grp-row")
    deltas = page.query_selector_all("[data-testid=level-table] tr.grp-row .chg")
    assert deltas, "Δ column empty"
    assert page.errors == [], page.errors
    ctx.close()


def test_swing_lists_and_tradingview_exports(server, browser):
    D = decide()
    ctx, page = new_page(browser, server)
    page.goto(server + "/swing", wait_until="networkidle")
    page.wait_for_selector("[data-testid=regime-checks] li")
    assert len(page.query_selector_all("[data-testid=regime-checks] li")) == len(D["regime"]["checks"])
    for key, tbl, n in (("breakouts", "tbl-breakouts", 25), ("pullbacks", "tbl-pullbacks", 15),
                        ("ipos", "tbl-ipos", 15), ("weekly", "tbl-weekly", 25), ("htf", "tbl-htf", 15)):
        rows = page.query_selector_all(f"[data-testid={tbl}] tbody tr")
        assert len(rows) == min(n, len(D.get(key) or [])), key
        if rows:
            assert rows[0].get_attribute("data-sym") == D[key][0], key       # rank order kept
    if D["breakouts"]:
        with page.expect_download() as dl:
            page.click("[data-testid=tv-brk] [data-act=dl]")
        txt = open(dl.value.path()).read()
        want = ",".join("NSE:" + s.replace("&", "_").replace("-", "_") for s in D["breakouts"])
        assert txt == want
        with page.expect_download() as dl:
            page.click("button[data-act=all]")
        allt = open(dl.value.path()).read()
        assert allt.startswith("###Breakout watch,") and want in allt
    if D.get("htf"):
        heads = [h.inner_text().lower() for h in page.query_selector_all("[data-testid=tbl-htf] th")]
        for h in ("pole", "flag", "pivot", "vs pivot", "early trigger", "flag vol"):
            assert h in heads                                     # (headers are CSS-uppercased)
    page.locator("[data-testid=tbl-breakouts] tbody tr").first.click()        # stock chart
    page.wait_for_selector("[data-testid=stock-chart] svg path")
    page.keyboard.press("Escape")
    assert not page.query_selector("[data-testid=stock-modal]")
    assert "Breakout watch vs NIFTY 500" in page.inner_text("[data-testid=swing-track]")
    assert page.errors == [], page.errors
    ctx.close()


def test_focus_breadth_rotation_flows_scans_listings(server, browser):
    ctx, page = new_page(browser, server)
    page.goto(server + "/focus", wait_until="networkidle")
    assert page.inner_text("[data-testid=focus-answer]").startswith("Focus on ")
    assert "Focus sectors vs the average stock" in page.inner_text("[data-testid=focus-track]")

    page.goto(server + "/breadth", wait_until="networkidle")
    page.wait_for_selector("[data-testid=breadth-chart] svg path")
    assert len(page.query_selector_all("[data-testid=macro-breadth] .mini")) >= 10

    page.goto(server + "/rotation", wait_until="networkidle")
    page.wait_for_selector("[data-testid=rotation-grid] svg path")
    page.click("[data-testid=rot-range] >> text=3M")
    assert page.query_selector("[data-testid=rot-range] button.on").inner_text() == "3M"

    page.goto(server + "/flows", wait_until="networkidle")
    page.wait_for_selector("[data-testid=flow-chart] svg")
    assert "monthly net" in page.inner_text(".card-t")
    n3y = len(page.query_selector_all("[data-testid=flow-table] tbody tr"))
    assert 0 < n3y <= 36
    if page.query_selector("[data-testid=flow-view]"):
        page.click("[data-testid=flow-view] >> text=Daily")
        page.wait_for_timeout(200)
        assert "daily net" in page.inner_text(".card-t")
        assert 0 < len(page.query_selector_all("[data-testid=flow-table] tbody tr")) <= 21

    page.goto(server + "/scans", wait_until="networkidle")
    page.wait_for_selector("[data-testid=scan-table]")
    heads = [h.inner_text().lower() for h in page.query_selector_all("[data-testid=scan-table] th")]
    assert heads[1:3] == ["stocks", "share of list"]
    page.click("[data-testid=scan-dim] >> text=Sector")
    assert page.query_selector("[data-testid=scan-dim] button.on").inner_text() == "Sector"

    page.goto(server + "/listings", wait_until="networkidle")
    page.wait_for_timeout(300)
    assert page.query_selector("[data-testid=listings]") or "No new listings" in page.inner_text("main")
    assert page.errors == [], page.errors
    ctx.close()


def test_search_opens_stock_and_phone_layout(server, browser):
    sym = decide()["breakouts"][0]
    ctx, page = new_page(browser, server, width=390, height=844)
    assert page.evaluate("document.documentElement.scrollWidth") <= 390     # no sideways scroll
    page.fill("[data-testid=stock-search]", sym.lower())
    page.wait_for_selector(".search-res button")
    page.keyboard.press("Enter")
    page.wait_for_selector("[data-testid=stock-chart] svg path")
    page.keyboard.press("Escape")
    page.click("button.menu-btn")                                           # off-canvas navigation
    page.click("nav >> text=Swing setups") if page.query_selector("nav") else page.click("text=Swing setups")
    page.wait_for_url("**/swing")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert page.errors == [], page.errors
    ctx.close()


def test_logout(server, browser):
    ctx, page = new_page(browser, server)
    page.click("[data-testid=user-menu]")
    page.click("[data-testid=logout]")
    page.wait_for_url("**/login**", timeout=15000)
    page.goto(server + "/swing", wait_until="networkidle")
    assert "/login" in page.url
    ctx.close()
