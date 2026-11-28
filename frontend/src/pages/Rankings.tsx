import { Fragment, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useLevel, useLevels, useMeta } from '../api/client';
import type { Group, Level, Member } from '../api/types';
import { fmtPrice } from '../lib/format';
import { isFiltering, memberPasses, NO_FILTERS, type Filters } from '../lib/market';
import { copyText, saveText, tvSym } from '../lib/tv';
import { useApp } from '../components/AppContext';
import { Sparkline } from '../components/charts';
import { IconCopy, IconDownload } from '../components/Icons';
import { ErrorBox, Loading, PageHeader, Segmented, rsPillStyle } from '../components/ui';

const EMAS = [20, 50, 100, 150, 200];

function NumChip({ label, on, value, onToggle, onValue, testid }: {
  label: [string, string]; on: boolean; value: number; onToggle: (v: boolean) => void; onValue: (v: number) => void; testid: string;
}) {
  return (
    <label className={`chip ${on ? 'on' : ''}`} data-testid={testid}>
      <input type="checkbox" checked={on} onChange={e => onToggle(e.target.checked)} />{label[0]}
      <input type="number" value={value} min={0} step={1} onChange={e => { onValue(parseFloat(e.target.value) || 0); onToggle(true); }} />{label[1]}
    </label>
  );
}

function MemberRows({ g, members, selected, setSel }: {
  g: Group; members: Member[]; selected: Set<string>; setSel: (syms: string[], on: boolean) => void;
}) {
  const { openStock, watch, toggleWatch, theme } = useApp();
  return (
    <tr className="sub-row"><td colSpan={4} style={{ padding: 0 }}>
      <div className="tbl-wrap">
        <table className="tbl sub-tbl" data-testid={`members-${g.id}`}>
          <thead><tr>
            <th style={{ width: 28 }} /><th>Stock</th><th>RS (26d)</th><th className="r">RS%</th><th className="r">LTP</th>
            <th className="r">Off high</th><th className="r">ADR</th>
            <th className="c" title="RS line (stock / NIFTY 500) vs its 21-day EMA">RS21</th>
            {EMAS.map(p => <th key={p} className="c" title={`price vs its ${p}-day EMA`}>{p}</th>)}
          </tr></thead>
          <tbody>{members.map(m => (
            <tr key={m.s} className="clickable" data-sym={m.s} onClick={() => openStock(m.s)}>
              <td onClick={e => e.stopPropagation()}>
                <input type="checkbox" className="pick" checked={selected.has(m.s)} onChange={e => setSel([m.s], e.target.checked)} aria-label={`select ${m.s}`} />
              </td>
              <td>
                <span className="nowrap">
                  <button className={`star ${watch.has(m.s) ? 'on' : ''}`} title="watchlist" data-testid="star"
                    onClick={e => { e.stopPropagation(); toggleWatch(m.s); }}>{watch.has(m.s) ? '★' : '☆'}</button>
                  <span className="stk-name">{m.n}</span>
                  {m.nw ? <span className="tag info" style={{ marginLeft: 6 }} title={`New listing — RS% over its ${m.nw} trading days since listing; joins the group index after a full window`}>NEW · {m.nw}d</span> : null}
                  {m.d != null && <span className={`delta ${m.d >= 0 ? 'up' : 'dn'}`}>{m.d >= 0 ? '+' : ''}{m.d.toFixed(0)}</span>}
                </span>
                <span className="stk-sym" style={{ marginLeft: 21 }}>{m.s}</span>
              </td>
              <td><Sparkline series={m.r} w={110} h={20} /></td>
              <td className="r"><span className="rs-pill" style={rsPillStyle(m.p, theme === 'dark')} title={m.nw ? `since listing (${m.nw} days)` : undefined}>{Math.round(m.p * 100)}%</span></td>
              <td className="r tnum">{fmtPrice(m.l)}</td>
              <td className="r tnum">{m.h == null ? '—' : `−${m.h.toFixed(1)}%`}</td>
              <td className="r tnum">{m.a == null ? '—' : `${m.a.toFixed(1)}%`}</td>
              <td className="c">{m.b === 1 ? <span className="tag pos">above</span> : m.b === 0 ? <span className="tag neg">below</span> : <span className="muted">—</span>}</td>
              {m.e.map((e, i) => <td key={i} className="ema-cell"><i className={e === 1 ? 'up' : e === 0 ? 'dn' : ''} title={e === 1 ? 'above' : e === 0 ? 'below' : 'n/a'} /></td>)}
            </tr>))}</tbody>
        </table>
      </div>
    </td></tr>
  );
}

function exportCsv(level: Level, groups: { g: Group; members: Member[] }[], gen: string) {
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

export function Rankings() {
  const { level = 'macro' } = useParams();
  const nav = useNavigate();
  const levels = useLevels().data;
  const meta = useMeta().data;
  const lq = useLevel(level);
  const { watch, toast, theme } = useApp();
  const loc = useLocation();
  const [f, setF] = useState<Filters>(() => ({ ...NO_FILTERS, q: (loc.state as { q?: string } | null)?.q ?? '' }));
  const [hiV, setHiV] = useState(20), [adrV, setAdrV] = useState(3), [rsV, setRsV] = useState(80);
  const [sort, setSort] = useState<{ key: 'pct' | 'name'; asc: boolean }>({ key: 'pct', asc: false });
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const filtering = isFiltering(f);
  const view = useMemo(() => {
    const data = lq.data;
    if (!data) return [];
    const q = f.q.trim().toLowerCase();
    const gs = [...data.groups].sort((a, b) => sort.key === 'pct'
      ? (sort.asc ? a.pct - b.pct : b.pct - a.pct)
      : (sort.asc ? b.name.localeCompare(a.name) : a.name.localeCompare(b.name)));
    return gs.map(g => {
      const gm = !!q && g.name.toLowerCase().includes(q);
      const members = filtering ? g.members.filter(m => memberPasses(m, f, gm, watch)) : g.members;
      return { g, members };
    }).filter(x => !filtering || x.members.length);
  }, [lq.data, f, sort, filtering, watch]);

  const ipoHits = useMemo(() => {
    const t = f.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!t.length || !meta) return [];
    return meta.ipo.filter(i => t.every(w => (i.n + ' ' + i.s).toLowerCase().includes(w)));
  }, [f.q, meta]);

  const setSel = (syms: string[], on: boolean) => setSelected(prev => {
    const n = new Set(prev);
    syms.forEach(s => (on ? n.add(s) : n.delete(s)));
    return n;
  });
  const toggleEma = (i: number) => setF(x => ({ ...x, ema: x.ema.includes(i) ? x.ema.filter(e => e !== i) : [...x.ema, i] }));
  const shownStocks = view.reduce((a, x) => a + (filtering ? x.members.length : x.g.n), 0);
  const sortBy = (key: 'pct' | 'name') => setSort(s => (s.key === key ? { key, asc: !s.asc } : { key, asc: key === 'name' }));
  const arrow = (key: string) => sort.key === key ? <span className="arrow">{sort.asc ? '▲' : '▼'}</span> : null;

  return <>
    <PageHeader title="Relative strength rankings"
      sub={<>Equal-weight group indexes vs NIFTY 500 over a {meta?.window ?? 26}-session window{meta ? ` · ${meta.drange}` : ''} — expand a group for its stocks.</>}
      actions={<Segmented label="Classification level" testid="level-tabs" value={level}
        options={(levels ?? []).map(l => ({ value: l.key, label: `${l.label} · ${l.n_groups}` }))}
        onChange={k => { setOpen(new Set()); nav(`/rankings/${k}`); }} />} />
    <section className="card">
      <div className="toolbar">
        <input className="input grow" placeholder="Filter groups or stocks…" value={f.q} data-testid="rank-search"
          onChange={e => setF(x => ({ ...x, q: e.target.value }))} onKeyDown={e => { if (e.key === 'Escape') setF(x => ({ ...x, q: '' })); }} />
        <span className="muted" style={{ fontSize: 12 }}>Above EMA</span>
        <span className="ema-set" data-testid="ema-filters">{EMAS.map((p, i) =>
          <button key={p} type="button" className={f.ema.includes(i) ? 'on' : ''} onClick={() => toggleEma(i)}>{p}</button>)}</span>
        <span className="toolbar-sep" />
        <NumChip testid="f-hi" label={['≤', '% off high']} on={f.hi != null} value={hiV} onValue={setHiV} onToggle={on => setF(x => ({ ...x, hi: on ? hiV : null }))} />
        <NumChip testid="f-adr" label={['ADR ≥', '%']} on={f.adr != null} value={adrV} onValue={setAdrV} onToggle={on => setF(x => ({ ...x, adr: on ? adrV : null }))} />
        <NumChip testid="f-rs" label={['RS% ≥', '']} on={f.rs != null} value={rsV} onValue={setRsV} onToggle={on => setF(x => ({ ...x, rs: on ? rsV : null }))} />
        <label className={`chip ${f.rse ? 'on' : ''}`} data-testid="f-rse"><input type="checkbox" checked={f.rse} onChange={e => setF(x => ({ ...x, rse: e.target.checked }))} />RS line &gt; EMA21</label>
        <button type="button" className={`chip ${f.watchOnly ? 'on' : ''}`} data-testid="f-watch" onClick={() => setF(x => ({ ...x, watchOnly: !x.watchOnly }))}>★ Watchlist</button>
        {filtering && <button className="btn sm ghost" onClick={() => setF(NO_FILTERS)}>Clear</button>}
      </div>
      <div className="selbar">
        <span data-testid="sel-count"><b>{selected.size}</b> selected</span>
        <button className="btn sm" onClick={() => setSel(view.flatMap(x => x.members.map(m => m.s)), true)}>Select visible</button>
        <button className="btn sm" disabled={!selected.size} onClick={() => setSelected(new Set())}>Clear</button>
        <button className="btn sm" disabled={!selected.size} data-testid="copy-tv" onClick={async () =>
          toast((await copyText([...selected].map(tvSym).join(',\n'))) ? `Copied ${selected.size}` : 'Copy failed')}><IconCopy />Copy for TradingView</button>
        <button className="btn sm" disabled={!selected.size} onClick={() => saveText([...selected].map(tvSym).join(',\n'), 'tradingview_watchlist.txt')}><IconDownload />.txt</button>
        <span style={{ flex: 1 }} />
        {filtering && <span className="muted" data-testid="filter-info">{view.length} group(s), {shownStocks} stock(s)</span>}
        {ipoHits.length > 0 && <Link className="btn sm" to="/listings" state={{ q: f.q }}>{ipoHits.length === 1 ? `${ipoHits[0].s} in New listings →` : `${ipoHits.length} in New listings →`}</Link>}
        <button className="btn sm" disabled={!lq.data} data-testid="csv" onClick={() => lq.data && exportCsv(lq.data, view, meta?.generated ?? '')}><IconDownload />CSV</button>
      </div>
      {lq.error ? <ErrorBox error={lq.error} /> : !lq.data ? <Loading /> : (
        <div className="tbl-wrap">
          <table className="tbl" data-testid="level-table">
            <thead><tr>
              <th className="sortable" onClick={() => sortBy('name')}>{lq.data.label}{arrow('name')}</th>
              <th className="hide-sm">Relative strength (26d)</th>
              <th className="r sortable" onClick={() => sortBy('pct')} title="the group's RS percentile over the window (RS_STS%)">RS%{arrow('pct')}</th>
              <th className="r hide-sm" title="change vs the previous snapshot">Δ</th>
            </tr></thead>
            <tbody>{view.map(({ g, members }) => {
              const isOpen = open.has(g.id);
              const syms = members.map(m => m.s);
              const allSel = syms.length > 0 && syms.every(s => selected.has(s));
              const nNew = g.members.length - g.n;
              return <Fragment key={g.id}>
                <tr className="grp-row" data-gid={g.id} onClick={() => setOpen(o => { const n = new Set(o); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n; })}>
                  <td>
                    <span className="grp-name">
                      <input type="checkbox" className="pick" checked={allSel} title="select the group's stocks" onClick={e => e.stopPropagation()} onChange={e => setSel(syms, e.target.checked)} />
                      <span className={`caret ${isOpen ? 'open' : ''}`}>▶</span>{g.name}
                      <span className="cnt">{filtering ? members.length : g.n}</span>
                      {!filtering && nNew > 0 && <span className="tag info" title="new listings shown in the group, not yet in its RS index">+{nNew} new</span>}
                    </span>
                  </td>
                  <td className="hide-sm"><Sparkline series={g.r} w={150} h={26} /></td>
                  <td className="r"><span className="rsbar"><span className="rsbar-t hide-sm"><span style={{ width: `${Math.max(3, g.pct * 100)}%`, background: g.pct >= 0.5 ? 'linear-gradient(90deg, var(--pos-2), var(--pos))' : 'linear-gradient(90deg, var(--surface-3), var(--text-3))' }} /></span>
                    <span className="rs-pill" style={rsPillStyle(g.pct, theme === 'dark')}>{Math.round(g.pct * 100)}%</span></span></td>
                  <td className="r hide-sm">{g.dp != null ? <span className={`delta ${g.dp >= 0 ? 'up' : 'dn'}`}>{g.dp >= 0 ? '+' : ''}{g.dp.toFixed(0)}</span> : <span className="muted">—</span>}</td>
                </tr>
                {isOpen && <MemberRows g={g} members={members} selected={selected} setSel={setSel} />}
              </Fragment>;
            })}</tbody>
          </table>
          {!view.length && <div className="empty">No stocks match these filters.</div>}
        </div>
      )}
    </section>
    <p className="foot">RS_STS% = the percentile of today's relative-strength value (group or stock ÷ NIFTY 500) within its own last {meta?.window ?? 26} sessions; Δ = change since the previous build. Click a group to expand it, a stock for its RS chart; ☆ adds it to your watchlist.</p>
  </>;
}
