"""Shared test guards."""
import pytest

import build_rs


@pytest.fixture(autouse=True)
def _isolated_official_fills(tmp_path, monkeypatch):
    """Never let a test read or write the real NSE-fill sidecar in the cache dir."""
    monkeypatch.setattr(build_rs, "OFFICIAL_FILLS", str(tmp_path / "official_fills.json"))
