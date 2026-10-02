"""Tests for the static site export (the GitHub Pages read-only deployment)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

import export_static


def test_export_produces_complete_site(tmp_path):
    if not (ROOT / "rs_data.json").exists():
        pytest.skip("rs_data.json not generated yet")
    out = export_static.export(out_dir=str(tmp_path / "site"))
    out = Path(out)
    for name in ("index.html", "app.js", "app.css", "rs_data.json", ".nojekyll"):
        assert (out / name).exists(), name
    data = json.loads((out / "rs_data.json").read_text())
    assert data["meta"]["n_stocks"] > 0
    assert data["levels"] and data["breadth"]["dates"]


def test_export_is_idempotent(tmp_path):
    if not (ROOT / "rs_data.json").exists():
        pytest.skip("rs_data.json not generated yet")
    out1 = Path(export_static.export(out_dir=str(tmp_path / "site")))
    out2 = Path(export_static.export(out_dir=str(tmp_path / "site")))
    assert sorted(p.name for p in out1.iterdir()) == \
        sorted(p.name for p in out2.iterdir())
