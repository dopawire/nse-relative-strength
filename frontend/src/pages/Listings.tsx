import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useMeta } from '../api/client';
import type { IpoWatch } from '../api/types';
import { fmtDate, fmtPrice } from '../lib/format';
import { useApp } from '../components/AppContext';
import { Card, Empty, ErrorBox, Loading } from '../components/ui';

const pct = (v: number | null) => v == null ? <span className="muted">—</span>
  : <span className={v > 0 ? 'pos' : v < 0 ? 'neg' : ''}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>;

function Table({ title, list, note, win }: { title: string; list: IpoWatch[]; note: string; win: number }) {
  const { openStock } = useApp();
  if (!list.length) return null;
  return (
    <Card title={title} count={`${list.length} · ${note}`} flush>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>#</th><th>Stock</th><th>Listed</th><th className="r">Days</th><th className="r" title="close on the listing day">Listing close</th>
          <th className="r">LTP</th><th className="r" title="LTP vs listing-day close">Since listing</th><th className="r" title="NIFTY 500 over the same dates">NIFTY 500</th>
          <th className="r" title="(1 + stock) / (1 + NIFTY 500) − 1">vs NIFTY 500</th>
          <th className="r" title={`Sessions until the stock has a full ${win}-day window and gets a regular RS ranking`}>Full RS in</th></tr></thead>
        <tbody>{list.map((i, k) => <tr key={i.s} className="clickable" onClick={() => openStock(i.s)}>
          <td className="muted tnum">{k + 1}</td>
          <td><span className="stk-name">{i.n}</span><span className="stk-sym">{i.s}</span></td>
          <td className="nowrap">{fmtDate(i.first)}</td>
          <td className="r tnum">{i.days}</td>
          <td className="r tnum">{fmtPrice(i.base)}</td>
          <td className="r tnum">{fmtPrice(i.ltp)}</td>
          <td className="r tnum">{pct(i.ret)}</td>
          <td className="r tnum">{pct(i.bret)}</td>
          <td className="r tnum"><b>{pct(i.xret)}</b></td>
          <td className="r tnum">{i.uc ? <span className="muted">awaiting NSE classification</span> : `${i.eta} session${i.eta === 1 ? '' : 's'}`}</td>
        </tr>)}</tbody>
      </table></div>
    </Card>
  );
}

export function Listings() {
  const mq = useMeta();
  const loc = useLocation();
  const [q, setQ] = useState<string>((loc.state as { q?: string } | null)?.q ?? '');
  if (mq.error) return <ErrorBox error={mq.error} />;
  if (!mq.data) return <Loading />;
  const ipo = mq.data.ipo, win = mq.data.window || 26;
  const toks = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = toks.length ? ipo.filter(i => toks.every(t => (i.n + ' ' + i.s).toLowerCase().includes(t))) : ipo;
  const measured = shown.filter(i => i.xret != null);
  const out = measured.filter(i => i.xret! >= 0).sort((a, b) => b.xret! - a.xret!);
  const under = measured.filter(i => i.xret! < 0).sort((a, b) => a.xret! - b.xret!);
  const fresh = shown.filter(i => i.xret == null);
  return <>
    <div className="sec-h" style={{ marginBottom: 14 }}>
      <p className="page-intro" style={{ margin: 0 }}>Listings awaiting their first {win}-day ranking · {out.length} of {measured.length} beating NIFTY 500 since the listing-day close · click one for its RS chart.</p>
      <input className="input" style={{ width: 260 }} placeholder="Filter new listings…" value={q} onChange={e => setQ(e.target.value)} data-testid="ipo-search" />
    </div>
    {!ipo.length ? <Empty>No new listings awaiting ranking right now.</Empty>
      : !shown.length ? <Empty>No new listings match “{q}”.</Empty> : <div data-testid="listings">
        <Table title="Outperformers" list={out} note="ranked best first" win={win} />
        <Table title="Underperformers" list={under} note="ranked worst first" win={win} />
        <Table title="Too new to measure" list={fresh} note="first session only" win={win} />
      </div>}
  </>;
}
