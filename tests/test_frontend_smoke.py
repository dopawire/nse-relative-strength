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
    page.query_selector_all(".tab")[-1].click()
    page.wait_for_timeout(1500)
    assert errors == [], f"page errors: {errors}"
    assert page.query_selector("#brd-svg") is not None
    cards = page.query_selector_all(".macro-card")
    assert len(cards) >= 10, f"expected >=10 macro cards, got {len(cards)}"


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
    page.query_selector_all(".tab")[-1].click()
    page.wait_for_timeout(1500)
    assert len(page.query_selector_all(".macro-card")) >= 10
    assert errors == [], f"page errors after breadth: {errors}"
    ctx.close()
