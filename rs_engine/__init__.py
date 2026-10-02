"""rs_engine — computation core for the NSE Relative-Strength pipeline.

Modules:
  config    constants + nse_holidays.csv loader (+ config.toml overrides)
  maths     RS maths (percentrank, EMAs, corporate-action breaks, ADR)
  breadth   market-breadth oscillators (total + per macro) and divergence
  rotation  full-history group RS-lines vs the benchmark
  snapshot  daily ranking archive + deltas + IPO watch
  report    printable daily digest
  render    rs_view.html template + SVG helpers

build_rs.py keeps the data layer (caches, fetchers, gap-fills) and the CLI,
and re-exports everything here for backwards compatibility.
"""
