import { useBreadth, useLevel, useMeta } from '../api/client';
import { fmtDate } from '../lib/format';
import { Oscillator } from '../components/charts';
import { Card, Empty, ErrorBox, Loading, PageHeader } from '../components/ui';

export function Breadth() {
  const bq = useBreadth();
  const macro = useLevel('macro').data;
  const meta = useMeta().data;
  if (bq.error) return <ErrorBox error={bq.error} />;
  if (!bq.data) return <Loading />;
  const b = bq.data;
  if (b.osc.length < 2) return <Empty>Not enough history yet — run a full build.</Empty>;
  const pct = Object.fromEntries((macro?.groups ?? []).map(g => [g.name, g.pct]));
  const div = b.divergence;
  const src = meta?.src ?? {};
  const srcDates = Object.keys(src).sort();
  return <>
    <PageHeader title="Market breadth" sub={<>McClellan-style oscillator: 19- vs 39-day EMA of ratio-adjusted (advancers − decliners) across {b.n.toLocaleString('en-IN')} stocks · {b.span}.</>}
      actions={<span className={`tag lg ${b.latest >= 0 ? 'pos' : 'neg'}`}>Latest {b.latest >= 0 ? '+' : ''}{b.latest.toFixed(1)}</span>} />
    {div?.state && div.state !== 'none' && <div className={`banner ${div.state === 'bearish' ? 'bear' : 'bull'}`}>
      <b>{div.state === 'bearish' ? 'Bearish divergence' : 'Bullish divergence'}</b> — {div.note}</div>}
    <Card title="NSE market breadth oscillator" sub={<>Latest <b className={b.latest >= 0 ? 'pos' : 'neg'}>{b.latest >= 0 ? '+' : ''}{b.latest.toFixed(1)}</b> on {fmtDate(b.dates[b.dates.length - 1])} · ≈ −40 and below flags oversold / possible bottoms, ≈ +40 and above overbought — reversal warnings</>}>
      <Oscillator testid="breadth-chart" dates={b.dates} osc={b.osc} height={340} perPoint={4.2} />
      <blockquote className="note" style={{ borderLeft: '3px solid var(--border-strong)', paddingLeft: 12, marginTop: 14 }}>
        Zanger: "I use one custom oscillator in particular which uses market breadth advance-decline data to give me a heads up on trend strength and potential reversals. When it hits extreme lows or highs, it usually means a reversal of some sort is ahead."
      </blockquote>
    </Card>
    {b.macros.length > 0 && <Card title="Macro breadth" count={`${b.macros.length} macros`} sub="the same oscillator per macro group · hover for values">
      <div className="mini-grid" data-testid="macro-breadth">{b.macros.map(m => (
        <div className="card mini" key={m.name}>
          <div className="mini-h"><span className="mini-n">{m.name}</span>
            <span><span className={`tag ${m.latest >= 0 ? 'pos' : 'neg'}`}>{m.latest >= 0 ? '+' : ''}{m.latest.toFixed(1)}</span>
              {pct[m.name] != null && <span className="tag plain">RS {Math.round(pct[m.name] * 100)}%</span>}</span>
          </div>
          <Oscillator dates={m.dates} osc={m.osc} height={140} axis={false} zones={false} />
        </div>))}</div>
    </Card>}
    {srcDates.length > 0 && <details className="foot">
      <summary>Data provenance — {srcDates.length} date(s) not from Yahoo daily bars</summary>
      <ul>{srcDates.map(d => <li key={d}>{d} — <code>{src[d]}</code></li>)}</ul>
      <p>Sources: <code>investing.com</code> official index close · <code>bhavcopy</code> NSE official EOD file · <code>intraday</code> rebuilt from 5-minute bars · <code>synthetic</code> equal-weight stock returns.</p>
    </details>}
  </>;
}
