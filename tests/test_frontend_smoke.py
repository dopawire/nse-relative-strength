"""Frontend smoke test — boots the real server and loads the page in headless
Chromium.  Catches JS regressions (like the stat-stocks-sub null crash) that
API/unit tests cannot see.

Skipped when NO_BROWSER=1 or Playwright is unavailable.
"""
import os
import sys
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.smoke

skip_browser = pytest.mark.skipif(
    os.environ.get("NO_BROWSER") == "1",
    reason="NO_BROWSER=1 set")


@pytest.fixture(scope="module")
def server():
    if os.environ.get("NO_BROWSER") == "1":
        pytest.skip("NO_BROWSER=1 set")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import urllib.request
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/meta", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip("server did not start (no rs_data.json?)")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    if os.environ.get("NO_BROWSER") == "1":
        pytest.skip("NO_BROWSER=1 set")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chromium")
        yield b
        b.close()


@pytest.fixture(scope="module")
def browser_page(server, browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    yield page, errors
    ctx.close()


def test_page_loads_without_js_errors(browser_page):
    page, errors = browser_page
    assert errors == [], f"page errors: {errors}"
    # stat cards must be populated (the stat-stocks-sub regression)
    assert page.inner_text("#stat-stocks").strip() not in ("", "—")
    assert "in window" in page.inner_text("#stat-stocks-sub")


def test_breadth_tab_renders_macro_dashboard(browser_page):
    page, errors = browser_page
    page.query_selector('.tab[data-tab="breadth"]').click()
    page.wait_for_timeout(1500)
    assert errors == [], f"page errors: {errors}"
    assert page.query_selector("#brd-svg") is not None
    cards = page.query_selector_all(".macro-card")
    assert len(cards) >= 10, f"expected >=10 macro cards, got {len(cards)}"
    # Phase-4 tabs render too
    page.query_selector('.tab[data-tab="rotation"]').click()
    page.wait_for_timeout(1500)
    assert len(page.query_selector_all(".macro-card")) >= 5   # sector cards
    page.query_selector('.tab[data-tab="ipo"]').click()
    page.wait_for_timeout(800)
    assert errors == [], f"page errors on new tabs: {errors}"


def test_filters_present(browser_page):
    page, _ = browser_page
    assert page.query_selector("#rs-on") is not None     # RS ≥ N% chip
    assert page.query_selector("#rse-on") is not None    # RS above EMA21 chip
    assert page.query_selector("#hi-on") is not None
    assert page.query_selector("#adr-on") is not None


# ---------------------------------------------------------------------------
#  Static export mode (GitHub Pages): no backend, page falls back to
#  rs_data.json and hides the action buttons.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def static_server(tmp_path_factory):
    if os.environ.get("NO_BROWSER") == "1":
        pytest.skip("NO_BROWSER=1 set")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")
    if not (ROOT / "rs_data.json").exists():
        pytest.skip("rs_data.json not generated yet")
    import export_static
    site = tmp_path_factory.mktemp("site")
    export_static.export(out_dir=str(site))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
         "--directory", str(site)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import urllib.request
    url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            urllib.request.urlopen(url + "/index.html", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.skip("static server did not start")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_static_mode_renders_without_backend(static_server, browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(static_server + "/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    assert errors == [], f"page errors: {errors}"
    # data comes from rs_data.json — cards must be populated
    assert page.inner_text("#stat-stocks").strip() not in ("", "—")
    # backend-only buttons hidden, read-only tag shown
    assert page.query_selector("#btn-update").is_hidden()
    assert page.query_selector("#btn-refresh-stocks").is_hidden()
    assert page.query_selector(".static-tag") is not None
    # breadth tab with macro dashboard works statically too
    page.query_selector('.tab[data-tab="breadth"]').click()
    page.wait_for_timeout(1500)
    assert len(page.query_selector_all(".macro-card")) >= 10
    assert errors == [], f"page errors after breadth: {errors}"
    ctx.close()


@skip_browser
def test_deep_link_opens_new_listings_ranked(server, browser):
    """Reloading on #/ipo (or #/rotation) must stay on that tab — it used to
    bounce to Macro — and New Listings shows the ranked performance tables."""
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/#/ipo", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1000)
    assert errors == [], f"page errors: {errors}"
    assert page.query_selector('.tab.active[data-tab="ipo"]') is not None
    titles = [t.inner_text() for t in page.query_selector_all(".ipo-sec")]
    if titles:                                 # empty when no new listings today
        assert any(t.startswith(("Outperformers", "Underperformers")) for t in titles)
        ranks = [r.inner_text() for r in page.query_selector_all("td.ipo-rank")]
        assert ranks and ranks[0] == "1"
    page.goto(server + "/#/rotation", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(800)
    assert page.query_selector('.tab.active[data-tab="rotation"]') is not None
    ctx.close()


@skip_browser
def test_rotation_draws_every_session(server, browser):
    """Rotation charts are daily: one point per session (no downsampling).
    Periods are CALENDAR months back to the close on/before the same date
    (30-Oct − 6M → 30-Apr) — 6M by default so each day is hoverable — and
    All draws the full history."""
    import json
    import datetime as dt
    dates = json.loads((ROOT / "rs_data.json").read_text())["rotation"]["dates"]
    n_all = len(dates)
    last = dt.date.fromisoformat(dates[-1])
    y, m = divmod(last.year * 12 + last.month - 1 - 6, 12)
    cutoff = dt.date(y, m + 1, 1)
    nxt = dt.date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1)
    cutoff = cutoff.replace(day=min(last.day, (nxt - dt.timedelta(days=1)).day))
    base = max((i for i, d in enumerate(dates) if d <= cutoff.isoformat()), default=0)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(server + "/#/rotation", wait_until="networkidle", timeout=30000)
    page.wait_for_selector("#rot-0 polyline")
    count = "e => e.getAttribute('points').trim().split(' ').length"
    assert page.eval_on_selector("#rot-0 polyline", count) == n_all - base
    assert f"rebased to 1.0 at {dates[base]}" in page.inner_text(".mbrd-head")
    page.click(".rot-range[data-range='All']")
    page.wait_for_timeout(300)
    assert page.eval_on_selector("#rot-0 polyline", count) == n_all
    ctx.close()


@skip_browser
def test_scans_page_breaks_down_gainers(server, browser):
    """Scans: deep link works, the market-cap split lists the size classes in
    order and adds up to the scan count, and the sector tab adds up too."""
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/#/scans", wait_until="networkidle", timeout=30000)
    page.wait_for_selector(".scan-card")
    assert page.inner_text(".scan-title") == "Scan summary · 1-month gainers"
    n = int(page.text_content(".sd-hero"))              # SVG text
    names = [r.inner_text().split("\t")[0].strip() for r in page.query_selector_all(".scan-row")]
    assert names == ["Large cap", "Mid cap", "Small cap", "Micro cap", "No market cap"]
    assert sum(int(c.inner_text()) for c in page.query_selector_all(".scan-row .sg-n")) == n
    page.click("[data-dim='sector']")
    page.wait_for_timeout(200)
    assert sum(int(c.inner_text()) for c in page.query_selector_all(".scan-row .sg-n")) == n
    heads = [h.inner_text().strip().lower() for h in page.query_selector_all(".scan-table th")]
    assert heads[1:] == ["stocks", "share of list", "of the group", "rs", "3m", "group 1d", "group 1w"]
    assert errors == [], errors
    ctx.close()


@skip_browser
def test_flows_page_draws_monthly_bars(server, browser):
    """FII / DII: deep link works, one bar pair per month in range, the table
    matches, and the range buttons change the month count."""
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/#/flows", wait_until="networkidle", timeout=30000)
    page.wait_for_selector(".scan-card")
    if page.query_selector(".fl-svg") is None:          # no flows data in this checkout
        assert "No FII / DII data" in page.inner_text("#content")
    else:
        assert page.inner_text(".scan-title") == "FII / DII cash flows · monthly net"
        n3 = len(page.query_selector_all(".fl-col"))
        assert 0 < n3 <= 36
        assert len(page.query_selector_all(".fl-table tbody tr")) == n3
        assert len(page.query_selector_all(".fl-col .fl-fii")) == n3
        page.click("[data-range='1Y']")
        page.wait_for_timeout(200)
        assert len(page.query_selector_all(".fl-col")) == min(12, n3)
        page.hover(".fl-col:last-child .fl-hit")
        assert "FII net" in page.inner_text("#fl-tip")
    assert errors == [], errors
    ctx.close()


@skip_browser
def test_focus_and_swing_pages(server, browser):
    """Focus gives one answer + sector / size verdicts; Swing shows the regime
    checklist and the setup tables — both deep-linkable, no JS errors."""
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/#/focus", wait_until="networkidle", timeout=30000)
    page.wait_for_selector(".dc-answer")
    assert page.inner_text(".dc-answer-t").startswith("Focus on ")
    assert "Market:" in page.inner_text(".dc-answer-s")
    caps = [r.inner_text() for r in page.query_selector_all(".dc-grid section:nth-child(2) .dc-row-h b")]
    assert set(caps) <= {"Large cap", "Mid cap", "Small cap", "Micro cap"} and caps
    page.goto(server + "/#/swing", wait_until="networkidle", timeout=30000)
    page.wait_for_selector(".dc-checks")
    assert len(page.query_selector_all(".dc-checks li")) == 7
    assert page.inner_text(".scan-title") == "Swing-trading desk"
    rows = page.query_selector_all(".dc-tr")
    if rows:                                   # click opens the stock RS chart
        rows[0].click()
        page.wait_for_selector("#stock-modal.open", timeout=5000)
    assert errors == [], errors
    ctx.close()
