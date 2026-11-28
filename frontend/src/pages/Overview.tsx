import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAllLevels, useBreadth, useDecide, useFlows, useMeta, useTrack } from '../api/client';
import type { GroupRow } from '../api/types';
import { CAP_LABEL, crore, fmtDate, fmtPrice, sgn, shortName } from '../lib/format';
import { stockIndex, type Stock } from '../lib/market';
import { QUAD_TIP, REGIME } from '../lib/decide';
import { useApp } from '../components/AppContext';
import { AreaSpark, Gauge, MiniBars, Oscillator } from '../components/charts';
import { Card, ErrorBox, Kpi, Loading, PageHeader, RsBadge, StockCell, Tabs, Tone } from '../components/ui';

type SetupKey = 'breakouts' | 'pullbacks' | 'htf' | 'weekly' | 'ipos';
const SETUPS: { key: SetupKey; label: string; anchor: string }[] = [
  { key: 'breakouts', label: 'Breakouts', anchor: 'list-breakouts' }, { key: 'htf', label: 'High tight flags', anchor: 'list-htf' },
  { key: 'weekly', label: 'Weekly trend', anchor: 'list-weekly' }, { key: 'pullbacks', label: 'Pullbacks', anchor: 'list-pullbacks' },
  { key: 'ipos', label: 'IPO bases', anchor: 'list-ipos' },
];

/** sector tile colour from its 1-month return vs the average stock */
function heatStyle(rel: number | null): React.CSSProperties {
  const v = Math.max(-1, Math.min(1, (rel ?? 0) / 8));
  const a = Math.round(8 + Math.abs(v) * 42);            // % of the data colour mixed into the surface
  return { background: `color-mix(in srgb, ${v >= 0 ? 'var(--pos)' : 'var(--neg)'} ${a}%, var(--surface-2))` };
}

function SetupList({ syms, byS, keyName }: { syms: string[]; byS: Map<string, Stock>; keyName: SetupKey }) {
  const { openStock } = useApp();
  const list = syms.slice(0, 8).map(s => byS.get(s)).filter((m): m is Stock => !!m);
  if (!list.length) return <div className="empty" style={{ padding: 36 }}>Nothing passes this screen today.</div>;
  const metric = (m: Stock): ReactNode => {
    if (keyName === 'htf' && m.htf) return m.htf.bo != null
      ? <><span className="pos">broke out</span><span className="sub2">pivot {fmtPrice(m.htf.p)}</span></>
      : <>{(-m.htf.dist).toFixed(1)}% below<span className="sub2">pivot {fmtPrice(m.htf.p)}</span></>;
    if (keyName === 'weekly' && m.wk) return <><Tone v={m.wk.d} /><span className="sub2">vs 10W SMA</span></>;
    if (keyName === 'ipos' && m.ipo) return <><Tone v={m.ipo.g} dp={0} /><span className="sub2">vs issue</span></>;
    return <>{m.h == null ? '—' : `${m.h.toFixed(1)}%`}<span className="sub2">off high</span></>;
  };
  return (
    <div className="tbl-wrap"><table className="tbl"><tbody>{list.map(m => (
      <tr key={m.s} className="clickable" onClick={() => openStock(m.s)}>
        <td><StockCell name={shortName(m.n)} sym={m.s} /></td>
        <td className="r nowrap">{fmtPrice(m.l)}<span className="sub2"><Tone v={m.w1} /> 1W</span></td>
        <td className="r nowrap">{metric(m)}</td>
        <td className="r"><RsBadge v={m.rr} /></td>
      </tr>))}</tbody></table></div>
  );
}

export function Overview() {
  const dq = useDecide();
  const meta = useMeta().data;
  const breadth = useBreadth().data;
  const flows = useFlows().data;
  const track = useTrack().data;
  const { levels } = useAllLevels();
  const nav = useNavigate();
  const [tab, setTab] = useState<SetupKey>('breakouts');
  const all = useMemo(() => (levels ? stockIndex(levels) : []), [levels]);
  const byS = useMemo(() => new Map(all.map(m => [m.s, m])), [all]);
  if (dq.error) return <ErrorBox error={dq.error} />;
  if (!dq.data || !meta) return <Loading />;
  const D = dq.data, reg = D.regime, R = REGIME[reg.level];
  const month = flows?.months[flows.months.length - 1];
  const monthDays = flows && month ? flows.days.filter(d => d.d.slice(0, 7) === month.m).map(d => d.fii) : [];
  const s20 = track?.summary?.['20'];
  const capTop = D.caps.find(r => r.name === D.cap);
  const withD1 = all.filter(m => m.d1 != null);
  const up = withD1.filter(m => (m.d1 ?? 0) > 0).length, down = withD1.filter(m => (m.d1 ?? 0) < 0).length;
  const leaders = all.filter(m => (m.rr ?? 0) >= 80 && m.e[1] === 1).length;
  const sectors = [...D.sectors].sort((a, b) => (b.rel1 ?? -99) - (a.rel1 ?? -99));
  const tail = breadth ? Math.min(breadth.osc.length, 130) : 0;
  const listOf = (k: SetupKey) => (D[k] ?? []) as string[];
  const screens: [keyof NonNullable<typeof s20>, string][] = [
    ['brk', 'Breakout watch'], ['pb', 'Pullbacks'], ['ipo', 'IPO bases'], ['wkl', 'Weekly trend'], ['htf', 'High tight flags']];
  const maxEx = Math.max(0.01, ...screens.map(([k]) => Math.abs(((s20?.[k] as { ex?: number } | null)?.ex) ?? 0)));
  const focusNames = D.focus;

  return <>
    <PageHeader title="Market overview" sub={<>Everything that matters for the next session — from the {fmtDate(D.asof)} close.</>}
      actions={<><Link className="btn" to="/focus">Focus</Link><Link className="btn primary" to="/swing">Swing setups →</Link></>} />

    <section className="card hero" data-testid="stat-regime">
      <div className="hero-in">
        <Gauge pass={reg.pass} total={reg.known} level={reg.level} />
        <div>
          <div className="hero-k">Today's call · market <span className={`r-${reg.level}`}>{R.word}</span></div>
          <div className="hero-t" data-testid="overview-answer">Focus on {focusNames.map((n, i) => <span key={n}>{i > 0 && (i === focusNames.length - 1 ? (focusNames.length > 2 ? ', and ' : ' and ') : ', ')}<b>{n}</b></span>)}
            {capTop && <>, in <b>{(CAP_LABEL[capTop.name] ?? capTop.name).toLowerCase()}s</b></>}.</div>
          <div className="hero-s">{R.line.charAt(0).toUpperCase() + R.line.slice(1)}</div>
          <div className="pills">
            {focusNames.map(n => <span key={n} className="pill"><span className="tri">▲</span>{n}</span>)}
            {capTop && <span className="pill cap">{CAP_LABEL[capTop.name] ?? capTop.name}</span>}
            {D.turning.map(n => <span key={n} className="pill" title="turning up — early"><span className="tri" style={{ color: 'var(--info)' }}>↗</span>{n}</span>)}
          </div>
        </div>
        <div className="hero-side">
          {R.sizing.map(([k, v]) => <div className="hs" key={k}><span>{k}</span><b>{v}</b></div>)}
        </div>
      </div>
    </section>

    <div className="grid four" style={{ marginTop: 18 }}>
      <Kpi testid="stat-breadth" label="Breadth oscillator"
        value={breadth ? `${breadth.latest >= 0 ? '+' : ''}${breadth.latest.toFixed(1)}` : '—'} valueTone={breadth ? (breadth.latest >= 0 ? 'pos' : 'neg') : undefined}
        sub={breadth ? `${breadth.n.toLocaleString('en-IN')} stocks · ±40 marks extremes` : ''}
        chart={breadth ? <AreaSpark values={breadth.osc.slice(-60)} zero /> : null} />
      <Kpi testid="stat-fii" label="FII net this month"
        value={month ? crore(month.fii) : '—'} valueTone={month ? (month.fii >= 0 ? 'pos' : 'neg') : undefined}
        sub={month ? <>DII {crore(month.dii)}{month.to ? ` · to ${fmtDate(month.to)}` : ''}</> : ''}
        chart={monthDays.length ? <MiniBars values={monthDays} /> : null} />
      <Kpi label="Participation today"
        value={withD1.length ? `${Math.round((up / withD1.length) * 100)}%` : '—'}
        sub={<><span className="pos">{up.toLocaleString('en-IN')} up</span> · <span className="neg">{down.toLocaleString('en-IN')} down</span> · {leaders} RS-80 leaders in uptrends</>}
        chart={withD1.length ? <div className="hbar-track" style={{ marginTop: 14, height: 8 }}>
          <div className="hbar-fill" style={{ left: 0, width: `${(up / withD1.length) * 100}%`, background: 'var(--pos)' }} />
          <div className="hbar-fill" style={{ right: 0, width: `${(down / withD1.length) * 100}%`, background: 'var(--neg)', opacity: .8 }} /></div> : null} />
      <Kpi testid="stat-stocks" label="Stocks ranked" value={meta.n_window.toLocaleString('en-IN')}
        sub={`${(meta.n_stocks - meta.n_window).toLocaleString('en-IN')} left out today${meta.illiquid.length ? ` (${meta.illiquid.length} thinly traded)` : ''} · ${meta.ipo.length} new listings`}
        chart={<div className="hbar-track" style={{ marginTop: 14, height: 8 }}>
          <div className="hbar-fill" style={{ left: 0, width: `${(meta.n_window / meta.n_stocks) * 100}%`, background: 'var(--accent-grad)' }} /></div>} />
    </div>

    <div className="grid wide-l" style={{ marginTop: 18 }}>
      <Card title="Sector heatmap" sub="1-month median return vs the average stock · click a sector for its rankings"
        tools={<span className="heat-legend">weaker<i />stronger</span>}>
        <div className="heat" data-testid="sector-heatmap">
          {sectors.map((r: GroupRow) => (
            <button key={r.name} type="button" className="heat-t" style={heatStyle(r.rel1)} title={`${r.name} — ${QUAD_TIP[r.quad]}`}
              onClick={() => nav('/rankings/sector', { state: { q: r.name } })}>
              <span className="heat-n">{r.name}</span>
              <span className="heat-v"><b>{sgn(r.rel1)}</b><span>{r.quad}</span></span>
            </button>))}
        </div>
      </Card>
      <Card title="Top setups" sub="tonight's best candidates · click one for its chart" flush
        tools={<Link className="btn sm ghost" to={`/swing#${SETUPS.find(s => s.key === tab)!.anchor}`}>All →</Link>}>
        <Tabs testid="setup-tabs" value={tab} onChange={setTab} tabs={SETUPS.map(s => ({ value: s.key, label: s.label, n: listOf(s.key).length }))} />
        <SetupList syms={listOf(tab)} byS={byS} keyName={tab} />
      </Card>
    </div>

    <div className="grid wide-l" style={{ marginTop: 18 }}>
      <Card title="Market breadth" sub="last 6 months · green above zero, red below" tools={<Link className="btn sm ghost" to="/breadth">Open →</Link>}>
        {breadth && tail > 1 ? <Oscillator dates={breadth.dates.slice(-tail)} osc={breadth.osc.slice(-tail)} height={230} /> : <Loading what="Loading" />}
      </Card>
      <Card title="How the screens have done" sub="vs NIFTY 500 · next 20 sessions" flush
        tools={<Link className="btn sm ghost" to="/swing">Details →</Link>}>
        {s20 ? <div style={{ paddingBottom: 6 }}>
          {screens.map(([k, label]) => {
            const v = s20[k] as { ex: number; hit: number } | null;
            const w = v ? (Math.abs(v.ex) / maxEx) * 50 : 0;
            return <div className="hbar" key={k}>
              <span>{label}<span className="sub2">{v ? `${(v.hit * 100).toFixed(0)}% beat NIFTY 500` : 'no results yet'}</span></span>
              <div className="hbar-track">
                <div className="hbar-zero" style={{ left: '50%' }} />
                {v && <div className="hbar-fill" style={{ [v.ex >= 0 ? 'left' : 'right']: '50%', width: `${w}%`, background: v.ex >= 0 ? 'var(--pos)' : 'var(--neg)' }} />}
              </div>
              <b className="r tnum" style={{ textAlign: 'right' }}>{v ? <Tone v={v.ex * 100} /> : '—'}</b>
            </div>;
          })}
          {s20.focus && <div className="hbar">
            <span>Focus sectors<span className="sub2">vs the average stock · {(s20.focus.hit * 100).toFixed(0)}% of days</span></span>
            <div className="hbar-track"><div className="hbar-zero" style={{ left: '50%' }} />
              <div className="hbar-fill" style={{ [s20.focus.avg >= 0 ? 'left' : 'right']: '50%', width: `${(Math.abs(s20.focus.avg) / maxEx) * 50}%`, background: 'var(--accent)' }} /></div>
            <b style={{ textAlign: 'right' }}><Tone v={s20.focus.avg * 100} /></b>
          </div>}
        </div> : <div className="empty">No results yet.</div>}
      </Card>
    </div>
    <p className="foot">Data as of the {fmtDate(D.asof)} close (built {meta.generated} IST). Completed sessions only — today's numbers arrive with the evening build after 15:30. Not investment advice.</p>
  </>;
}
