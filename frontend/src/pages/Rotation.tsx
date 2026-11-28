import { useState } from 'react';
import { useRotation } from '../api/client';
import { fmtDate } from '../lib/format';
import { rebase, ROT_RANGES, rotStartIndex } from '../lib/market';
import { LineChart } from '../components/charts';
import { Card, Empty, ErrorBox, Loading, Segmented } from '../components/ui';

export function RotationPage() {
  const rq = useRotation();
  const [range, setRange] = useState('6M');
  if (rq.error) return <ErrorBox error={rq.error} />;
  if (!rq.data) return <Loading />;
  const { dates: all, groups } = rq.data;
  if (!groups.length) return <Empty>No rotation data yet — run a build.</Empty>;
  const start = rotStartIndex(all, ROT_RANGES[range]);
  const dates = all.slice(start);
  const rows = groups.map(g => {
    const rs = rebase(g.rs, start);
    return { name: g.name, rs, total: (rs[rs.length - 1] / rs[0] - 1) * 100 };
  }).sort((a, b) => b.total - a.total);
  return <>
    <div className="sec-h" style={{ marginBottom: 14 }}>
      <p className="page-intro" style={{ margin: 0 }}>Chain-linked equal-weight sector index ÷ NIFTY 500, rebased to 1.0 on {fmtDate(dates[0])} · {dates.length - 1} sessions to {fmtDate(dates[dates.length - 1])} · strongest first.</p>
      <Segmented label="Period" testid="rot-range" value={range} onChange={setRange} options={Object.keys(ROT_RANGES).map(k => ({ value: k, label: k }))} />
    </div>
    <div className="mini-grid" data-testid="rotation-grid">{rows.map(r => (
      <Card key={r.name} className="mini">
        <div className="mini-h" style={{ marginTop: -6 }}><span className="mini-n">{r.name}</span>
          <span className={`tag ${r.total >= 0 ? 'pos' : 'neg'}`}>{r.total >= 0 ? '+' : ''}{r.total.toFixed(1)}%</span></div>
        <LineChart dates={dates} height={130} baseline={1} fmt={v => v.toFixed(3)}
          series={[{ values: r.rs, color: r.total >= 0 ? 'var(--pos)' : 'var(--neg)', label: 'RS', width: 1.5 }]} />
      </Card>))}</div>
  </>;
}
