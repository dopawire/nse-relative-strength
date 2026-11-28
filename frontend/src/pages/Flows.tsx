import { useState } from 'react';
import { useFlows } from '../api/client';
import { crore, dayLabel, fmtDate, MON, monLabel, num0 } from '../lib/format';
import { FLOW_RANGES, flowRows, type FlowView } from '../lib/market';
import { PairBars } from '../components/charts';
import { Card, Empty, ErrorBox, Loading, PageHeader, Segmented } from '../components/ui';

const cell = (v: number) => <span className={v >= 0 ? 'pos' : 'neg'}>{v >= 0 ? '+' : '−'}{Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>;

export function FlowsPage() {
  const fq = useFlows();
  const [view, setView] = useState<FlowView>('M');
  const [range, setRange] = useState<Record<FlowView, string>>({ M: '3Y', D: '1M' });
  if (fq.error) return <ErrorBox error={fq.error} />;
  if (!fq.data) return <Loading />;
  const { months, days } = fq.data;
  if (!months.length) return <Empty>No FII / DII data yet — run <code>refresh_flows.py</code> and a build.</Empty>;
  const daily = view === 'D' && days.length > 0;
  const v: FlowView = daily ? 'D' : 'M';
  const rows = flowRows(months, days, v, range[v]);
  const last = rows[rows.length - 1];
  const running = !daily && !!last.to && last.to.slice(0, 7) === last.k;
  const sum = (k: 'fii' | 'dii') => rows.reduce((a, r) => a + r[k], 0);
  const firstGross = daily ? days.find(r => r.fb != null)?.d : null;
  const netOnly = daily && rows.some(r => r.fb == null);
  const tick = (i: number, slot: number) => {
    const k = rows[i].k;
    if (!daily) {
      const every = slot >= 34 ? 1 : slot >= 11 ? 3 : 12, mo = +k.slice(5, 7);
      if (every !== 1 && (mo - 1) % every) return '';
      return every === 12 ? k.slice(0, 4) : every === 3 && mo !== 1 ? MON[mo - 1] : monLabel(k).replace(' 20', " '");
    }
    const step = Math.ceil(46 / slot);
    if (step <= 5) return (rows.length - 1 - i) % step ? '' : `${+k.slice(8)} ${MON[+k.slice(5, 7) - 1]}`;
    const m = k.slice(0, 7);
    if (i > 0 && rows[i - 1].k.slice(0, 7) === m) return '';
    if (i === 0 && rows.length > 1 && rows[1].k.slice(0, 7) !== m) return '';
    const mo = +m.slice(5);
    return mo === 1 ? monLabel(m).replace(' 20', " '") : MON[mo - 1];
  };
  const sub = daily
    ? `NSE provisional cash market, ₹ crore · ${fmtDate(rows[0].k)} – ${fmtDate(last.k)} · ${rows.length} sessions`
    : `NSE provisional cash market, ₹ crore · ${monLabel(rows[0].k)} – ${monLabel(last.k)}${running ? ` (to ${fmtDate(last.to)})` : ''}`;
  return <>
    <PageHeader title="FII / DII flows" sub="Foreign and domestic institutional net buying in the cash market — NSE provisional figures, ₹ crore." />
    <Card title={`FII / DII cash flows · ${daily ? 'daily' : 'monthly'} net`} sub={sub}
      tools={<>
        {days.length > 0 && <Segmented label="View" testid="flow-view" value={v} onChange={setView}
          options={[{ value: 'M', label: 'Monthly' }, { value: 'D', label: 'Daily' }]} />}
        <Segmented label="Period" testid="flow-range" value={range[v]} onChange={x => setRange(r => ({ ...r, [v]: x }))}
          options={Object.keys(FLOW_RANGES[v]).map(k => ({ value: k, label: k }))} />
      </>}>
      <div className="legend" style={{ marginBottom: 8 }}>
        <span><i style={{ background: 'var(--fii)' }} />FII net <b className="tnum">{crore(sum('fii'))}</b></span>
        <span><i style={{ background: 'var(--dii)' }} />DII net <b className="tnum">{crore(sum('dii'))}</b></span>
        <span className="muted">totals over the {rows.length} {daily ? 'sessions' : 'months'} shown</span>
      </div>
      <PairBars testid="flow-chart" tick={tick}
        rows={rows.map((r, i) => ({ k: r.k, a: r.fii, b: r.dii, partial: running && i === rows.length - 1 }))}
        tip={r => <><b>{daily ? dayLabel(r.k) : monLabel(r.k)}{r.partial && last.to ? ` · to ${fmtDate(last.to)}` : ''}</b>
          <div><i className="sw" style={{ background: 'var(--fii)' }} />FII net {crore(r.a)}</div>
          <div><i className="sw" style={{ background: 'var(--dii)' }} />DII net {crore(r.b)}</div>
          <div className="muted">Combined {crore(r.a + r.b)}</div></>} />
    </Card>
    <Card flush>
      <div className="tbl-wrap" style={{ maxHeight: 560, overflowY: 'auto' }}>
        <table className="tbl" data-testid="flow-table">
          <thead><tr><th>{daily ? 'Session' : 'Month'}</th><th className="r">FII net</th><th className="r">DII net</th><th className="r">FII + DII</th>
            <th className="r" title="FII gross purchase">FII buy</th><th className="r" title="FII gross sales">FII sell</th>
            <th className="r" title="DII gross purchase">DII buy</th><th className="r" title="DII gross sales">DII sell</th></tr></thead>
          <tbody>{rows.slice().reverse().map(r => <tr key={r.k}>
            <td className="nowrap">{daily ? dayLabel(r.k) : monLabel(r.k)}{r === last && running && <span className="muted" style={{ fontSize: 11 }}> to {fmtDate(r.to)}</span>}</td>
            <td className="r tnum">{cell(r.fii)}</td><td className="r tnum">{cell(r.dii)}</td><td className="r tnum">{cell(r.fii + r.dii)}</td>
            <td className="r tnum soft">{num0(r.fb)}</td><td className="r tnum soft">{num0(r.fs)}</td>
            <td className="r tnum soft">{num0(r.db)}</td><td className="r tnum soft">{num0(r.ds)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </Card>
    {netOnly && <p className="foot">Gross buy / sell are recorded from {fmtDate(firstGross)}; earlier sessions carry the net figures only (stockezee.com day-by-day archive, which matches NSE's own figures on every session both have).</p>}
  </>;
}
