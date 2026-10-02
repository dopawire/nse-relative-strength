#!/usr/bin/env python3
"""Export a read-only static site into site/ — no backend required.

The frontend auto-detects the absence of the API and falls back to
rs_data.json, so the export is simply: frontend assets + data + .nojekyll.
Deployed to GitHub Pages by .github/workflows/pages.yml.

    python3 export_static.py          # writes ./site/
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "frontend", "dist")


def export(out_dir=None, src_dir=None):
    out = out_dir or os.path.join(HERE, "site")
    src = src_dir or SRC
    data = os.path.join(HERE, "rs_data.json")
    if not os.path.exists(data):
        sys.exit("rs_data.json missing — run build_rs.py first")
    if os.path.isdir(out):
        shutil.rmtree(out)
    shutil.copytree(src, out)
    shutil.copy(data, os.path.join(out, "rs_data.json"))
    open(os.path.join(out, ".nojekyll"), "w").close()
    total = sum(os.path.getsize(os.path.join(out, f))
                for f in os.listdir(out))
    print(f"static site written to {out} ({total / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    export()
