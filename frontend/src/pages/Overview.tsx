import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useAllLevels, useBreadth, useDecide, useFlows, useMeta, useTrack } from '../api/client';
import { CAP_LABEL, crore, fmtDate, fmtPrice, shortName } from '../lib/format';
import { stockIndex, type Stock } from '../lib/market';
import { REGIME } from '../lib/decide';
import { useApp } from '../components/AppContext';
import { Oscillator } from '../components/charts';
import { Card, ErrorBox, Loading, Stat, Tone } from '../components/ui';

function MiniList({ title, to, syms, byS, render }: {
  title: string; to: string; syms: string[]; byS: Map<string, Stock>; render: (m: Stock) => React.ReactNode;
}) {
  const { openStock } = useApp();
  const list = syms.slice(0, 5).map(s => byS.get(s)).filter((m): m is Stock => !!m);
  return (
    <Card title={title} count={syms.length} tools={<Link className="btn sm ghost" to={to}>All →</Link>} flush>
      {list.length ? <table className="tbl"><tbody>{list.map(m => (
        <tr key={m.s} className="clickable" onClick={() => openStock(m.s)}>
          <td><span className="stk-name">{shortName(m.n)}</span><span className="stk-sym">{m.s}</span></td>
          <td className="r tnum">{render(m)}</td>
        </tr>))}</tbody></table> : <div className="empty" style={{ padding: 24 }}>None today</div>}
    </Card>
  );
}

export function Overview() {
  const dq = useDecide();
  const meta = useMeta().data;
  const breadth = useBreadth().data;
  const flows = useFlows().data;
  const track = useTrack().data;
  const { levels } = useAllLevels();
  const byS = useMemo(() => new Map((levels ? stockIndex(levels) : []).map(m => [m.s, m])), [levels]);
  if (dq.error) return <ErrorBox error={dq.error} />;
  if (!dq.data || !meta) return <Loading />;
  const D = dq.data, reg = D.regime, R = REGIME[reg.level];
  const month = flows?.months[flows.months.length - 1];
  const s20 = track?.summary?.['20'];
  const tail = breadth ? Math.min(breadth.osc.length, 130) : 0;
  const capTop = D.caps.find(r => r.name === D.cap);
  return <>
    <div className="grid four">
      <Stat testid="stat-regime" label="Market regime" value={<span className={`r-${reg.level}`}>{R.word}</span>} sub={`${reg.pass} of ${reg.known} checks pass · ${R.size.split(' · ')[0]}`} />
      <Stat testid="stat-breadth" label="Breadth oscillator" value={breadth ? `${breadth.latest >= 0 ? '+' : ''}${breadth.latest.toFixed(1)}` : '—'}
        tone={breadth ? (breadth.latest >= 0 ? 'pos' : 'neg') : undefined} sub={breadth ? `${breadth.n.toLocaleString('en-IN')} stocks · ±40 = extremes` : ''} />
      <Stat testid="stat-fii" label="FII net this month" value={month ? crore(month.fii) : '—'} tone={month ? (month.fii >= 0 ? 'pos' : 'neg') : undefined}
        sub={month ? <>DII {crore(month.dii)}{month.to ? ` · to ${fmtDate(month.to)}` : ''}</> : ''} />
      <Stat testid="stat-stocks" label="Stocks ranked" value={meta.n_window.toLocaleString('en-IN')}
        sub={`${(meta.n_stocks - meta.n_window).toLocaleString('en-IN')} left out today${meta.illiquid.length ? ` (${meta.illiquid.length} thinly traded)` : ''}`} />
    </div>

    <div className="answer" style={{ marginTop: 16 }} data-testid="overview-answer">
      <span className={`dot ${reg.level}`} />
      <div style={{ flex: 1 }}>
        <div className="answer-t">Focus on {D.focus.map((n, i) => <span key={n}>{i > 0 && (i === D.focus.length - 1 ? (D.focus.length > 2 ? ', and ' : ' and ') : ', ')}<b>{n}</b></span>)}
          {capTop && <>, in <b>{(CAP_LABEL[capTop.name] ?? capTop.name).toLowerCase()}s</b></>}.</div>
        <div className="answer-s">{R.line.charAt(0).toUpperCase() + R.line.slice(1)}{D.turning.length > 0 && <> Turning up: {D.turning.join(', ')}.</>}</div>
      </div>
      <Link className="btn sm" to="/focus">Details</Link>
    </div>

    <div className="grid three" style={{ marginTop: 16 }}>
      <MiniList title="Breakout watch" to="/swing#list-breakouts" syms={D.breakouts} byS={byS}
        render={m => <>RS <b>{m.rr ?? '—'}</b><span className="sub2">{m.h == null ? '' : `${m.h.toFixed(1)}% off high`}</span></>} />
      <MiniList title="High tight flags" to="/swing#list-htf" syms={D.htf ?? []} byS={byS}
        render={m => m.htf ? (m.htf.bo != null ? <>broke out<span className="sub2">pivot {fmtPrice(m.htf.p)}</span></>
          : <>{(-m.htf.dist).toFixed(1)}% below<span className="sub2">pivot {fmtPrice(m.htf.p)}</span></>) : null} />
      <MiniList title="Weekly trend" to="/swing#list-weekly" syms={D.weekly ?? []} byS={byS}
        render={m => <>RS <b>{m.rr ?? '—'}</b><span className="sub2">{m.wk ? <Tone v={m.wk.d} /> : null} vs 10W</span></>} />
    </div>

    <div className="grid two" style={{ marginTop: 16 }}>
      <Card title="Breadth, last 6 months" tools={<Link className="btn sm ghost" to="/breadth">Open →</Link>}>
        {breadth && tail > 1 ? <Oscillator dates={breadth.dates.slice(-tail)} osc={breadth.osc.slice(-tail)} height={200} /> : <Loading />}
      </Card>
      <Card title="How the screens have done" sub="average excess return vs NIFTY 500 over the next 20 sessions" tools={<Link className="btn sm ghost" to="/swing">Track record →</Link>} flush>
        {s20 ? <table className="tbl"><tbody>
          {([['brk', 'Breakout watch'], ['pb', 'Pullbacks'], ['ipo', 'IPO bases'], ['wkl', 'Weekly trend'], ['htf', 'High tight flags']] as const).map(([k, label]) => {
            const v = s20[k];
            return <tr key={k}><td>{label}</td><td className="r tnum">{v ? <><Tone v={v.ex * 100} /><span className="hit">{(v.hit * 100).toFixed(0)}% beat N500</span></> : '—'}</td></tr>;
          })}
          {s20.focus && <tr><td>Focus sectors vs the average stock</td><td className="r tnum"><Tone v={s20.focus.avg * 100} /><span className="hit">{(s20.focus.hit * 100).toFixed(0)}% of days ahead</span></td></tr>}
        </tbody></table> : <div className="empty">No results yet.</div>}
      </Card>
    </div>
    <p className="foot">Data as of the {fmtDate(D.asof)} close (built {meta.generated} IST). Completed sessions only — today's numbers arrive with the evening build after 15:30. Not investment advice.</p>
  </>;
}
