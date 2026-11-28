import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { logout, pipelineStatus, startRefreshStocks, startUpdate, useAllLevels, useDecide, useMeta } from '../api/client';
import { fmtDate } from '../lib/format';
import { stockIndex } from '../lib/market';
import { useApp } from './AppContext';
import {
  IconBolt, IconFlow, IconHome, IconLayers, IconLogout, IconMenu, IconMoon, IconPulse, IconRefresh, IconRotate,
  IconScan, IconSearch, IconSpark, IconSun, IconTarget, Logo,
} from './Icons';
import { StockModal } from './StockModal';

const NAV = [
  { sec: null, items: [{ to: '/', label: 'Overview', icon: IconHome, end: true }] },
  { sec: 'Decide', items: [{ to: '/focus', label: 'Focus', icon: IconTarget }, { to: '/swing', label: 'Swing setups', icon: IconBolt }] },
  { sec: 'Rankings', items: [{ to: '/rankings/macro', label: 'Relative strength', icon: IconLayers }, { to: '/listings', label: 'New listings', icon: IconSpark }] },
  { sec: 'Market', items: [
    { to: '/breadth', label: 'Breadth', icon: IconPulse }, { to: '/rotation', label: 'Rotation', icon: IconRotate },
    { to: '/flows', label: 'FII / DII', icon: IconFlow }, { to: '/scans', label: 'Scans', icon: IconScan }] },
];

const TITLES: [RegExp, string, string][] = [
  [/^\/$/, 'Overview', 'Dashboard'], [/^\/focus/, 'Where to focus', 'Decide'], [/^\/swing/, 'Swing setups', 'Decide'],
  [/^\/rankings/, 'Relative strength', 'Rankings'], [/^\/listings/, 'New listings', 'Rankings'], [/^\/breadth/, 'Market breadth', 'Market'],
  [/^\/rotation/, 'Sector rotation', 'Market'], [/^\/flows/, 'FII / DII flows', 'Market'], [/^\/scans/, 'Scans', 'Market'],
];

/** NSE cash session: Mon–Fri 09:15–15:30 IST (holidays aside) */
function marketStatus(now = new Date()) {
  const ist = new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60000);
  const mins = ist.getHours() * 60 + ist.getMinutes(), wd = ist.getDay();
  const open = wd >= 1 && wd <= 5 && mins >= 555 && mins < 930;
  return { open, label: open ? 'Market open' : 'Market closed', clock: ist.toTimeString().slice(0, 5) };
}
const REGIME_WORD = { on: 'Risk-on', mixed: 'Mixed', off: 'Risk-off' } as const;

function StockSearch() {
  const { levels } = useAllLevels();
  const meta = useMeta().data;
  const { openStock } = useApp();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [act, setAct] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const all = useMemo(() => {
    const xs = levels ? stockIndex(levels).map(m => ({ s: m.s, n: m.n })) : [];
    const have = new Set(xs.map(x => x.s));
    for (const i of meta?.ipo ?? []) if (!have.has(i.s)) xs.push({ s: i.s, n: i.n });
    return xs;
  }, [levels, meta]);
  const hits = useMemo(() => {
    const t = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!t.length) return [];
    const score = (x: { s: string; n: string }) => (x.s.toLowerCase().startsWith(t[0]) ? 0 : 1);
    return all.filter(x => t.every(w => (x.s + ' ' + x.n).toLowerCase().includes(w))).sort((a, b) => score(a) - score(b)).slice(0, 12);
  }, [q, all]);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && !(e.target instanceof HTMLInputElement)) { e.preventDefault(); box.current?.querySelector('input')?.focus(); }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, []);
  const pick = (s: string) => { openStock(s); setQ(''); setOpen(false); };
  return (
    <div className="search" ref={box}>
      <IconSearch />
      <kbd>/</kbd>
      <input className="input" placeholder="Search 2,500+ stocks…" value={q} aria-label="Search stocks" data-testid="stock-search"
        onChange={e => { setQ(e.target.value); setOpen(true); setAct(0); }} onFocus={() => setOpen(true)}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setAct(a => Math.min(hits.length - 1, a + 1)); }
          if (e.key === 'ArrowUp') { e.preventDefault(); setAct(a => Math.max(0, a - 1)); }
          if (e.key === 'Enter' && hits[act]) pick(hits[act].s);
          if (e.key === 'Escape') { setQ(''); setOpen(false); }
        }} />
      {open && hits.length > 0 && <div className="search-res" role="listbox">
        {hits.map((h, i) => <button key={h.s} type="button" className={i === act ? 'act' : ''} onMouseEnter={() => setAct(i)} onClick={() => pick(h.s)}>
          <span className="s">{h.s}</span><span className="n">{h.n}</span>
        </button>)}
      </div>}
    </div>
  );
}

function UserMenu() {
  const { me, toast } = useApp();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);
  const run = async (what: 'prices' | 'stocks') => {
    setOpen(false);
    try {
      await (what === 'prices' ? startUpdate() : startRefreshStocks());
    } catch (e) { toast(`Couldn't start: ${(e as Error).message}`); return; }
    setRunning(what === 'prices' ? 'Updating prices…' : 'Refreshing listings…');
    toast('Started — this takes a few minutes');
    const t0 = Date.now();
    const poll = window.setInterval(async () => {
      try {
        const s = await pipelineStatus();
        if (s.running && Date.now() - t0 < 20 * 60 * 1000) return;
        window.clearInterval(poll);
        setRunning(null);
        if (s.last_result === 'ok') { await qc.invalidateQueries(); toast('Done — data updated'); }
        else toast(`Failed: ${(s.last_output || s.last_result || '').split('\n').filter(Boolean).slice(-2).join(' · ').slice(0, 160)}`);
      } catch { /* keep polling */ }
    }, 5000);
  };
  return (
    <div className="dropdown" ref={box}>
      <button className="btn user-btn" onClick={() => setOpen(o => !o)} aria-haspopup="menu" data-testid="user-menu">
        {running ? <><IconRefresh className="spin" />{running}</> : <><span className="avatar">{me.user.slice(0, 1)}</span><span className="hide-sm">{me.user}</span></>}
      </button>
      {open && <div className="dropdown-menu" role="menu">
        <div className="mh"><span className="avatar">{me.user.slice(0, 1)}</span><div><b>{me.user}</b>{me.role === 'admin' ? 'Administrator' : 'Viewer'}{!me.auth && ' · login off (local)'}</div></div>
        {me.can.update_prices && <button className="mi" disabled={!!running} onClick={() => run('prices')}><IconRefresh />Update prices now</button>}
        {me.can.refresh_stocks && <button className="mi" disabled={!!running} onClick={() => run('stocks')}><IconSpark />Refresh new listings</button>}
        {me.auth && <button className="mi" data-testid="logout" onClick={async () => {
          try { await logout(); } catch { /* already gone */ }
          qc.clear();
          nav('/login');
          window.location.reload();
        }}><IconLogout />Sign out</button>}
      </div>}
    </div>
  );
}

export function Layout() {
  const { theme, toggleTheme } = useApp();
  const loc = useLocation();
  const meta = useMeta().data;
  const decide = useDecide().data;
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [loc.pathname]);
  // /swing#list-htf: scroll to the section once the page has rendered it
  useEffect(() => {
    if (!loc.hash) { window.scrollTo(0, 0); return; }
    let tries = 0;
    const t = window.setInterval(() => {
      const el = document.getElementById(decodeURIComponent(loc.hash.slice(1)));
      if (el || ++tries > 40) {
        window.clearInterval(t);
        el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 75);
    return () => window.clearInterval(t);
  }, [loc.pathname, loc.hash]);
  const hit = TITLES.find(([re]) => re.test(loc.pathname));
  const title = hit?.[1] ?? '', section = hit?.[2] ?? '';
  const [mkt, setMkt] = useState(marketStatus);
  useEffect(() => { const t = window.setInterval(() => setMkt(marketStatus()), 30000); return () => window.clearInterval(t); }, []);
  const asof = decide?.asof || meta?.drange.split('→').pop()?.trim();
  const reg = decide?.regime;
  useEffect(() => { document.title = title ? `${title} · NSE RS` : 'NSE Relative Strength'; }, [title]);
  return (
    <div className={`shell ${navOpen ? 'nav-open' : ''}`} onClick={e => {
      if (navOpen && (e.target as HTMLElement).classList.contains('shell')) setNavOpen(false);
    }}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <div className="brand-mark"><Logo /></div>
          <div><div className="brand-name">NSE Relative Strength</div><div className="brand-sub">vs NIFTY 500</div></div>
        </div>
        {NAV.map(g => <div key={g.sec ?? 'top'}>
          {g.sec && <div className="nav-sec">{g.sec}</div>}
          {g.items.map(it => <NavLink key={it.to} to={it.to} end={'end' in it ? it.end : false}
            className={({ isActive }) => `nav-link ${isActive || (it.to.startsWith('/rankings') && loc.pathname.startsWith('/rankings')) ? 'active' : ''}`}>
            <it.icon />{it.label}
            {it.to === '/swing' && decide && <span className="nav-count">{decide.breakouts.length}</span>}
            {it.to === '/listings' && meta && <span className="nav-count">{meta.ipo.length}</span>}
          </NavLink>)}
        </div>)}
        <div className="side-foot">
          <div className="market-box" data-testid="market-box">
            <div className="mb-h"><span className={`live ${mkt.open ? 'open' : ''}`} />{mkt.label}<span className="muted" style={{ marginLeft: 'auto', fontWeight: 500 }}>{mkt.clock} IST</span></div>
            {meta && <>Data <b>{fmtDate(asof)}</b> close<br />Built {meta.generated} · {meta.n_window.toLocaleString('en-IN')} ranked</>}
            {mkt.open && <div style={{ marginTop: 6, color: 'var(--text-3)' }}>Today's numbers arrive after 15:30.</div>}
          </div>
          <div className="disclaimer">For research only — not investment advice.</div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn icon ghost menu-btn" onClick={() => setNavOpen(o => !o)} aria-label="Menu"><IconMenu /></button>
          <div className="crumb"><small>{section}</small><h1>{title}</h1></div>
          {reg && <span className="regime-pill hide-sm" title={`${reg.pass} of ${reg.known} regime checks pass`} data-testid="regime-chip">
            <span className={`dot ${reg.level}`} />{REGIME_WORD[reg.level]} <span className="muted" style={{ fontWeight: 500 }}>{reg.pass}/{reg.known}</span>
          </span>}
          {asof && <span className="tag outline hide-sm" style={{ height: 30, borderRadius: 99, padding: '0 12px' }} title="data covers completed sessions only">{fmtDate(asof)} close</span>}
          <div className="spacer" />
          <StockSearch />
          <button className="btn icon" onClick={toggleTheme} aria-label="Toggle theme" data-testid="theme-toggle">
            {theme === 'dark' ? <IconMoon /> : <IconSun />}
          </button>
          <UserMenu />
        </header>
        <main className="page"><Outlet /></main>
      </div>
      <StockModal />
    </div>
  );
}
