import { useMemo, useState } from 'react';
import { useAllLevels, useDecide } from '../api/client';
import { fmtDate, mean, median } from '../lib/format';
import { scanGroups, stockIndex, type ScanDim } from '../lib/market';
import { Donut, type DonutSeg } from '../components/charts';
import { Card, ErrorBox, Loading, Segmented } from '../components/ui';

const DIMS: { value: ScanDim; label: string; unit: string }[] = [
  { value: 'sector', label: 'Sector', unit: 'sectors' }, { value: 'basic', label: 'Sub-industry', unit: 'sub-industries' },
  { value: 'cap', label: 'Market cap', unit: 'sizes' }];
const SLOTS = 5;
const CAP_SLOT: Record<string, number> = { Large: 1, Mid: 2, Small: 3, Micro: 4 };

const chg = (v: number | null, dp: number) => v == null ? <span className="muted">—</span>
  : <span className={v >= 0 ? 'pos' : 'neg'}>{v >= 0 ? '+' : ''}{v.toFixed(dp)}%</span>;

export function Scans() {
  const { levels, error, isLoading } = useAllLevels();
  const asof = useDecide().data?.asof;
  const [dim, setDim] = useState<ScanDim>('cap');
  const all = useMemo(() => (levels ? stockIndex(levels) : []), [levels]);
  if (error) return <ErrorBox error={error} />;
  if (isLoading) return <Loading />;
  const sg = scanGroups(all, dim);
  const color: Record<string, string> = {};
  sg.keys.forEach((k, i) => {
    color[k] = dim === 'cap' ? (CAP_SLOT[k] ? `var(--sc-${CAP_SLOT[k]})` : 'var(--sc-other)') : i < SLOTS ? `var(--sc-${i + 1})` : 'var(--sc-other)';
  });
  let segs: DonutSeg[] = sg.keys.filter(k => sg.count(k)).map(k => ({ name: sg.label(k), n: sg.count(k), color: color[k] }));
  if (dim !== 'cap' && segs.length > SLOTS) {
    const rest = segs.slice(SLOTS);
    segs = segs.slice(0, SLOTS).concat([{ name: `Other (${rest.length})`, n: rest.reduce((a, x) => a + x.n, 0), color: 'var(--sc-other)' }]);
  }
  const n = sg.total, unit = DIMS.find(d => d.value === dim)!.unit;
  const nGroups = sg.keys.filter(k => sg.count(k)).length;
  return (
    <Card title="Scan summary · 1-month gainers" sub={`${n} stocks up ≥ 14% in 20 sessions, ≥ ₹10 cr/day, price ≥ ₹100 · as of ${fmtDate(asof)}`}
      tools={<Segmented label="Group by" testid="scan-dim" value={dim} onChange={setDim} options={DIMS} />}>
      <div className="donut-wrap">
        <Donut segs={segs} total={n} line1="stocks" line2={`${nGroups} ${unit}`} />
        <div className="tbl-wrap">
          <table className="tbl" data-testid="scan-table">
            <thead><tr><th>{dim === 'cap' ? 'Size' : DIMS.find(d => d.value === dim)!.label}</th><th className="r">Stocks</th><th>Share of list</th>
              <th className="r">Of the group</th><th className="r" title="median RS rating (1-99)">RS</th><th className="r" title="median 3-month return">3M</th>
              <th className="r" title="whole group: average 1-day change of all its stocks">Group 1D</th>
              <th className="r" title="whole group: average 1-week change of all its stocks">Group 1W</th></tr></thead>
            <tbody>{sg.keys.map(k => {
              const list = sg.hits.get(k) ?? [], c = list.length, tot = sg.members.get(k)?.length ?? 0, grp = sg.members.get(k) ?? [];
              const share = n ? (c / n) * 100 : 0, rs = median(list.map(m => m.rr));
              return <tr key={k} style={c ? undefined : { opacity: .55 }}>
                <td className="nowrap"><span className="sw" style={{ background: c ? color[k] : 'transparent' }} />{sg.label(k)}</td>
                <td className="r tnum"><b>{c}</b></td>
                <td><span className="bar-track"><span style={{ width: `${share.toFixed(1)}%`, background: color[k] }} /></span><span className="tnum">{c ? `${share.toFixed(0)}%` : '—'}</span></td>
                <td className="r tnum">{c} of {tot} <span className="muted">({tot ? ((c / tot) * 100).toFixed(c / tot < 0.1 ? 1 : 0) : '0'}%)</span></td>
                <td className="r tnum">{rs == null ? '—' : Math.round(rs)}</td>
                <td className="r tnum">{chg(median(list.map(m => m.m3)), 0)}</td>
                <td className="r tnum">{chg(mean(grp.map(m => m.d1)), 2)}</td>
                <td className="r tnum">{chg(mean(grp.map(m => m.w1)), 2)}</td>
              </tr>;
            })}</tbody>
          </table>
          {!sg.keys.length && <div className="empty">No 1-month gainers today.</div>}
        </div>
      </div>
    </Card>
  );
}
