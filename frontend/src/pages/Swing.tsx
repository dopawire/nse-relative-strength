import { useMemo, type ReactNode } from 'react';
import { useAllLevels, useDecide, useTrack } from '../api/client';
import type { HtfInfo } from '../api/types';
import { CAP_LABEL, fmtDate, fmtDay, fmtPrice, pctTxt, sgn, shortName } from '../lib/format';
import { stockIndex, type Stock } from '../lib/market';
import { REGIME, TAG_TIP, TAG_TONE, TAG_WORD } from '../lib/decide';
import { saveText, tvSections } from '../lib/tv';
import { useApp } from '../components/AppContext';
import { IconDownload } from '../components/Icons';
import { TvButtons } from '../components/TvButtons';
import { Card, Empty, ErrorBox, EvBadge, Loading, PageHeader, RsBadge, StockCell, StockLink, Tone } from '../components/ui';
import { Gauge, Sparkline } from '../components/charts';
import { QuadTag } from './Focus';
import { SwingTrack } from './Track';

interface Col { h: string; tip?: string; r?: boolean; cell: (m: Stock, i: number) => ReactNode }

function SetupTable({ list, max, cols, empty, testid }: { list: Stock[]; max: number; cols: Col[]; empty: string; testid: string }) {
  const { openStock } = useApp();
  if (!list.length) return <Empty>{empty}</Empty>;
  return (
    <div className="tbl-wrap">
      <table className="tbl" data-testid={testid}>
        <thead><tr>{cols.map(c => <th key={c.h} title={c.tip} className={c.r ? 'r' : ''}>{c.h}</th>)}</tr></thead>
        <tbody>{list.slice(0, max).map((m, i) => (
          <tr key={m.s} className="clickable" data-sym={m.s} onClick={() => openStock(m.s)}>
            {cols.map(c => <td key={c.h} className={c.r ? 'r tnum' : ''}>{c.cell(m, i)}</td>)}
          </tr>))}</tbody>
      </table>
    </div>
  );
}

const pctOrDash = (v: number | null | undefined, dp = 1) => (v == null ? '—' : `${v.toFixed(dp)}%`);

export function Swing() {
  const { levels, error, isLoading } = useAllLevels();
  const dq = useDecide();
  const track = useTrack().data;
  const byS = useMemo(() => new Map((levels ? stockIndex(levels) : []).map(m => [m.s, m])), [levels]);
  if (error || dq.error) return <ErrorBox error={error || dq.error} />;
  if (isLoading || dq.isLoading) return <Loading />;
  const D = dq.data;
  if (!D?.regime) return <Empty>No Swing data yet — run a build (<code>build_rs.py</code>).</Empty>;

  const reg = D.regime, R = REGIME[reg.level], S = D.rules as Record<string, number> & { pbOffHigh: number[] };
  const IR = D.ipo_rules ?? {}, WR = D.weekly_rules ?? {};
  // older rs_data.json (built before the HTF list) has no rules: defaults
  const hr = (D.htf_rules ?? {}) as Record<string, number | number[] | undefined>;
  const HR = { minPole: (hr.minPole as number) ?? 100, poleWeeks: (hr.poleWeeks as number) ?? 9,
    maxFlag: (hr.maxFlag as number) ?? 25, flagWeeks: (hr.flagWeeks as number[]) ?? [1, 8] };
  const hot = new Set(D.hot ?? []);
  const inLead = (m: Stock) => hot.has(m.industry ?? '') || hot.has(m.sector ?? '');
  const pick = (syms: string[] | undefined) => (syms ?? []).map(s => byS.get(s)).filter((m): m is Stock => !!m);
  const breakouts = pick(D.breakouts), pullbacks = pick(D.pullbacks), extended = pick(D.extended);
  const ipos = pick(D.ipos), weekly = pick(D.weekly), htfs = pick(D.htf);
  const inBrk = new Set(D.breakouts.slice(0, 25)), inIpo = new Set((D.ipos ?? []).slice(0, 15));
  const ind = Object.fromEntries(D.industries.map(r => [r.name, r]));
  const leadInd = D.lead_ind.map(n => ind[n]).filter(Boolean);
  const tags = (m: Stock, extra: ReactNode = null) => <>{extra}{(D.tags?.[m.s] ?? []).map(t =>
    <span key={t} className={`tag ${TAG_TONE[t] ?? 'plain'}`} title={TAG_TIP[t]}>{TAG_WORD[t] ?? t}</span>)}</>;

  // ---- shared columns
  const cNum: Col = { h: '#', cell: (_m, i) => <span className="rank">{i + 1}</span> };
  const cStock = (withCap = true): Col => ({ h: 'Stock', cell: m => <StockCell name={shortName(m.n)} sym={m.s}
    extra={<>{withCap && m.cap ? ` · ${(CAP_LABEL[m.cap] ?? '').replace(' cap', '')}` : ''}
      <span className="stk-ind" title={m.industry ?? ''}>{inLead(m) && <span className="hot" title="in a leading industry / sector">●</span>}{m.industry}</span>
      <EvBadge ev={m.ev} /></>} /> });
  const cSpark: Col = { h: 'RS trend', tip: 'the stock’s RS line over the 26-session window', cell: m => <Sparkline series={m.r} w={84} h={22} /> };
  // paired two-line cells keep the tables to ~11 columns
  const cPriceTv: Col = { h: 'Price', tip: 'last close · average daily traded value (₹ crore, 20 sessions)', r: true,
    cell: m => <>{fmtPrice(m.l)}<span className="sub2">{m.tv == null ? '—' : `₹${m.tv.toFixed(0)} cr/day`}</span></> };
  const cRet: Col = { h: '1W · 1M', r: true, cell: m => <><Tone v={m.w1} /><span className="sub2"><Tone v={m.m1} /></span></> };
  const cOffAdr: Col = { h: 'Off high', tip: '% below the 52-week high · average daily range (size the stop with it)', r: true,
    cell: m => <>{pctOrDash(m.h)}<span className="sub2">ADR {pctOrDash(m.a)}</span></> };
  const cBase: Col = { h: '10d range', tip: '10-session high-low range as % of price (small = a tight base) · today’s volume ÷ its 50-day average', r: true,
    cell: m => <>{pctOrDash(m.tt)}<span className="sub2">vol {m.vr == null ? '—' : `${m.vr.toFixed(1)}×`}</span></> };
  const cRS: Col = { h: 'RS', tip: 'RS rating 1-99 vs all stocks', r: true, cell: m => <RsBadge v={m.rr} /> };
  const c1W: Col = { h: '1W', r: true, cell: m => <Tone v={m.w1} /> };
  const cDl: Col = { h: 'Deliv', tip: 'delivery % today (20-session average) — share of traded quantity taken into demat', r: true,
    cell: m => (m.dl == null ? '—' : <>{m.dl.toFixed(0)}%<span className="sub2">{m.dla == null ? '' : `${m.dla.toFixed(0)}% avg`}</span></>) };
  const cTags: Col = { h: 'Setup', cell: m => tags(m) };
  const daily = [cNum, cStock(), cSpark, cPriceTv, cRS, cRet, cOffAdr, cBase, cDl, cTags];

  const ipoCols: Col[] = [cNum, cStock(false),
    { h: 'Listed', tip: 'listing day · market sessions since', r: true, cell: m => <>{fmtDay(m.ipo!.d)}<span className="sub2">{m.ipo!.n} sessions</span></> },
    { h: 'Issue', tip: 'IPO issue price, adjusted for any later split / bonus', r: true, cell: m => (m.ipo!.p == null ? '—' : fmtPrice(m.ipo!.p)) },
    cPriceTv,
    { h: 'vs issue', tip: '% above the issue price', r: true, cell: m => <Tone v={m.ipo!.g} dp={0} /> },
    { h: 'vs N500', tip: 'out-/under-performance vs NIFTY 500 since the listing-day close', r: true, cell: m => <Tone v={m.ipo!.x} dp={0} /> },
    c1W, { ...cOffAdr, tip: '% below the highest intraday price since listing · average daily range' }, cBase, cTags];

  const weeklyCols: Col[] = [cNum, cStock(), cSpark, cPriceTv, cRS,
    { h: '10W SMA', tip: "10-week simple moving average of weekly closes (this week's bar closes at the latest price)", r: true, cell: m => fmtPrice(m.wk!.s) },
    { h: 'vs 10W', tip: '% the price is above the 10-week SMA — small = near the weekly support line', r: true, cell: m => <Tone v={m.wk!.d} /> },
    { h: 'Weeks above', tip: 'weekly closes in a row above the 10-week SMA (this week included)', r: true, cell: m => m.wk!.n },
    cRet, cOffAdr,
    { h: 'Setup', cell: m => tags(m, <>
      {inBrk.has(m.s) && <span className="tag outline" title="also in today's breakout watch (top 25)">Breakout watch</span>}
      {inIpo.has(m.s) && <span className="tag outline" title="also in today's IPO bases list — a listing under a year old">IPO base</span>}</>) }];

  const when = (d?: string | null) => (d ? `${fmtDay(d)} close` : '');
  const volX = (x: number | null) => (x == null ? '' : ` · ${x.toFixed(1)}× vol`);
  const htfState = (h: HtfInfo) => h.bo == null
    ? <>{(-h.dist).toFixed(1)}% below<span className="sub2">in the flag</span></>
    : <><Tone v={h.dist} /> above<span className="sub2">broke out {when(h.bod)}{volX(h.vx)}</span></>;
  const htfEarly = (h: HtfInfo) => {
    if (h.et == null || h.es == null || (h.bo != null && h.eb == null)) return <span className="muted">—</span>;
    const risk = ` (${((1 - h.es / h.et) * 100).toFixed(0)}% risk)`;
    return h.eb != null
      ? <><b>{fmtPrice(h.et)} hit</b><span className="sub2">{when(h.ebd)} · stop {fmtPrice(h.es)}{risk}</span></>
      : <>{fmtPrice(h.et)}<span className="sub2" title="a close above it is the early entry">stop {fmtPrice(h.es)}{risk}</span></>;
  };
  const htfCols: Col[] = [cNum, cStock(), cPriceTv, cRS,
    { h: 'Pole', tip: 'the run-up: low to the pole high, and how many sessions it took', r: true, cell: m => <>+{m.htf!.g.toFixed(0)}%<span className="sub2">{m.htf!.pw} sessions</span></> },
    { h: 'Flag', tip: 'deepest pullback from the pole high, and sessions since the pole high', r: true, cell: m => <>−{m.htf!.fd.toFixed(0)}%<span className="sub2">{m.htf!.fw} sessions</span></> },
    { h: 'Pivot', tip: 'the pole high — the breakout level (set your alert here)', r: true, cell: m => fmtPrice(m.htf!.p) },
    { h: 'vs pivot', tip: 'the last close vs the pivot — completed sessions only (the data updates after the 15:30 close)', r: true, cell: m => htfState(m.htf!) },
    { h: 'Early trigger', tip: 'the high of a tight 10-day range inside the flag (≤ 2.5 ADR): a close above it is the early, lower-priced entry; stop under the range low', r: true, cell: m => htfEarly(m.htf!) },
    { h: 'Flag vol', tip: 'average volume in the flag ÷ average volume in the pole — under 0.7 = drying up', r: true, cell: m => (m.htf!.dry == null ? '—' : `${m.htf!.dry.toFixed(2)}×`) },
    { h: 'Setup', cell: m => tags(m, inBrk.has(m.s) && <span className="tag outline" title="also in today's breakout watch (top 25)">Breakout watch</span>) }];

  const sections = [
    { name: 'Breakout watch', syms: D.breakouts }, { name: 'Pullbacks in leaders', syms: D.pullbacks },
    { name: 'IPO bases', syms: D.ipos ?? [] }, { name: 'Weekly trend above 10W SMA', syms: D.weekly ?? [] },
    { name: 'High tight flags', syms: D.htf ?? [] },
  ];
  const anyList = sections.some(s => s.syms.length);
  const Title = ({ n, children }: { n: number; children: ReactNode }) => <><span className="sec-num">{n}</span>{children}</>;

  return <>
    <PageHeader title="Swing setups" sub={<>What to check every evening before the next session · as of the {fmtDate(D.asof)} close.</>}
      actions={anyList && <button className="btn" data-act="all" title="One TradingView watchlist with a section per list — TradingView: watchlist menu → Import list"
        onClick={() => saveText(tvSections(sections), `swing_watchlist_${D.asof}.txt`)}><IconDownload />TradingView watchlist · all lists</button>} />
    <section className="card hero" data-testid="swing-answer">
      <div className="hero-in">
        <Gauge pass={reg.pass} total={reg.known} level={reg.level} />
        <div>
          <div className="hero-k">Market regime</div>
          <div className="hero-t">Market: <b className={`r-${reg.level}`}>{R.word}</b> — {reg.pass} of {reg.known} checks pass.</div>
          <div className="hero-s">{R.line.charAt(0).toUpperCase() + R.line.slice(1)}</div>
        </div>
        <div className="hero-side">
          {R.sizing.map(([k, v]) => <div className="hs" key={k}><span>{k}</span><b>{v}</b></div>)}
        </div>
      </div>
    </section>
    <div className="tiles" style={{ marginTop: 18 }}>
      {([['list-breakouts', 'Breakout watch', breakouts.length, 'leaders near highs', 'var(--sc-1)'],
         ['list-pullbacks', 'Pullbacks', pullbacks.length, 'lower-risk entries', 'var(--sc-3)'],
         ['list-ipos', 'IPO bases', ipos.length, 'new listings basing', 'var(--sc-4)'],
         ['list-weekly', 'Weekly trend', weekly.length, 'above a rising 10W SMA', 'var(--sc-5)'],
         ['list-htf', 'High tight flags', htfs.length, '+100% pole, tight flag', 'var(--sc-2)']] as const).map(([id, label, n, sub, c]) =>
        <a key={id} className="tile" href={`#${id}`} onClick={e => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>
          <span className="tl"><span className="tsw" style={{ background: c }} />{label}</span>
          <div className="tv">{n}</div><div className="ts">{sub}</div>
        </a>)}
    </div>
    <div className="grid two" style={{ marginTop: 16 }}>
      <Card title={<Title n={1}>Market regime checklist</Title>}>
        <ul className="checks" data-testid="regime-checks">{reg.checks.map(c => <li key={c.t}>
          <span className={`ck ${c.ok === null ? 'na' : c.ok ? 'ok' : 'no'}`}>{c.ok === null ? '–' : c.ok ? '✓' : '✗'}</span>{c.t}<span className="v">{c.v}</span>
        </li>)}</ul>
      </Card>
      <Card title={<Title n={2}>Leading industries</Title>} sub="where setups work best">
        {leadInd.length ? leadInd.map(r => <div className="row-item" key={r.name}>
          <div className="row-h"><b>{r.name}</b><span className="muted" style={{ fontSize: 12 }}>{r.sector}</span><QuadTag q={r.quad} /></div>
          <div className="row-line">{sgn(r.m1)} 1M · {pctTxt(r.p50)} above 50-EMA · {r.lead} leaders</div>
        </div>) : <Empty>No industry is beating the average stock right now.</Empty>}
      </Card>
    </div>

    <div style={{ marginTop: 16 }}>
      <Card id="list-breakouts" title={<Title n={3}>Breakout watch — leaders near their highs</Title>} count={`${breakouts.length} stocks`}
        tools={<TvButtons syms={D.breakouts} shown={25} file={`swing_breakouts_${D.asof}.txt`} testid="tv-brk" />} flush>
        <p className="note-box">RS ≥ {S.minRS}, above the 20/50/100/150/200-day EMAs, RS line above its 21-EMA, within {S.maxOffHigh}% of the 52-week high,
          ADR {S.minAdr}–{S.maxAdr}%, ≥ ₹{S.minTurnoverCr} cr/day, not up &gt; {S.maxWeek}% this week or &gt; {S.maxMonth}% this month. <span className="hot">●</span> = in a leading group (ranked first).
          Buy only on a breakout from a tight range on rising volume; stop under the range low (≈ 1 ADR). Ranked higher when the 10-day range is <b>tight</b>,
          volume is <b>drying up</b> and delivery is steadily high. <span className="ev res">⚠ Results</span> = reports within 14 days — don't hold through them.</p>
        <SetupTable list={breakouts} max={25} cols={daily} testid="tbl-breakouts" empty="No stock passes the breakout filter today — that itself says: stay patient." />
      </Card>
      <Card id="list-pullbacks" title={<Title n={4}>Pullbacks in leaders — lower-risk entries</Title>} count={`${pullbacks.length} stocks`}
        tools={<TvButtons syms={D.pullbacks} shown={15} file={`swing_pullbacks_${D.asof}.txt`} testid="tv-pb" />} flush>
        <p className="note-box">RS ≥ {S.pbMinRS}, above the 50 and 200-day EMAs but back below the 20-day, {S.pbOffHigh?.[0]}–{S.pbOffHigh?.[1]}% off the high.
          Enter when it turns back up (reclaims the prior day's high / the 20-EMA); stop under the pullback low.</p>
        <SetupTable list={pullbacks} max={15} cols={daily} testid="tbl-pullbacks" empty="No leader is pulling back in an orderly way right now." />
      </Card>
      <Card id="list-ipos" title={<Title n={5}>IPO bases — new listings near their highs</Title>} count={`${ipos.length} stocks`}
        tools={<TvButtons syms={D.ipos ?? []} shown={15} file={`swing_ipo_bases_${D.asof}.txt`} testid="tv-ipo" />} flush>
        <p className="note-box">Mainboard IPOs {IR.minAge}–{IR.maxAge} sessions old — too young for an RS rating or a 200-day EMA, so the breakout watch can't see them.
          Above the issue price, ahead of NIFTY 500 since listing, above every EMA it has, within {IR.maxOffHigh}% of the high since listing,
          ADR {IR.minAdr}–{IR.maxAdr}%, not up &gt; {IR.maxWeek}% this week. The classic entry is a breakout above the post-listing high after a few quiet weeks. Young stocks move fast — size smaller.</p>
        <SetupTable list={ipos} max={15} cols={ipoCols} testid="tbl-ipos" empty="No recent IPO is basing near its high right now." />
      </Card>
      <Card id="list-weekly" title={<Title n={6}>Weekly trend — leaders above the 10-week SMA</Title>} count={`${weekly.length} stocks`}
        tools={<TvButtons syms={D.weekly ?? []} shown={25} file={`swing_weekly_10w_${D.asof}.txt`} testid="tv-wk" />} flush>
        <p className="note-box">Weekly close above a rising {WR.sma}-week SMA (TradingView's weekly bar), RS ≥ {WR.minRS}, ADR {WR.minAdr}–{WR.maxAdr}%,
          not up &gt; {WR.maxWeek}% this week or &gt; {WR.maxMonth}% this month; strongest RS first. Hold while the weekly close stays above the 10-week line.
          <span className="tag info" style={{ marginLeft: 6 }}>Near 10W</span> = within {WR.near}% of the line — the lower-risk entry.</p>
        <SetupTable list={weekly} max={25} cols={weeklyCols} testid="tbl-weekly" empty="No leader is in a rising weekly trend that isn't already extended right now." />
      </Card>
      <Card id="list-htf" title={<Title n={7}>High tight flags — a +{HR.minPole}% pole, then a tight flag</Title>} count={`${htfs.length} stocks`}
        tools={<TvButtons syms={D.htf ?? []} shown={15} file={`swing_high_tight_flags_${D.asof}.txt`} testid="tv-htf" />} flush>
        <p className="note-box">Up ≥ {HR.minPole}% in ≤ {HR.poleWeeks} weeks (the pole), then a pullback of ≤ {HR.maxFlag}% lasting {HR.flagWeeks[0]}–{HR.flagWeeks[1]} weeks (the flag);
          buy the first close above the pivot (the pole high). <span className="tag pos">Flag vol dry-up</span> ranks first — in the NSE test those beat NIFTY 500 by +6.8% over 20 sessions.
          <b> Early trigger</b> — a close above a tight 10-day range inside the flag gets you in a median 8% below the pivot (41% reached 2× risk before the stop);
          its stop is the range low, often 10–13% away — take a smaller position. <b>India check:</b> stocks up 100% in weeks often land in NSE's ASM list — look it up before buying.</p>
        <SetupTable list={htfs} max={15} cols={htfCols} testid="tbl-htf" empty="No liquid stock is in a high tight flag right now — they are rare (a few a month, mostly in strong markets)." />
      </Card>
      {extended.length > 0 && <Card title="Don't chase — extended leaders" sub={`Up > 20% in a week or > ${S.maxMonth}% in a month: wait for a base or a pullback.`}>
        {extended.map(m => <span key={m.s} className="nowrap" style={{ marginRight: 10 }}><StockLink sym={m.s} name={m.n} /><span className="muted" style={{ fontSize: 12 }}>{sgn(m.w1, 0)} 1W</span></span>)}
      </Card>}
      <Card title="Track record — does the screen work?"><SwingTrack t={track} /></Card>
      <Card title="Rules I'd trade by">
        <ul className="bullets" style={{ marginTop: 0 }}>
          <li><b>Regime first:</b> size follows the checklist above — cut size when it turns Mixed, mostly cash when Risk-off.</li>
          <li><b>Risk per trade:</b> decide the stop before entry; lose at most 0.5–1% of capital if it hits. Shares = risk ₹ ÷ (entry − stop).</li>
          <li><b>Stop:</b> below the setup's low, usually ≤ 1× ADR from entry; never widen it.</li>
          <li><b>Profits:</b> sell a third to half at 2–3× risk or after 3–5 strong days; move the stop to breakeven; trail the rest with the 10/20-day EMA.</li>
          <li><b>Leaders only:</b> RS ≥ 80 stocks in leading groups; skip stocks reporting results within the holding period.</li>
          <li><b>Review:</b> if 3–4 breakouts in a row fail, the market is telling you to step back.</li>
        </ul>
      </Card>
    </div>
    <p className="foot">Screens use the latest completed session; levels are a starting point for your own chart review, not investment advice. Click a stock for its RS chart.</p>
  </>;
}
