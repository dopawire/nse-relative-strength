// Relative-strength rankings: a master–detail screen.  Left: the groups of a
// classification level ranked by RS%; right: the selected group — its stats,
// its RS line over the window and its stocks.  Filters apply to the stocks;
// the group list shows how many of each group's stocks pass them.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useLevel, useLevels, useMeta } from '../api/client';
import type { Group, Level, Member } from '../api/types';
import { fmtPrice, median } from '../lib/format';
import { isFiltering, memberPasses, NO_FILTERS, type Filters } from '../lib/market';
import { copyText, saveText, tvSym } from '../lib/tv';
import { useApp } from '../components/AppContext';
import { LineChart, Sparkline } from '../components/charts';
import { IconCopy, IconDownload, IconSearch, IconX } from '../components/Icons';
import { ErrorBox, Loading, RsBadge, Tone } from '../components/ui';

const EMAS = [20, 50, 100, 150, 200];
type GroupSort = 'pct' | 'dp' | 'name';
type MemberSort = 'p' | 'd' | 'rr' | 'l' | 'm1' | 'h' | 'a';

interface GroupView {
  g: Group; members: Member[]; above50: number | null; m1: number | null; leaders: number; rank: number;
}

/** RS% (0..1) → a bar + the number */
function RsMeter({ v, w = 64 }: { v: number; w?: number }) {
  const pct = Math.round(v * 100);
  return (
    <span className="meter" title={`RS% ${pct}`}>
      <span className="meter-t" style={{ width: w }}><span style={{ width: `${Math.max(2, pct)}%` }} className={pct >= 60 ? 'hi' : pct >= 30 ? 'mid' : 'lo'} /></span>
      <span className="meter-v">{pct}</span>
    </span>
  );
}

const Delta = ({ v }: { v: number | null | undefined }) => v == null || v === 0
  ? <span className="muted">–</span>
  : <span className={`chg ${v > 0 ? 'up' : 'dn'}`}>{v > 0 ? '▲' : '▼'} {Math.abs(v).toFixed(0)}</span>;

function NumFilter({ label, unit, on, value, onChange, testid }: {
  label: string; unit: string; on: boolean; value: number; onChange: (on: boolean, v: number) => void; testid: string;
}) {
  return (
    <label className={`fchip ${on ? 'on' : ''}`} data-testid={testid}>
      <input type="checkbox" checked={on} onChange={e => onChange(e.target.checked, value)} />
      <span>{label}</span>
      <input type="number" value={value} min={0} step={1} aria-label={`${label} value`}
        onChange={e => onChange(true, parseFloat(e.target.value) || 0)} />
      {unit && <span className="muted">{unit}</span>}
    </label>
  );
}

function exportCsv(level: Level, groups: GroupView[], gen: string) {
  const head = ['level', 'group', 'group_n', 'group_rs_pct', 'group_delta', 'symbol', 'name', 'rs_pct', 'delta', 'ltp',
    'ema20', 'ema50', 'ema100', 'ema150', 'ema200', 'off_high_pct', 'adr_pct', 'rs_ema21', 'new_listing_days'];
  const esc = (s: unknown) => `"${String(s ?? '').replace(/"/g, '""')}"`;
  const lines = [head.join(',')];
  for (const { g, members } of groups) {
    for (const m of members) {
      lines.push([level.key, g.name, g.n, (g.pct * 100).toFixed(1), g.dp != null ? g.dp.toFixed(1) : '', m.s, m.n,
        (m.p * 100).toFixed(1), m.d != null ? m.d.toFixed(1) : '', m.l, ...m.e, m.h, m.a,
        m.b === 1 ? 'above' : m.b === 0 ? 'below' : '', m.nw].map(esc).join(','));
    }
  }
  saveText(lines.join('\n'), `nse_rs_${level.key}_${gen.split(' ')[0] || 'export'}.csv`, 'text/csv');
}

const LEVEL_NOUN: Record<string, string> = { macro: 'Macro sector', sector: 'Sector', industry: 'Industry', basic: 'Sub-industry' };
const LEVEL_PLURAL: Record<string, string> = { macro: 'macro sectors', sector: 'sectors', industry: 'industries', basic: 'sub-industries' };

export function Rankings() {
  const { level = 'macro' } = useParams();
  const nav = useNavigate();
  const loc = useLocation();
  const levels = useLevels().data;
  const meta = useMeta().data;
  const lq = useLevel(level);
  const { watch, toggleWatch, openStock, toast } = useApp();
  const [f, setF] = useState<Filters>(() => ({ ...NO_FILTERS, q: (loc.state as { q?: string } | null)?.q ?? '' }));
  const [num, setNum] = useState({ hi: 20, adr: 3, rs: 80 });
  const [gsort, setGsort] = useState<{ k: GroupSort; asc: boolean }>({ k: 'pct', asc: false });
  const [msort, setMsort] = useState<{ k: MemberSort; asc: boolean }>({ k: 'p', asc: false });
  const [sel, setSel] = useState<number | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const detail = useRef<HTMLDivElement>(null);
  const filtering = isFiltering(f);

  // groups with their filtered members and summary stats, in the chosen order
  const groups = useMemo<GroupView[]>(() => {
    const data = lq.data;
    if (!data) return [];
    const q = f.q.trim().toLowerCase();
    const rankOf = new Map([...data.groups].sort((a, b) => b.pct - a.pct).map((g, i) => [g.id, i + 1]));
    const out = data.groups.map(g => {
      const gm = !!q && g.name.toLowerCase().includes(q);
      const members = filtering ? g.members.filter(m => memberPasses(m, f, gm, watch)) : g.members;
      const known = g.members.filter(m => m.e[1] !== -1);
      return {
        g, members, rank: rankOf.get(g.id) ?? 0,
        above50: known.length ? known.filter(m => m.e[1] === 1).length / known.length : null,
        m1: median(g.members.map(m => m.m1)),
        leaders: g.members.filter(m => (m.rr ?? 0) >= 80).length,
      };
    }).filter(x => !filtering || x.members.length);
    const dir = gsort.asc ? 1 : -1;
    return out.sort((a, b) => gsort.k === 'name' ? dir * a.g.name.localeCompare(b.g.name)
      : gsort.k === 'dp' ? dir * ((a.g.dp ?? -999) - (b.g.dp ?? -999)) : dir * (a.g.pct - b.g.pct));
  }, [lq.data, f, gsort, filtering, watch]);

  useEffect(() => { setSel(null); }, [level]);
  // keep a valid selection: the first group when none / when it left the list
  useEffect(() => {
    if (!groups.length) { if (sel != null) setSel(null); return; }
    if (sel == null || !groups.some(x => x.g.id === sel)) setSel(groups[0].g.id);
  }, [groups, sel]);

  const cur = groups.find(x => x.g.id === sel) ?? null;
  const members = useMemo(() => {
    if (!cur) return [];
    const k = msort.k, dir = msort.asc ? 1 : -1;
    const v = (m: Member) => (m[k] as number | null | undefined) ?? null;
    return [...cur.members].sort((a, b) => {
      const va = v(a), vb = v(b);
      if (va == null) return 1;
      if (vb == null) return -1;
      return dir * (va - vb);
    });
  }, [cur, msort]);

  const ipoHits = useMemo(() => {
    const t = f.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return !t.length || !meta ? [] : meta.ipo.filter(i => t.every(w => (i.n + ' ' + i.s).toLowerCase().includes(w)));
  }, [f.q, meta]);

  const togglePick = (syms: string[], on: boolean) => setPicked(prev => {
    const n = new Set(prev);
    syms.forEach(s => (on ? n.add(s) : n.delete(s)));
    return n;
  });
  const choose = (id: number) => {
    setSel(id);
    if (window.matchMedia('(max-width: 1100px)').matches) detail.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const i = groups.findIndex(x => x.g.id === sel);
    const j = Math.max(0, Math.min(groups.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)));
    setSel(groups[j].g.id);
    document.querySelector(`[data-gid="${groups[j].g.id}"]`)?.scrollIntoView({ block: 'nearest' });
  };
  const gHead = (k: GroupSort, label: string, cls = '') => (
    <th className={`sortable ${cls} ${gsort.k === k ? 'sorted' : ''}`} onClick={() => setGsort(s => ({ k, asc: s.k === k ? !s.asc : k === 'name' }))}>
      {label}{gsort.k === k && <span className="arrow">{gsort.asc ? '↑' : '↓'}</span>}
    </th>
  );
  const mHead = (k: MemberSort, label: string, tip?: string) => (
    <th className={`sortable r ${msort.k === k ? 'sorted' : ''}`} title={tip} onClick={() => setMsort(s => ({ k, asc: s.k === k ? !s.asc : false }))}>
      {label}{msort.k === k && <span className="arrow">{msort.asc ? '↑' : '↓'}</span>}
    </th>
  );
  const noun = LEVEL_NOUN[level] ?? 'Group';
  const shownStocks = groups.reduce((a, x) => a + x.members.length, 0);
  const winDates = meta?.window_dates ?? [];

  return <>
    <div className="page-head">
      <div>
        <h2 className="ph-t">Relative strength</h2>
        <div className="ph-s">Equal-weight group indexes vs NIFTY 500, last {meta?.window ?? 26} sessions{meta ? ` · ${meta.drange.replace('→', '–')}` : ''}</div>
      </div>
      <nav className="subnav" data-testid="level-tabs" aria-label="Classification level">
        {(levels ?? []).map(l => <button key={l.key} type="button" className={l.key === level ? 'on' : ''}
          onClick={() => nav(`/rankings/${l.key}`)}>{LEVEL_NOUN[l.key] ?? l.label}<span>{l.n_groups}</span></button>)}
      </nav>
    </div>

    <div className="filterbar">
      <div className="fsearch">
        <IconSearch />
        <input placeholder={`Filter ${LEVEL_PLURAL[level] ?? 'groups'} or stocks`} value={f.q} data-testid="rank-search"
          onChange={e => setF(x => ({ ...x, q: e.target.value }))} onKeyDown={e => { if (e.key === 'Escape') setF(x => ({ ...x, q: '' })); }} />
        {f.q && <button type="button" className="fclear" aria-label="Clear search" onClick={() => setF(x => ({ ...x, q: '' }))}><IconX /></button>}
      </div>
      <div className="fgroup" data-testid="ema-filters" role="group" aria-label="Price above these EMAs">
        <span className="flabel">Above EMA</span>
        {EMAS.map((p, i) => <button key={p} type="button" aria-pressed={f.ema.includes(i)} className={f.ema.includes(i) ? 'on' : ''}
          onClick={() => setF(x => ({ ...x, ema: x.ema.includes(i) ? x.ema.filter(e => e !== i) : [...x.ema, i] }))}>{p}</button>)}
      </div>
      <NumFilter testid="f-hi" label="Off high ≤" unit="%" on={f.hi != null} value={num.hi}
        onChange={(on, v) => { setNum(n => ({ ...n, hi: v })); setF(x => ({ ...x, hi: on ? v : null })); }} />
      <NumFilter testid="f-adr" label="ADR ≥" unit="%" on={f.adr != null} value={num.adr}
        onChange={(on, v) => { setNum(n => ({ ...n, adr: v })); setF(x => ({ ...x, adr: on ? v : null })); }} />
      <NumFilter testid="f-rs" label="RS% ≥" unit="" on={f.rs != null} value={num.rs}
        onChange={(on, v) => { setNum(n => ({ ...n, rs: v })); setF(x => ({ ...x, rs: on ? v : null })); }} />
      <label className={`fchip ${f.rse ? 'on' : ''}`} data-testid="f-rse"><input type="checkbox" checked={f.rse} onChange={e => setF(x => ({ ...x, rse: e.target.checked }))} />RS line above EMA21</label>
      <label className={`fchip ${f.watchOnly ? 'on' : ''}`} data-testid="f-watch"><input type="checkbox" checked={f.watchOnly} onChange={e => setF(x => ({ ...x, watchOnly: e.target.checked }))} />Watchlist</label>
      <div className="fend">
        {filtering && <span className="fcount" data-testid="filter-info">{shownStocks.toLocaleString('en-IN')} stocks in {groups.length} group(s)</span>}
        {filtering && <button type="button" className="btn sm ghost" onClick={() => setF(NO_FILTERS)}>Reset</button>}
        {ipoHits.length > 0 && <Link className="btn sm" to="/listings" state={{ q: f.q }}>{ipoHits.length === 1 ? `${ipoHits[0].s} is a new listing →` : `${ipoHits.length} new listings →`}</Link>}
        <button type="button" className="btn sm" disabled={!lq.data} data-testid="csv" onClick={() => lq.data && exportCsv(lq.data, groups, meta?.generated ?? '')}><IconDownload />CSV</button>
      </div>
    </div>

    {lq.error ? <ErrorBox error={lq.error} /> : !lq.data ? <Loading /> : (
      <div className="md">
        <section className="md-list panel" aria-label={LEVEL_PLURAL[level] ?? 'groups'}>
          <div className="tbl-wrap md-scroll">
            <table className="tbl dense" data-testid="level-table" tabIndex={0} onKeyDown={onListKey}>
              <thead><tr>
                <th className="num">#</th>{gHead('name', noun)}{gHead('pct', 'RS%', 'r')}{gHead('dp', 'Δ', 'r')}
              </tr></thead>
              <tbody>{groups.map(x => (
                <tr key={x.g.id} data-gid={x.g.id} className={`grp-row ${x.g.id === sel ? 'sel' : ''}`} onClick={() => choose(x.g.id)}>
                  <td className="num muted">{x.rank}</td>
                  <td>
                    <div className="gname">{x.g.name}</div>
                    <div className="gsub">{filtering ? <><b>{x.members.length}</b> of {x.g.n} match</> : <>{x.g.n} stocks{x.g.members.length > x.g.n ? ` · ${x.g.members.length - x.g.n} new` : ''}</>}</div>
                  </td>
                  <td className="r"><RsMeter v={x.g.pct} /></td>
                  <td className="r"><Delta v={x.g.dp} /></td>
                </tr>))}</tbody>
            </table>
            {!groups.length && <div className="empty">No stocks match these filters.</div>}
          </div>
        </section>

        <section className="md-detail" ref={detail} aria-live="polite">
          {cur && <>
            <div className="panel detail-head">
              <div className="dh-top">
                <div>
                  <div className="eyebrow">{noun} · #{cur.rank} of {lq.data.groups.length}</div>
                  <h3 className="dh-t">{cur.g.name}</h3>
                </div>
                <div className="dh-rs"><span className="big">{Math.round(cur.g.pct * 100)}</span><span className="muted">RS%</span><Delta v={cur.g.dp} /></div>
              </div>
              <dl className="stats">
                <div><dt>Stocks</dt><dd>{cur.g.n}{cur.g.members.length > cur.g.n && <small> +{cur.g.members.length - cur.g.n} new</small>}</dd></div>
                <div><dt>Above 50-day EMA</dt><dd>{cur.above50 == null ? '—' : `${Math.round(cur.above50 * 100)}%`}</dd></div>
                <div><dt>Median 1M</dt><dd><Tone v={cur.m1} /></dd></div>
                <div><dt>RS ≥ 80</dt><dd>{cur.leaders}</dd></div>
              </dl>
              {winDates.length === cur.g.r.length && <div className="dh-chart">
                <LineChart dates={winDates} height={110} fmt={v => v.toFixed(3)}
                  series={[{ values: cur.g.r, color: 'var(--accent)', label: 'vs NIFTY 500', width: 1.5 }]} />
              </div>}
            </div>

            <div className="panel">
              <div className="panel-h">
                <span className="panel-t">Stocks <span className="muted">{members.length}{filtering ? ` of ${cur.g.members.length}` : ''}</span></span>
                <button type="button" className="btn sm ghost" onClick={() => togglePick(members.map(m => m.s), true)}>Select visible</button>
              </div>
              <div className="tbl-wrap">
                <table className="tbl dense" data-testid={`members-${cur.g.id}`}>
                  <thead><tr>
                    <th className="cb"><input type="checkbox" className="pick" aria-label="select all shown"
                      checked={members.length > 0 && members.every(m => picked.has(m.s))} onChange={e => togglePick(members.map(m => m.s), e.target.checked)} /></th>
                    <th>Stock</th>
                    {mHead('p', 'RS%', 'percentile of today’s RS value within the window')}{mHead('d', 'Δ', 'change since the previous build')}
                    {mHead('rr', 'Rating', 'RS rating 1-99 vs all stocks (12-month weighted)')}{mHead('l', 'Price')}{mHead('m1', '1M')}
                    {mHead('h', 'Off high', '% below the 52-week high')}{mHead('a', 'ADR', 'average daily range, 20 sessions')}
                    <th className="c" title="RS line (stock ÷ NIFTY 500) vs its 21-day EMA">RS21</th>
                    <th className="c" title="price above (filled) / below (hollow) its 20 / 50 / 100 / 150 / 200-day EMA">EMAs</th>
                    <th className="hide-md">26d</th>
                  </tr></thead>
                  <tbody>{members.map(m => (
                    <tr key={m.s} className="clickable" data-sym={m.s} onClick={() => openStock(m.s)}>
                      <td className="cb" onClick={e => e.stopPropagation()}>
                        <input type="checkbox" className="pick" checked={picked.has(m.s)} onChange={e => togglePick([m.s], e.target.checked)} aria-label={`select ${m.s}`} />
                      </td>
                      <td>
                        <div className="tick">
                          <button type="button" className={`star ${watch.has(m.s) ? 'on' : ''}`} data-testid="star" aria-label="watchlist"
                            onClick={e => { e.stopPropagation(); toggleWatch(m.s); }}>{watch.has(m.s) ? '★' : '☆'}</button>
                          <span className="tick-s">{m.s}</span>
                          {m.nw ? <span className="badge" title={`New listing — RS over its ${m.nw} sessions since listing`}>new · {m.nw}d</span> : null}
                        </div>
                        <div className="tick-n">{m.n}</div>
                      </td>
                      <td className="r"><RsMeter v={m.p} w={32} /></td>
                      <td className="r"><Delta v={m.d} /></td>
                      <td className="r"><RsBadge v={m.rr} /></td>
                      <td className="r">{fmtPrice(m.l)}</td>
                      <td className="r"><Tone v={m.m1} /></td>
                      <td className="r">{m.h == null ? '—' : `${m.h.toFixed(1)}%`}</td>
                      <td className="r">{m.a == null ? '—' : `${m.a.toFixed(1)}%`}</td>
                      <td className="c">{m.b === 1 ? <span className="chg up" title="above its EMA21">▲</span> : m.b === 0 ? <span className="chg dn" title="below its EMA21">▼</span> : <span className="muted">–</span>}</td>
                      <td className="c"><span className="emas">{m.e.map((e, i) => <i key={i} className={e === 1 ? 'up' : e === 0 ? 'dn' : ''} title={`${EMAS[i]}-day EMA: ${e === 1 ? 'above' : e === 0 ? 'below' : 'n/a'}`} />)}</span></td>
                      <td className="hide-md"><Sparkline series={m.r} w={64} h={18} /></td>
                    </tr>))}</tbody>
                </table>
                {!members.length && <div className="empty">No stocks in this group match the filters.</div>}
              </div>
            </div>
          </>}
        </section>
      </div>
    )}

    {picked.size > 0 && <div className="actionbar" role="region" aria-label="Selection">
      <span data-testid="sel-count"><b>{picked.size}</b> selected</span>
      <button type="button" className="btn sm" data-testid="copy-tv" onClick={async () =>
        toast((await copyText([...picked].map(tvSym).join(',\n'))) ? `Copied ${picked.size} for TradingView` : 'Copy failed')}><IconCopy />Copy for TradingView</button>
      <button type="button" className="btn sm" onClick={() => saveText([...picked].map(tvSym).join(',\n'), 'tradingview_watchlist.txt')}><IconDownload />.txt</button>
      <button type="button" className="btn sm ghost" onClick={() => setPicked(new Set())}>Clear</button>
    </div>}
    <p className="foot">RS% ranks today's relative-strength value (group or stock ÷ NIFTY 500) within its own last {meta?.window ?? 26} sessions; Δ is the change since the previous build. ↑ ↓ moves through the list; click a stock for its chart.</p>
  </>;
}
