import { useMemo } from 'react';
import { useAllLevels, useDecide, useTrack } from '../api/client';
import type { GroupRow } from '../api/types';
import { CAP_LABEL, fmtDate, pctTxt, sgn } from '../lib/format';
import { stockIndex } from '../lib/market';
import { QUAD_TIP, REGIME } from '../lib/decide';
import { Card, Empty, ErrorBox, Loading, PageHeader, StockLink } from '../components/ui';
import { FocusTrack } from './Track';

export const QuadTag = ({ q }: { q: string }) => <span className={`tag quad-${q}`} title={QUAD_TIP[q]}>{q}</span>;

export function Focus() {
  const { levels, error, isLoading } = useAllLevels();
  const dq = useDecide();
  const track = useTrack().data;
  const byS = useMemo(() => new Map((levels ? stockIndex(levels) : []).map(m => [m.s, m])), [levels]);
  if (error || dq.error) return <ErrorBox error={error || dq.error} />;
  if (isLoading || dq.isLoading) return <Loading />;
  const D = dq.data;
  if (!D?.sectors?.length) return <Empty>No Focus data yet — run a build (<code>build_rs.py</code>).</Empty>;
  const reg = D.regime, R = REGIME[reg.level], base = D.base;
  const sec = Object.fromEntries(D.sectors.map(r => [r.name, r]));
  const focus = D.focus.map(n => sec[n]).filter(Boolean);
  const turning = D.turning.map(n => sec[n]).filter(Boolean);
  const avoid = D.avoid.map(n => sec[n]).filter(Boolean);
  const capTop = D.caps.find(r => r.name === D.cap);
  const capName = (k: string) => CAP_LABEL[k] ?? k;
  const line = (r: GroupRow) => `median stock ${sgn(r.m1)} in 1M and ${sgn(r.m3)} in 3M (all stocks ${sgn(base.m1)} / ${sgn(base.m3)}) · `
    + `${pctTxt(r.p50)} above the 50-day EMA · ${r.lead} leader${r.lead === 1 ? '' : 's'} (RS ≥ 80)`;
  const SecRow = ({ r, extra }: { r: GroupRow; extra?: React.ReactNode }) => (
    <div className="row-item">
      <div className="row-h"><b>{r.name}</b><QuadTag q={r.quad} />
        <span className="row-score" title="composite score vs other sectors (0-100)">{r.score.toFixed(0)}</span></div>
      <div className="row-line">{line(r)}</div>{extra}
    </div>
  );
  return <>
    <PageHeader title="Where to focus" sub={<>One answer from relative strength, momentum, participation and breadth — as of the {fmtDate(D.asof)} close.</>} />
    <div className="answer" data-testid="focus-answer">
      <span className={`dot ${reg.level}`} />
      <div>
        <div className="answer-t">Focus on {focus.map((r, i) => <span key={r.name}>{i > 0 && (i === focus.length - 1 ? (focus.length > 2 ? ', and ' : ' and ') : ', ')}<b>{r.name}</b></span>)}
          {capTop && <>, in <b>{capName(capTop.name).toLowerCase()}s</b></>}.</div>
        <div className="answer-s">Market: <b className={`r-${reg.level}`}>{R.word}</b> ({reg.pass} of {reg.known} checks) — {R.line}</div>
      </div>
    </div>
    <ul className="bullets">
      <li><b>Sectors:</b> {focus.map(r => `${r.name} (${r.quad.toLowerCase()})`).join(', ')} lead on combined strength.</li>
      {turning.length > 0 && <li><b>Turning up:</b> {turning.map(r => `${r.name} (${sgn(r.rel1)} vs the average stock in 1M)`).join(', ')} — early, watch for follow-through.</li>}
      {capTop && <li><b>Size:</b> {capName(capTop.name)} is strongest — median {sgn(capTop.m1)} in 1M, {pctTxt(capTop.p50)} above the 50-day EMA.</li>}
      {avoid.length > 0 && <li><b>Avoid for now:</b> {avoid.map(r => r.name).join(', ')}.</li>}
    </ul>
    <div className="grid two" style={{ marginTop: 18 }}>
      <Card title="Sectors to focus">
        {focus.map(r => <SecRow key={r.name} r={r} extra={<div className="row-sub">
          {r.inds?.length ? <>Strongest industries: {r.inds.join(', ')}</> : null}
          {r.leaders?.length ? <>{r.inds?.length ? ' · ' : ''}Leaders: {r.leaders.map(s => <StockLink key={s} sym={s} name={byS.get(s)?.n} />)}</> : null}
        </div>} />)}
      </Card>
      <Card title="Market cap" sub="which size class is leading">
        {D.caps.map((r, i) => <div className="row-item" key={r.name}>
          <div className="row-h"><b>{capName(r.name)}</b>
            <span className={`tag ${i === 0 ? 'pos' : i === 1 ? 'info' : 'plain'}`}>{i === 0 ? 'Focus' : i === 1 ? 'Next best' : 'Lighter'}</span>
            <span className="row-score">{r.score.toFixed(0)}</span></div>
          <div className="row-line">median {sgn(r.w1)} 1W · {sgn(r.m1)} 1M · {sgn(r.m3)} 3M · {pctTxt(r.p50)} above 50-EMA · {pctTxt(r.nearHi)} within 10% of a 52-week high</div>
        </div>)}
      </Card>
      {turning.length > 0 && <Card title="Turning up — watch next">{turning.map(r => <SecRow key={r.name} r={r} />)}</Card>}
      {avoid.length > 0 && <Card title="Avoid for now">{avoid.map(r => <SecRow key={r.name} r={r} />)}</Card>}
    </div>
    <div style={{ marginTop: 16 }}>
      <Card title="Track record — did these calls work?"><FocusTrack t={track} /></Card>
    </div>
    <p className="foot">How it's decided: sectors with ≥ 5 stocks are ranked on 1M (30%) and 3M (20%) median return vs the average stock,
      share above the 50-day EMA (20%), share of RS ≥ 80 leaders (15%) and the group's RS_STS% (15%).
      Leading / Improving / Weakening / Lagging compare 3M and 1M with the average stock. Size classes are ranked the same way. Not investment advice.</p>
  </>;
}
