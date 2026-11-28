// Track record tables (Focus + Swing pages).
import type { EdgeStat, ListStat, Track, TrackHorizon } from '../api/types';
import { CAP_LABEL, fmtDate } from '../lib/format';
import { REGIME } from '../lib/decide';
import { Empty, Tone } from '../components/ui';

const HZ = ['5', '10', '20'];

const edgeCell = (e: EdgeStat | null | undefined, word: string) => !e
  ? <td className="r muted">—</td>
  : <td className="r tnum"><Tone v={e.avg * 100} /><span className="hit">{(e.hit * 100).toFixed(0)}% {word}</span></td>;
const listCell = (l: ListStat | null | undefined) => !l
  ? <td className="r muted">—</td>
  : <td className="r tnum"><Tone v={l.ex * 100} /><span className="hit">{(l.hit * 100).toFixed(0)}% beat N500</span></td>;

function Intro({ t }: { t: Track }) {
  if (!t.n || !t.since) return null;
  return <p className="note">{t.n} sessions of calls since {fmtDate(t.since)}{t.live_since
    ? ` (logged live since ${fmtDate(t.live_since)}; earlier days rebuilt from price history with the same rules)`
    : ' — rebuilt from price history with the same rules'}. Results use the next 5 / 10 / 20 sessions. Days overlap, so treat hit rates as a guide, not proof.</p>;
}

const Head = () => <thead><tr><th>Call</th><th className="r">5 sessions</th><th className="r">10 sessions</th><th className="r">20 sessions</th></tr></thead>;

export function FocusTrack({ t }: { t: Track | undefined }) {
  const s = t?.summary;
  if (!t || !s || !Object.keys(s).length) return <Empty>The first results appear 5 sessions after the first logged call.</Empty>;
  const row = (label: string, key: 'focus' | 'avoid' | 'cap', word: string, tip: string) =>
    <tr><td title={tip}>{label}</td>{HZ.map(h => <Cell key={h}>{edgeCell(s[h]?.[key], word)}</Cell>)}</tr>;
  return <>
    <Intro t={t} />
    <div className="tbl-wrap"><table className="tbl" data-testid="focus-track"><Head /><tbody>
      {row('Focus sectors vs the average stock', 'focus', 'of days ahead', 'average return of the focus sectors’ stocks minus the average stock')}
      {row('Avoid sectors trailed the average stock by', 'avoid', 'of days right', 'average stock minus the avoid sectors’ stocks — positive = the avoid call was right')}
      {row('Size pick vs the average stock', 'cap', 'of days ahead', 'the picked size class minus the average stock')}
    </tbody></table></div>
    <h3 style={{ fontSize: 14, margin: '22px 0 8px' }}>Recent calls</h3>
    <div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>Date</th><th>Market</th><th>Focus sectors</th><th>Size</th>
        <th className="r" title="focus sectors vs the average stock over the next 10 sessions (5 when 10 aren't in yet)">Result</th></tr></thead>
      <tbody>{(t.rows ?? []).slice(0, 12).map(r => {
        const x = (r.h['10'] || r.h['5']) as { focus?: number | null } | undefined;
        const which = r.h['10'] ? '10d' : r.h['5'] ? '5d' : '';
        return <tr key={r.date}>
          <td className="nowrap">{fmtDate(r.date)}{!r.bt && <span className="tag accent" style={{ marginLeft: 6 }}>live</span>}</td>
          <td><span className={`tag ${r.regime === 'on' ? 'pos' : r.regime === 'mixed' ? 'warn' : 'neg'}`}>{REGIME[r.regime].word}</span></td>
          <td className="soft">{r.focus.join(', ')}</td>
          <td className="soft nowrap">{r.cap ? CAP_LABEL[r.cap] ?? r.cap : '—'}</td>
          <td className="r tnum">{x && x.focus != null ? <Tone v={x.focus * 100} /> : <span className="muted" title="fewer than 5 sessions since the call">pending</span>}
            {which && <span className="hit">{which}</span>}</td>
        </tr>;
      })}</tbody></table></div>
  </>;
}

const Cell = ({ children }: { children: React.ReactNode }) => <>{children}</>;

export function SwingTrack({ t }: { t: Track | undefined }) {
  const s = t?.summary;
  if (!t || !s || !Object.keys(s).length) return <Empty>The first results appear 5 sessions after the first logged call.</Empty>;
  const lists: [keyof TrackHorizon, string, string][] = [
    ['brk', 'Breakout watch', "average return of the day's top 25 breakout candidates minus NIFTY 500"],
    ['pb', 'Pullbacks', "average return of the day's top 15 pullback candidates minus NIFTY 500"],
    ['ipo', 'IPO bases', "average return of the day's top 15 IPO bases minus NIFTY 500"],
    ['wkl', 'Weekly trend', "average return of the day's top 25 weekly-trend stocks minus NIFTY 500"],
    ['htf', 'High tight flags', "average return of the day's high-tight-flag list minus NIFTY 500"],
  ];
  const regs = (h: string, key: 'regime' | 'brk_regime') => {
    const r = s[h]?.[key] as Record<string, { n: number; nifty?: number; ex?: number; up?: number; hit?: number }> | undefined;
    if (!r) return <td className="muted">—</td>;
    return <td className="reg-cell">{(['on', 'mixed', 'off'] as const).filter(k => r[k]).map(k =>
      <div key={k}>{REGIME[k].word} <Tone v={(key === 'regime' ? r[k].nifty! : r[k].ex!) * 100} />
        <i>{(((key === 'regime' ? r[k].up : r[k].hit) ?? 0) * 100).toFixed(0)}% {key === 'regime' ? 'up' : 'beat'} · {r[k].n}d</i></div>)}</td>;
  };
  return <>
    <Intro t={t} />
    <div className="tbl-wrap"><table className="tbl" data-testid="swing-track"><Head /><tbody>
      {lists.map(([k, label, tip]) => <tr key={k}><td title={tip}>{label} vs NIFTY 500</td>
        {HZ.map(h => <Cell key={h}>{listCell(s[h]?.[k] as ListStat | null)}</Cell>)}</tr>)}
      <tr><td title="breakout watch vs NIFTY 500, split by the market regime on the day of the call">Breakouts by regime</td>{HZ.map(h => <Cell key={h}>{regs(h, 'brk_regime')}</Cell>)}</tr>
      <tr><td title="NIFTY 500's average return after days with each regime reading">NIFTY 500 after each regime</td>{HZ.map(h => <Cell key={h}>{regs(h, 'regime')}</Cell>)}</tr>
    </tbody></table></div>
    <p className="foot">Lists are bought at that day's close and held, without stops or costs — the raw edge of the screen, not a trading result.</p>
  </>;
}
