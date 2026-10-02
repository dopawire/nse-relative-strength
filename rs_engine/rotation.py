"""Full-history chain-linked group RS-lines vs the benchmark (rotation view)."""

from collections import defaultdict


def compute_rotation(universe, cache, bench, covered_dates, level="sector"):
    """Full-history RS line per group (chain-linked equal-weight index vs the
    benchmark, both rebased to 1.0 at the first covered date).  Handles stocks
    listing/delisting mid-history via daily cross-sectional returns.  Returns
    {"dates": [...], "groups": [{"name", "rs"} ...]} for the rotation view."""
    by_group = defaultdict(list)
    for u in universe:
        ser = cache.get(u["sym"])
        if ser and u.get(level):
            by_group[u[level]].append(ser)

    def chain(series):
        idx = [100.0]
        for i in range(1, len(covered_dates)):
            prev, cur = covered_dates[i - 1], covered_dates[i]
            rets = [s[cur] / s[prev] - 1 for s in series
                    if s.get(prev) and s.get(cur)]
            idx.append(idx[-1] * (1 + (sum(rets) / len(rets) if rets else 0.0)))
        return idx

    bench_idx = chain([bench])
    groups = []
    for name, series in sorted(by_group.items()):
        if len(series) < 5:
            continue
        gi = chain(series)
        rs = [round(gi[i] / bench_idx[i], 4) for i in range(len(covered_dates))]
        groups.append({"name": name, "rs": rs})
    return {"dates": covered_dates, "groups": groups}

