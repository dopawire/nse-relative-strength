/**
 * NSE Relative Strength — Frontend App
 * Vanilla JS, no framework. Smooth, fast, professional.
 */
(function () {
  'use strict';

  // =========================================================================
  // STATE
  // =========================================================================
  const state = {
    meta: null,
    levels: [],          // [{key, label, n_groups}]
    activeTab: 'macro',
    levelData: {},       // {key: {groups: [...]}} — cache of fetched level data
    groupMembers: {},    // {gid: [...]} — cache of fetched member data
    emaFilter: new Set(),
    hiFilter: { on: false, max: 20 },
    adrFilter: { on: false, min: 3 },
    rsFilter: { on: false, min: 80 },
    rseFilter: false,
    watchlist: loadWatchlist(),   // localStorage star list
    watchlistOnly: false,
    rotationData: null,   // cached rotation RS-lines
    rotRange: '6M',       // rotation period: ~2px per session → every day hoverable
    scan: { dim: 'cap' },   // Scans breakdown tab
    flowsData: null,      // cached FII / DII monthly flows
    decide: null,         // Focus / Swing decisions (rs_engine.decide)
    track: null,          // their track record
    flowRange: '3Y',      // FII / DII chart period
    selected: new Set(), // selected symbols for TradingView export
    breadthData: null,   // cached breadth oscillator data
    theme: 'dark',
    sortKey: 'pct',      // current sort column
    sortAsc: false,      // false = descending (default for pct)
  };

  // =========================================================================
  // DOM REFS (populated after DOM ready)
  // =========================================================================
  let $ = {};

  // =========================================================================
  // API — FastAPI backend when present, rs_data.json fallback for the static
  // export (GitHub Pages): the page auto-detects and switches seamlessly.
  // =========================================================================
  let staticData = null;   // null = backend mode; object = static mode

  async function bootApi() {
    try {
      const r = await fetch('/api/meta', { cache: 'no-store' });
      if (r.ok) return;                      // backend present — normal mode
    } catch (e) { /* no backend — fall through to static mode */ }
    const r = await fetch('rs_data.json', { cache: 'no-store' });
    if (!r.ok) throw new Error('neither API nor rs_data.json is reachable');
    staticData = await r.json();
    document.body.classList.add('static-mode');
  }

  function staticMeta() {
    const m = staticData.meta;
    return {
      benchmark: 'NIFTY 500',
      window: (m.window_dates || []).length || 26,
      drange: m.drange,
      generated: m.gen,
      n_stocks: m.n_stocks,
      n_groups_per_level: staticData.levels.map(l => l.groups.length),
      n_window: m.n_window || 0,
      excluded: m.excluded || [],
      illiquid: m.illiquid || [],
      src: m.src || {},
      ipo: m.ipo || [],
    };
  }

  function staticBreadth() {
    const b = staticData.breadth;
    return {
      dates: b.dates,
      osc: b.osc,
      n: b.n,
      latest: b.osc.length ? b.osc[b.osc.length - 1] : 0.0,
      span: b.dates.length ? `${b.dates[0]} → ${b.dates[b.dates.length - 1]}` : '',
      macros: b.macros || [],
      divergence: b.divergence || {},
      market: b.market || {},
    };
  }

  const api = {
    async get(url) {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`API ${r.status}: ${url}`);
      return r.json();
    },
    async meta() {
      return staticData ? staticMeta() : api.get('/api/meta');
    },
    async levels() {
      return staticData
        ? staticData.levels.map(l => ({ key: l.key, label: l.label, n_groups: l.groups.length }))
        : api.get('/api/levels');
    },
    async level(key) {
      if (staticData) {
        const lv = staticData.levels.find(l => l.key === key);
        if (!lv) throw new Error(`no such level: ${key}`);
        return lv;
      }
      return api.get(`/api/levels/${key}`);
    },
    async group(gid) {
      if (staticData) {
        for (const lv of staticData.levels) {
          const g = lv.groups.find(g => g.id === gid);
          if (g) return g;
        }
        throw new Error(`no such group: ${gid}`);
      }
      return api.get(`/api/groups/${gid}`);
    },
    async breadth() {
      return staticData ? staticBreadth() : api.get('/api/breadth');
    },
    async decide() {
      return staticData ? (staticData.decide || {}) : api.get('/api/decide');
    },
    async track() {
      return staticData ? (staticData.track || {}) : api.get('/api/track');
    },
    async flows() {
      return staticData ? (staticData.flows || { months: [] }) : api.get('/api/flows');
    },
    async rotation() {
      return staticData
        ? (staticData.rotation || { dates: [], groups: [] })
        : api.get('/api/rotation');
    },
  };

  // =========================================================================
  // UTILS
  // =========================================================================
  const utils = {
    esc(s) {
      return String(s).replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    },

    greenBg(pct) {
      const r = Math.round(255 + (46 - 255) * pct);
      const g = Math.round(255 + (158 - 255) * pct);
      const b = Math.round(255 + (110 - 255) * pct);
      const text = pct < 0.55 ? '#0a3d24' : '#ffffff';
      return `background:rgb(${r},${g},${b});color:${text}`;
    },

    fmtPct(pct) { return Math.round(pct * 100) + '%'; },
    fmtPrice(p) { return p != null ? p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'; },
    fmtOffHi(h) { return h != null ? '-' + h.toFixed(1) + '%' : '—'; },
    fmtAdr(a) { return a != null ? a.toFixed(1) + '%' : '—'; },

    sparkline(series, w = 120, h = 22) {
      if (!series || !series.length) return '';
      const lo = Math.min(...series), hi = Math.max(...series);
      const rng = (hi - lo) || 1;
      const n = series.length;
      const gap = 1.5;
      const bw = (w - gap * (n - 1)) / n;
      let hiIdx = 0;
      for (let i = 1; i < n; i++) if (series[i] > series[hiIdx]) hiIdx = i;
      let bars = '';
      for (let i = 0; i < n; i++) {
        const bh = 3 + (series[i] - lo) / rng * (h - 4);
        const x = i * (bw + gap), y = h - bh;
        const col = i === hiIdx ? (state.theme === 'dark' ? '#3dd68c' : '#1e7a4d') : (state.theme === 'dark' ? '#2a5c3f' : '#a9dcc0');
        bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${col}" rx="0.6"/>`;
      }
      return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${bars}</svg>`;
    },

    debounce(fn, ms) {
      let t;
      return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
    },
  };

  // =========================================================================
  // THEME
  // =========================================================================
  function initTheme() {
    const saved = localStorage.getItem('rs-theme');
    if (saved) {
      state.theme = saved;
    } else if (window.matchMedia('(prefers-color-scheme: light)').matches) {
      state.theme = 'light';
    } else {
      state.theme = 'dark';
    }
    applyTheme();
  }

  function applyTheme() {
    document.documentElement.classList.toggle('light', state.theme === 'light');
    const icon = state.theme === 'light' ? '☀️' : '🌙';
    if ($.themeToggle) $.themeToggle.querySelector('.icon').textContent = icon;
    localStorage.setItem('rs-theme', state.theme);
  }

  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    applyTheme();
    // Re-render sparklines (they encode theme colors)
    refreshCurrentView();
  }

  // =========================================================================
  // ROUTING
  // =========================================================================
  function getHashTab() {
    const h = window.location.hash.replace('#/', '');
    return h || 'macro';
  }

  function setHashTab(tab) {
    if (window.location.hash !== '#/' + tab) {
      history.pushState(null, '', '#/' + tab);
    }
    activateTab(tab);
  }

  function activateTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    // Toolbars: level tables get search + filters; New Listings gets search only
    const isLevel = !['breadth', 'rotation', 'ipo', 'scans', 'flows', 'focus', 'swing'].includes(tab);
    $.toolbarSection.style.display = ['breadth', 'rotation', 'scans', 'flows', 'focus', 'swing'].includes(tab) ? 'none' : '';
    $.toolbarSection.classList.toggle('search-only', tab === 'ipo');
    $.note.style.display = isLevel ? '' : 'none';
    renderTab(tab);
  }

  window.addEventListener('hashchange', () => {
    const tab = getHashTab();
    if (tab !== state.activeTab) activateTab(tab);
  });

  // =========================================================================
  // RENDER: TAB PANELS
  // =========================================================================
  async function renderTab(tab) {
    $.content.innerHTML = '<div class="loading">Loading</div>';

    if (tab === 'breadth') {
      await renderBreadth();
      return;
    }
    if (tab === 'rotation') {
      await renderRotation();
      return;
    }
    if (tab === 'ipo') {
      renderIpo();
      return;
    }
    if (tab === 'scans') {
      await renderScans();
      return;
    }
    if (tab === 'flows') {
      renderFlows();
      return;
    }
    if (tab === 'focus') {
      await renderFocus();
      return;
    }
    if (tab === 'swing') {
      await renderSwing();
      return;
    }

    // Fetch level data if not cached
    if (!state.levelData[tab]) {
      try {
        state.levelData[tab] = await api.level(tab);
      } catch (e) {
        // Cache the error so we don't keep retrying on tab switch
        state.levelData[tab] = { _error: e.message };
        $.content.innerHTML = `<div class="brd-empty">Failed to load data: ${utils.esc(e.message)}<br><small>Switch tabs and come back to retry.</small></div>`;
        return;
      }
    } else if (state.levelData[tab]._error) {
      // Previously failed — retry once
      try {
        state.levelData[tab] = await api.level(tab);
      } catch (e) {
        state.levelData[tab] = { _error: e.message };
        $.content.innerHTML = `<div class="brd-empty">Failed to load data: ${utils.esc(e.message)}</div>`;
        return;
      }
    }

    const data = state.levelData[tab];
    renderLevelTable(tab, data);
  }

  function refreshCurrentView() {
    if (state.activeTab === 'breadth') {
      renderBreadth(true);   // use cached data — avoid re-fetching
    } else if (state.activeTab === 'scans') {
      if (state.levelData.macro && state.levelData.macro.groups) drawScans();
    } else if (state.activeTab === 'flows') {
      renderFlows();
    } else if (state.activeTab === 'focus') {
      renderFocus();
    } else if (state.activeTab === 'swing') {
      renderSwing();
    } else if (state.activeTab === 'ipo') {
      renderIpo();
    } else if (state.levelData[state.activeTab]) {
      renderLevelTable(state.activeTab, state.levelData[state.activeTab]);
    }
  }

  // =========================================================================
  // RENDER: LEVEL TABLE
  // =========================================================================
  function renderLevelTable(tab, data) {
    const q = ($.searchInput.value || '').trim().toLowerCase();
    const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter || state.watchlistOnly;

    let groups = data.groups || [];

    // Sort
    const asc = state.sortAsc;
    if (state.sortKey === 'pct') {
      groups = [...groups].sort((a, b) => asc ? a.pct - b.pct : b.pct - a.pct);
    } else {
      groups = [...groups].sort((a, b) => asc ? b.name.localeCompare(a.name) : a.name.localeCompare(b.name));
    }

    // Build
    let rows = '';
    let shownGroups = 0, shownStocks = 0;

    for (const g of groups) {
      // Check group name matches search
      const gmatch = q && g.name.toLowerCase().includes(q);

      // Filter members
      const members = g.members || [];
      let filteredMembers = members;
      if (filtering) {
        filteredMembers = members.filter(m => memberPasses(m, q, gmatch));
      }

      if (filtering && !filteredMembers.length) continue;

      const spark = utils.sparkline(g.r, 150, 28);
      const bg = utils.greenBg(g.pct);
      const nm = utils.esc(g.name);
      const gid = g.id;

      rows += `<tbody class="gb" data-gid="${gid}" data-pct="${g.pct.toFixed(6)}" data-name="${utils.esc(g.name)}">`;
      rows += `<tr class="grp">`;
      rows += `<td class="nm"><input type="checkbox" class="gpick" title="select all stocks in this group">`;
      const nNew = members.length - g.n;
      rows += `<span class="car">▶</span>${nm}<span class="cnt">${filtering ? filteredMembers.length : g.n}</span>${!filtering && nNew > 0 ? `<span class="cnt-new" title="new listings shown in the group, not yet in its RS index">+${nNew} new</span>` : ''}</td>`;
      rows += `<td class="sp">${spark}</td>`;
      rows += `<td class="pc"><span class="rs-pct" style="${bg}">${utils.fmtPct(g.pct)}</span>${g.dp != null ? `<span class="delta ${g.dp >= 0 ? 'up' : 'dn'}">${g.dp >= 0 ? '+' : ''}${g.dp.toFixed(0)}</span>` : ''}</td>`;
      rows += `</tr>`;

      // Sub-row for members (lazy)
      rows += `<tr class="sub hide"><td colspan="3" class="subcell"></td></tr>`;
      rows += `</tbody>`;

      shownGroups++;
      shownStocks += filtering ? filteredMembers.length : g.n;
    }

    const sortState = state.sortKey === 'pct' && !state.sortAsc ? ' class="desc"' : (state.sortKey === 'pct' ? ' class="asc"' : (state.sortAsc ? ' class="asc"' : ' class="desc"'));
    const tableHTML = `
      <div class="table-wrap">
        <table id="level-table">
          <thead><tr>
            <th data-sort="name"${state.sortKey === 'name' ? sortState : ''}>${data.label}</th>
            <th>Relative Strength</th>
            <th class="pc" data-sort="pct"${state.sortKey === 'pct' ? sortState : ''}>RS_STS%</th>
          </tr></thead>
          ${rows}
        </table>
      </div>`;

    $.content.innerHTML = tableHTML;

    // Update search info
    $.searchInfo.textContent = filtering ? `${shownGroups} group(s), ${shownStocks} stock(s)` : '';
    updateIpoHint();

    // Bind events
    bindTableEvents();
    updateSelectionUI();
  }

  // =========================================================================
  // FILTER LOGIC
  // =========================================================================
  function memberPasses(m, q, gmatch) {
    if (q && !gmatch && !(m.n + ' ' + m.s).toLowerCase().includes(q)) return false;
    for (const ei of state.emaFilter) {
      if (m.e[ei] !== 1) return false;
    }
    if (state.hiFilter.on) {
      if (m.h == null || m.h > state.hiFilter.max) return false;
    }
    if (state.adrFilter.on) {
      if (m.a == null || m.a < state.adrFilter.min) return false;
    }
    if (state.rsFilter.on) {
      if (m.p == null || m.p * 100 < state.rsFilter.min) return false;
    }
    if (state.rseFilter) {
      if (m.b !== 1) return false;
    }
    if (state.watchlistOnly) {
      if (!state.watchlist.has(m.s)) return false;
    }
    return true;
  }

  // =========================================================================
  // GET GROUP MEMBERS (from cache, level data, or API)
  // =========================================================================
  function getGroupMembersSync(gid) {
    if (state.groupMembers[gid]) return state.groupMembers[gid];
    // Look in already-fetched level data (members are embedded)
    for (const lv of Object.values(state.levelData)) {
      for (const g of (lv.groups || [])) {
        if (g.id === gid && g.members) {
          state.groupMembers[gid] = g.members;
          return g.members;
        }
      }
    }
    return null;
  }

  async function getGroupMembers(gid) {
    let members = getGroupMembersSync(gid);
    if (members) return members;
    try {
      const data = await api.group(gid);
      state.groupMembers[gid] = data.members || [];
      return state.groupMembers[gid];
    } catch (e) {
      return null;
    }
  }

  // =========================================================================
  // RENDER: MEMBER SUB-TABLE (lazy)
  // =========================================================================
  async function expandGroup(body) {
    const sub = body.querySelector('tr.sub');
    const gid = +body.dataset.gid;

    // Toggle
    if (!sub.classList.contains('hide')) {
      sub.classList.add('hide');
      body.querySelector('.car').classList.remove('open');
      return;
    }

    // Fetch if not cached
    const members = await getGroupMembers(gid);
    if (!members) {
      sub.querySelector('td.subcell').innerHTML = '<span style="color:var(--danger)">Failed to load members</span>';
      sub.classList.remove('hide');
      return;
    }

    const q = ($.searchInput.value || '').trim().toLowerCase();
    const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter || state.watchlistOnly;
    const gmatch = q && (body.dataset.name || '').toLowerCase().includes(q);

    let visibleMembers = members;
    if (filtering) {
      visibleMembers = members.filter(m => memberPasses(m, q, gmatch));
    }

    const EMA_HEAD = [20, 50, 100, 150, 200].map(p => `<th class="eh">${p}</th>`).join('');
    let mrows = '';
    for (const m of visibleMembers) {
      const spark = utils.sparkline(m.r, 120, 20);
      const bg = utils.greenBg(m.p);
      const ck = state.selected.has(m.s) ? ' checked' : '';
      let emaCells = '';
      for (const e of m.e) {
        emaCells += `<td class="e" data-a="${e}"></td>`;
      }
      const rseCell = m.b === 1
        ? '<td class="mrse"><span class="rse-badge up">above</span></td>'
        : (m.b === 0
          ? '<td class="mrse"><span class="rse-badge dn">below</span></td>'
          : '<td class="mrse"><span class="rse-badge na">—</span></td>');
      const star = state.watchlist.has(m.s) ? '★' : '☆';
      const dBadge = (m.d != null)
        ? `<span class="delta ${m.d >= 0 ? 'up' : 'dn'}">${m.d >= 0 ? '+' : ''}${m.d.toFixed(0)}</span>`
        : '';
      // new listing: ranked over its days since listing, not in the group index yet
      const newBadge = m.nw
        ? `<span class="new-badge" title="New listing — RS% over its ${m.nw} trading days since listing; joins the group index after a full window">NEW · ${m.nw}d</span>`
        : '';
      mrows += `<tr data-sym="${utils.esc(m.s)}">
        <td class="mck"><input type="checkbox" class="pick" data-sym="${utils.esc(m.s)}"${ck}></td>
        <td class="mnm"><button class="wstar${state.watchlist.has(m.s) ? ' on' : ''}" data-sym="${utils.esc(m.s)}" title="watchlist">${star}</button>${utils.esc(m.n)}<span class="msym">${utils.esc(m.s)}</span>${newBadge}${dBadge}</td>
        <td class="msp">${spark}</td>
        <td class="mpc"><span class="rs-pct${m.nw ? ' since-listing' : ''}" style="${bg}"${m.nw ? ` title="since listing (${m.nw} days)"` : ''}>${utils.fmtPct(m.p)}</span></td>
        <td class="mlt tnum">${utils.fmtPrice(m.l)}</td>
        <td class="mhi tnum">${utils.fmtOffHi(m.h)}</td>
        <td class="madr tnum">${utils.fmtAdr(m.a)}</td>
        ${rseCell}
        ${emaCells}
      </tr>`;
    }

    const subHead = `<thead><tr>
      <th></th><th class="ehn">Stock</th><th>RS</th>
      <th class="ehp">RS%</th><th class="ehl">LTP</th>
      <th class="ehh">Off Hi</th><th class="eha">ADR%</th>
      <th class="ehr" title="RS line (stock / NIFTY 500) vs its 21-day EMA">RS21</th>
      ${EMA_HEAD}</tr></thead>`;

    sub.querySelector('td.subcell').innerHTML = `<table class="sub-table">${subHead}<tbody>${mrows}</tbody></table>`;
    sub.classList.remove('hide');
    body.querySelector('.car').classList.add('open');
  }

  // =========================================================================
  // RENDER: BREADTH CHART
  // =========================================================================
  async function renderBreadth(useCache = false) {
    try {
      let data = useCache ? state.breadthData : null;
      if (!data) {
        data = await api.breadth();
        state.breadthData = data;
      }
      if (!data.dates || !data.dates.length) {
        $.content.innerHTML = '<div class="brd-empty">Not enough history. Run <code>python3 build_rs.py --refresh</code>.</div>';
        return;
      }
      // macro RS_STS% badges come from the macro level (lazy-fetched once)
      let pctMap = {};
      if (data.macros && data.macros.length && !state.levelData.macro) {
        try { state.levelData.macro = await api.level('macro'); } catch (e) { /* badges optional */ }
      }
      const ml = state.levelData.macro;
      if (ml && ml.groups) {
        for (const g of ml.groups) pctMap[g.name] = g.pct;
      }
      $.content.innerHTML = buildBreadthHTML(data, pctMap);
      bindBreadthEvents(data);
      bindMacroEvents(data);
    } catch (e) {
      $.content.innerHTML = `<div class="brd-empty">Failed to load breadth data: ${utils.esc(e.message)}</div>`;
    }
  }

  function buildBreadthHTML(data, pctMap = {}) {
    const { dates, osc, n, latest, span } = data;
    if (!osc || osc.length < 2) {
      return '<div class="brd-empty">Not enough price history. Run <code>python3 build_rs.py --refresh</code>.</div>';
    }

    const nPts = osc.length;
    const L = 52, R = 44, T = 18, B = 46, ph = 300;
    const pw = Math.max(640, 4.2 * (nPts - 1));
    const W = L + pw + R, H = T + ph + B;
    const amax = Math.max(Math.abs(Math.min(...osc)), Math.abs(Math.max(...osc)));
    const ymax = Math.max(20, Math.ceil(amax / 10) * 10);

    const X = i => L + pw * i / (nPts - 1);
    const Y = v => T + ph * (1 - (v + ymax) / (2 * ymax));

    let parts = [];

    // Overbought/oversold zones
    if (40 < ymax) {
      parts.push(`<rect x="${L}" y="${T}" width="${pw.toFixed(1)}" height="${Y(40) - T}" fill="${state.theme === 'dark' ? '#0d2b1d' : '#eaf7f0'}"/>`);
      parts.push(`<rect x="${L}" y="${Y(-40)}" width="${pw.toFixed(1)}" height="${T + ph - Y(-40)}" fill="${state.theme === 'dark' ? '#2d1115' : '#fdeceb'}"/>`);
    }

    // Grid + y-axis labels
    const step = ymax <= 80 ? 20 : 40;
    for (let v = -ymax; v <= ymax + 0.1; v += step) {
      const y = Y(v);
      const stroke = v === 0 ? (state.theme === 'dark' ? '#4a5568' : '#9aa6b2') : (state.theme === 'dark' ? '#252840' : '#edf1f4');
      const sw = v === 0 ? 1.4 : 1;
      parts.push(`<line x1="${L}" y1="${y.toFixed(1)}" x2="${L + pw.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${stroke}" stroke-width="${sw}"/>`);
      parts.push(`<text x="${L - 7}" y="${y + 3}" font-size="10" fill="${state.theme === 'dark' ? '#9ca3af' : '#7a8794'}" text-anchor="end">${v > 0 ? '+' : ''}${v}</text>`);
      parts.push(`<text x="${L + pw + 6}" y="${y + 3}" font-size="10" fill="${state.theme === 'dark' ? '#9ca3af' : '#7a8794'}">${v > 0 ? '+' : ''}${v}</text>`);
    }

    // +/-40 dashed guides
    for (const g of [40, -40]) {
      if (Math.abs(g) < ymax) {
        parts.push(`<line x1="${L}" y1="${Y(g)}" x2="${L + pw.toFixed(1)}" y2="${Y(g)}" stroke="${state.theme === 'dark' ? '#f87171' : '#c0392b'}" stroke-width="1" stroke-dasharray="4 4" opacity="0.45"/>`);
      }
    }

    // Time axis: month gridlines + labels
    const firstIdx = {}, order = [];
    for (let i = 0; i < dates.length; i++) {
      const ym = dates[i].substring(0, 7);
      if (!(ym in firstIdx)) { firstIdx[ym] = i; order.push(ym); }
    }
    let lastLabelX = -1e9, prevYear = null;
    for (let k = 0; k < order.length; k++) {
      const ym = order[k];
      const i0 = firstIdx[ym];
      const i1 = (k + 1 < order.length) ? firstIdx[order[k + 1]] - 1 : nPts - 1;
      const span = i1 - i0 + 1;
      const mx = X(i0);
      const year = ym.substring(0, 4);
      const isYearStart = year !== prevYear;
      prevYear = year;
      parts.push(`<line x1="${mx.toFixed(1)}" y1="${T}" x2="${mx.toFixed(1)}" y2="${T + ph}" stroke="${isYearStart ? (state.theme === 'dark' ? '#4a5568' : '#d3dae1') : (state.theme === 'dark' ? '#252840' : '#eef1f4')}" stroke-width="${isYearStart ? 1.3 : 1}"/>`);
      const midx = X((i0 + i1) / 2);
      const mon = new Date(ym + '-01').toLocaleString('en', { month: 'short' });
      if (span >= 6 && (midx - lastLabelX) >= 24) {
        parts.push(`<text x="${midx.toFixed(1)}" y="${T + ph + 16}" font-size="10" fill="${state.theme === 'dark' ? '#9ca3af' : '#7a8794'}" text-anchor="middle">${mon}</text>`);
        lastLabelX = midx;
      }
      if (isYearStart) {
        parts.push(`<text x="${mx.toFixed(1)}" y="${T + ph + 34}" font-size="11" font-weight="700" fill="${state.theme === 'dark' ? '#e8eaf0' : '#46505c'}" text-anchor="middle">${year}</text>`);
      }
    }

    // Oscillator line
    for (let i = 1; i < nPts; i++) {
      const col = (osc[i - 1] + osc[i]) / 2 >= 0 ? (state.theme === 'dark' ? '#3dd68c' : '#1e7a4d') : (state.theme === 'dark' ? '#f87171' : '#c0392b');
      parts.push(`<line x1="${X(i - 1).toFixed(1)}" y1="${Y(osc[i - 1]).toFixed(1)}" x2="${X(i).toFixed(1)}" y2="${Y(osc[i]).toFixed(1)}" stroke="${col}" stroke-width="1.6"/>`);
    }

    // Last point marker
    const lx = X(nPts - 1), ly = Y(osc[nPts - 1]);
    parts.push(`<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3" fill="${state.theme === 'dark' ? '#e8eaf0' : '#111'}"/>`);

    // Crosshair + hover dot (moved by JS)
    parts.push(`<line id="brd-cross" x1="0" y1="${T}" x2="0" y2="${T + ph}" stroke="${state.theme === 'dark' ? '#9ca3af' : '#5a6672'}" stroke-width="1" stroke-dasharray="3 3" style="visibility:hidden"/>`);
    parts.push(`<circle id="brd-dot" r="3.5" fill="${state.theme === 'dark' ? '#e8eaf0' : '#111'}" stroke="${state.theme === 'dark' ? '#1a1d2a' : '#fff'}" stroke-width="1.5" style="visibility:hidden"/>`);

    const svg = `<svg id="brd-svg" width="${W.toFixed(0)}" height="${H.toFixed(0)}" viewBox="0 0 ${W.toFixed(0)} ${H.toFixed(0)}" class="brd-svg">${parts.join('')}</svg>`;

    return `<div class="brd-wrap">
      <div class="brd-head">NSE Market Breadth Oscillator
        <span> · McClellan-style: 19- vs 39-day EMA of ratio-adjusted (advancers − decliners) across ${n} stocks · ${span}</span>
      </div>
      ${divergenceBanner(data.divergence)}
      <div class="brd-scroll" id="brd-scroll">
        ${svg}
        <div class="brd-tip" id="brd-tip"></div>
      </div>
      <div class="brd-cap">Latest reading <b>${latest >= 0 ? '+' : ''}${latest.toFixed(1)}</b>. Extreme lows (≈ −40 and below) flag oversold / possible bottoms; extreme highs (≈ +40 and above) flag overbought — reversal warnings.</div>
      <blockquote class="brd-q">Zanger: "I use one custom oscillator in particular which uses market breadth advance-decline data to give me a heads up on trend strength and potential reversals. When it hits extreme lows or highs, it usually means a reversal of some sort is ahead."</blockquote>
    </div>
    ${macroBreadthSection(data, pctMap)}
    ${provenanceHTML()}`;
  }

  // ---- Data provenance (which dates came from something other than Yahoo) ----
  function divergenceBanner(div) {
    if (!div || !div.state || div.state === 'none') return '';
    const bear = div.state === 'bearish';
    return `<div class="div-warn ${bear ? 'bear' : 'bull'}">
      <b>${bear ? 'Bearish divergence' : 'Bullish divergence'}</b> — ${utils.esc(div.note || '')}</div>`;
  }

  function provenanceHTML() {
    const src = (state.meta && state.meta.src) || {};
    const dates = Object.keys(src).sort();
    if (!dates.length) return '';
    const counts = {};
    for (const d of dates) counts[src[d]] = (counts[src[d]] || 0) + 1;
    const summary = Object.entries(counts).map(([k, v]) => `${v} via ${k}`).join(' · ');
    const items = dates.map(d => `<li>${d} — <code>${src[d]}</code></li>`).join('');
    return `<details class="prov"><summary>Data provenance — ${dates.length} date(s) not from Yahoo daily bars · ${summary}</summary>
      <ul class="prov-list">${items}</ul>
      <p class="prov-note">All other trading days use Yahoo daily closes.
      Sources: <code>investing.com</code> — official index close ·
      <code>bhavcopy</code> — NSE official EOD file ·
      <code>intraday</code> — reconstructed from Yahoo 5-minute bars ·
      <code>synthetic</code> — equal-weight stock returns.</p></details>`;
  }

  // ---- Macro breadth dashboard (12 small oscillator charts) ----
  function macroBreadthSection(data, pctMap) {
    const macros = data.macros || [];
    if (!macros.length) return '';
    const cards = macros.map((m, i) => macroCardHTML(m, i, pctMap)).join('');
    return `<div class="mbrd-head">Macro breadth — ${macros.length} macros
      <span> · same oscillator (19- vs 39-day EMA of RANA) per macro group · hover for values</span></div>
      <div class="macro-grid">${cards}</div>`;
  }

  function macroCardHTML(mb, i, pctMap) {
    const pos = mb.latest >= 0;
    const pct = pctMap[mb.name];
    return `<div class="macro-card">
      <div class="mhead">
        <span class="mname">${utils.esc(mb.name)}</span>
        <span class="mbadges">
          <span class="mbadge ${pos ? 'up' : 'dn'}">${pos ? '+' : ''}${mb.latest.toFixed(1)}</span>
          ${pct != null ? `<span class="mbadge rs">RS ${Math.round(pct * 100)}%</span>` : ''}
        </span>
      </div>
      <div class="mplot">${macroChartSVG(mb, i)}<div class="mtip" id="mtip-${i}"></div></div>
    </div>`;
  }

  function macroChartSVG(mb, i) {
    const osc = mb.osc, n = osc.length;
    const W = 340, H = 150, L = 6, R = 44, T = 10, B = 16;
    const ph = H - T - B, pw = W - L - R;
    const amax = Math.max(...osc.map(Math.abs), 0.001);
    const ymax = Math.ceil(amax / 10) * 10 + 10;
    const X = k => L + pw * k / (n - 1);
    const Y = v => T + ph * (1 - (v + ymax) / (2 * ymax));
    const green = state.theme === 'dark' ? '#3dd68c' : '#1e7a4d';
    const red = state.theme === 'dark' ? '#f87171' : '#c0392b';
    const muted = state.theme === 'dark' ? '#9ca3af' : '#7a8794';
    const zero = state.theme === 'dark' ? '#4a5568' : '#9aa6b2';

    let p = [];
    p.push(`<line x1="${L}" y1="${Y(0).toFixed(1)}" x2="${L + pw}" y2="${Y(0).toFixed(1)}" stroke="${zero}" stroke-width="1"/>`);
    for (let k = 1; k < n; k++) {
      const col = (osc[k - 1] + osc[k]) / 2 >= 0 ? green : red;
      p.push(`<line x1="${X(k - 1).toFixed(1)}" y1="${Y(osc[k - 1]).toFixed(1)}" x2="${X(k).toFixed(1)}" y2="${Y(osc[k]).toFixed(1)}" stroke="${col}" stroke-width="1.3"/>`);
    }
    const lx = X(n - 1), ly = Y(osc[n - 1]);
    p.push(`<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="2.5" fill="${state.theme === 'dark' ? '#e8eaf0' : '#111'}"/>`);
    p.push(`<text x="${L + pw + 4}" y="${Y(ymax) + 3}" font-size="9" fill="${muted}">+${ymax}</text>`);
    p.push(`<text x="${L + pw + 4}" y="${Y(0) + 3}" font-size="9" fill="${muted}">0</text>`);
    p.push(`<text x="${L + pw + 4}" y="${Y(-ymax) + 3}" font-size="9" fill="${muted}">-${ymax}</text>`);
    p.push(`<line id="mcross-${i}" x1="0" y1="${T}" x2="0" y2="${T + ph}" stroke="${state.theme === 'dark' ? '#9ca3af' : '#5a6672'}" stroke-width="1" stroke-dasharray="3 3" style="visibility:hidden"/>`);
    p.push(`<circle id="mdot-${i}" r="3" fill="${state.theme === 'dark' ? '#e8eaf0' : '#111'}" style="visibility:hidden"/>`);
    return `<svg id="msvg-${i}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="mbrd-svg">${p.join('')}</svg>`;
  }

  function bindMacroEvents(data) {
    const macros = data.macros || [];
    macros.forEach((mb, i) => {
      const svg = document.getElementById('msvg-' + i);
      const tip = document.getElementById('mtip-' + i);
      const cross = document.getElementById('mcross-' + i);
      const dot = document.getElementById('mdot-' + i);
      if (!svg || !tip) return;
      const osc = mb.osc, dates = mb.dates, n = osc.length;
      const W = 340, H = 150, L = 6, R = 44, T = 10, B = 16;
      const ph = H - T - B, pw = W - L - R;
      const amax = Math.max(...osc.map(Math.abs), 0.001);
      const ymax = Math.ceil(amax / 10) * 10 + 10;
      const X = k => L + pw * k / (n - 1);
      const Y = v => T + ph * (1 - (v + ymax) / (2 * ymax));
      const fmtD = s => {
        const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const a = s.split('-');
        return a[2] + ' ' + m[+a[1] - 1] + ' ' + a[0];
      };
      svg.addEventListener('mousemove', function (e) {
        const r = svg.getBoundingClientRect();
        const sx = W / r.width;
        const x = (e.clientX - r.left) * sx;
        let k = Math.round((x - L) / pw * (n - 1));
        if (k < 0) k = 0; if (k >= n) k = n - 1;
        const px = X(k), py = Y(osc[k]);
        cross.setAttribute('x1', px); cross.setAttribute('x2', px);
        cross.style.visibility = 'visible';
        dot.setAttribute('cx', px); dot.setAttribute('cy', py);
        dot.style.visibility = 'visible';
        const v = osc[k];
        tip.innerHTML = `<b>${fmtD(dates[k])}</b>${v >= 0 ? '+' : ''}${v.toFixed(1)}`;
        tip.style.visibility = 'visible';
        const tipW = tip.offsetWidth;
        const plotW = svg.parentNode.clientWidth;
        let left = (e.clientX - r.left) - tipW / 2;
        left = Math.max(2, Math.min(left, plotW - tipW - 2));
        tip.style.left = left + 'px';
        tip.style.top = (py * (r.height / H) - 30) + 'px';
      });
      svg.addEventListener('mouseleave', function () {
        cross.style.visibility = 'hidden';
        dot.style.visibility = 'hidden';
        tip.style.visibility = 'hidden';
      });
    });
  }

  function bindBreadthEvents(data) {
    const { dates, osc } = data;
    const nPts = osc.length;
    const L = 52, T = 18, ph = 300;
    const pw = Math.max(640, 4.2 * (nPts - 1));

    const svg = document.getElementById('brd-svg');
    const cross = document.getElementById('brd-cross');
    const dot = document.getElementById('brd-dot');
    const tip = document.getElementById('brd-tip');
    const scroll = document.getElementById('brd-scroll');

    if (!svg) return;

    const amax = Math.max(Math.abs(Math.min(...osc)), Math.abs(Math.max(...osc)));
    const ymax = Math.max(20, Math.ceil(amax / 10) * 10);
    const W = L + pw + 44, H = T + ph + 46;

    function X(i) { return L + pw * i / (nPts - 1); }
    function Y(v) { return T + ph * (1 - (v + ymax) / (2 * ymax)); }

    function fmt(s) {
      const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const a = s.split('-');
      return a[2] + ' ' + m[+a[1] - 1] + ' ' + a[0];
    }

    svg.addEventListener('mousemove', function (e) {
      const r = svg.getBoundingClientRect();
      const sx = W / r.width;
      const x = (e.clientX - r.left) * sx;
      let i = Math.round((x - L) / pw * (nPts - 1));
      if (i < 0) i = 0; if (i >= nPts) i = nPts - 1;
      const px = X(i), py = Y(osc[i]);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px);
      cross.style.visibility = 'visible';
      dot.setAttribute('cx', px); dot.setAttribute('cy', py);
      dot.style.visibility = 'visible';
      const val = osc[i];
      tip.innerHTML = `<b>${fmt(dates[i])}</b><span>${val >= 0 ? '+' : ''}${val.toFixed(1)}</span>`;
      tip.style.visibility = 'visible';
      const cx = (e.clientX - scroll.getBoundingClientRect().left) + scroll.scrollLeft;
      // Clamp the tooltip inside the VISIBLE area — at the chart's right edge
      // (latest point) it used to overflow and stretch the horizontal scroll.
      const tipW = tip.offsetWidth;
      const scW = scroll.clientWidth;
      let left = (cx - scroll.scrollLeft) - tipW / 2;
      if (left < 2) left = 2;
      if (left > scW - tipW - 2) left = scW - tipW - 2;
      tip.style.left = (scroll.scrollLeft + left) + 'px';
      tip.style.top = (py * (r.height / H) - 34) + 'px';
    });

    svg.addEventListener('mouseleave', function () {
      cross.style.visibility = 'hidden';
      dot.style.visibility = 'hidden';
      tip.style.visibility = 'hidden';
    });
  }

  // =========================================================================
  // PHASE 4: ROTATION TAB, NEW LISTINGS, STOCK RS CHART, WATCHLIST, CSV
  // =========================================================================
  function renderRotation() {
    if (state.rotationData) return drawRotation(state.rotationData);
    $.content.innerHTML = '<div class="loading">Loading</div>';
    api.rotation().then(data => {
      state.rotationData = data;
      drawRotation(data);
    }).catch(e => {
      $.content.innerHTML = `<div class="brd-empty">Failed to load rotation data: ${utils.esc(e.message)}</div>`;
    });
  }

  // calendar months per period (All = 0).  A 340px card holds ~280px of
  // plot, so beyond ~1Y a pixel spans several sessions and hover can't reach
  // each day — hence the 6M default.
  const ROT_RANGES = { '3M': 3, '6M': 6, '1Y': 12, 'All': 0 };

  // Index of the base session: the close on (or the last one before) the same
  // calendar date `months` earlier than the latest date — 30-Oct → 30-Jul for
  // 3M, as charting tools measure it.
  function rotStartIndex(dates, months) {
    if (!months || !dates.length) return 0;
    const [y, m, d] = dates[dates.length - 1].split('-').map(Number);
    const back = new Date(Date.UTC(y, m - 1 - months, 1));
    const lastDay = new Date(Date.UTC(back.getUTCFullYear(), back.getUTCMonth() + 1, 0)).getUTCDate();
    back.setUTCDate(Math.min(d, lastDay));            // 31-May − 3M → 28/29-Feb
    const cutoff = back.toISOString().slice(0, 10);
    let i = 0;
    while (i + 1 < dates.length && dates[i + 1] <= cutoff) i++;
    return i;
  }

  function drawRotation(data) {
    const allDates = data.dates || [];
    const groups = data.groups || [];
    if (!groups.length) {
      $.content.innerHTML = '<div class="brd-empty">No rotation data yet — run a build.</div>';
      return;
    }
    // period slice, rebased to 1.0 at its base session
    const start = rotStartIndex(allDates, ROT_RANGES[state.rotRange]);
    const dates = allDates.slice(start);
    const sliced = groups.map(g => {
      const base = g.rs[start] || 1;
      return g.rs.slice(start).map(v => v / base);
    });
    const cards = groups.map((g, i) => {
      const rs = sliced[i];
      const total = ((rs[rs.length - 1] / rs[0]) - 1) * 100;
      const pos = total >= 0;
      return `<div class="macro-card">
        <div class="mhead">
          <span class="mname">${utils.esc(g.name)}</span>
          <span class="mbadges">
            <span class="mbadge ${pos ? 'up' : 'dn'}">${pos ? '+' : ''}${total.toFixed(1)}%</span>
          </span>
        </div>
        <div class="mplot">${lineChartSVG(rs, null, 'rot-' + i, 340, 140)}
          <div class="mtip" id="rot-tip-${i}"></div></div>
      </div>`;
    }).join('');
    const pills = Object.keys(ROT_RANGES).map(k =>
      `<button type="button" class="rot-range${k === state.rotRange ? ' on' : ''}" data-range="${k}">${k}</button>`).join('');
    $.content.innerHTML = `<div class="mbrd-head">Sector rotation — RS vs NIFTY 500
      <span class="rot-ranges">${pills}</span>
      <span> · chain-linked equal-weight sector index ÷ NIFTY 500, rebased to 1.0 at ${dates[0] || 'start'} · ${dates.length - 1} sessions to ${dates[dates.length - 1] || ''}, one point per trading day · hover for values</span></div>
      <div class="macro-grid">${cards}</div>`;
    groups.forEach((g, i) => {
      bindLineChart('rot-' + i, dates, sliced[i], null, document.getElementById('rot-tip-' + i));
    });
    $.content.querySelectorAll('.rot-range').forEach(b => b.addEventListener('click', () => {
      state.rotRange = b.dataset.range;
      drawRotation(data);
    }));
  }

  // Multi-word search: every token must appear in name or symbol
  function ipoMatches(ipo, q) {
    const toks = (q || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!toks.length) return ipo;
    return ipo.filter(i => toks.every(t => (i.n + ' ' + i.s).toLowerCase().includes(t)));
  }

  // When a ranking-table search also matches a new listing, surface a clickable
  // hint so stocks like Jindal Supreme (JSIPL) are discoverable from any tab.
  function updateIpoHint() {
    const q = ($.searchInput.value || '').trim().toLowerCase();
    if (!q || state.activeTab !== 'macro' && state.activeTab !== 'sector'
        && state.activeTab !== 'industry' && state.activeTab !== 'basic') return;
    const hits = ipoMatches((state.meta && state.meta.ipo) || [], q);
    if (!hits.length) return;
    const b = document.createElement('button');
    b.className = 'ipo-hint';
    b.type = 'button';
    b.textContent = hits.length === 1
      ? `${hits[0].s} in New Listings →`
      : `${hits.length} in New Listings →`;
    b.addEventListener('click', () => setHashTab('ipo'));
    $.searchInfo.append(' ', b);
  }

  function renderIpo() {
    const ipo = (state.meta && state.meta.ipo) || [];
    const win = (state.meta && state.meta.window) || 26;
    const q = ($.searchInput.value || '').trim().toLowerCase();
    const shown = ipoMatches(ipo, q);
    $.searchInfo.textContent = q ? `${shown.length} of ${ipo.length} new listing(s)` : '';
    if (!ipo.length) {
      $.content.innerHTML = '<div class="brd-empty">No new listings awaiting ranking right now.</div>';
      return;
    }
    if (!shown.length) {
      $.content.innerHTML = `<div class="brd-empty">No new listings match <code>${utils.esc(q)}</code>.</div>`;
      return;
    }
    // Performance since the listing-day close, ranked vs NIFTY 500 over the
    // same dates: outperformers best-first, underperformers worst-first.
    const pct = v => `<span class="${v > 0 ? 'pos' : (v < 0 ? 'neg' : '')}">${v > 0 ? '+' : ''}${v.toFixed(1)}%</span>`;
    const ranked = (title, list, note) => {
      if (!list.length) return '';
      const rows = list.map((i, k) => `<tr class="ipo-row" data-sym="${utils.esc(i.s)}">
        <td class="tnum ipo-rank">${k + 1}</td>
        <td class="mnm">${utils.esc(i.n)}<span class="msym">${utils.esc(i.s)}</span></td>
        <td class="tnum">${i.first}</td>
        <td class="tnum">${i.days}</td>
        <td class="tnum">${i.base != null ? utils.fmtPrice(i.base) : '—'}</td>
        <td class="tnum">${utils.fmtPrice(i.ltp)}</td>
        <td class="tnum">${i.ret != null ? pct(i.ret) : '—'}</td>
        <td class="tnum">${i.bret != null ? pct(i.bret) : '—'}</td>
        <td class="tnum ipo-x">${i.xret != null ? pct(i.xret) : '—'}</td>
        <td class="tnum"${i.uc ? '' : ` title="${i.days} of ${win} sessions so far — gets a full ${win}-day RS ranking and joins its group's RS index after ${i.eta} more"`}>${i.uc ? 'awaiting NSE classification' : `${i.eta} session${i.eta === 1 ? '' : 's'}`}</td>
      </tr>`).join('');
      return `<div class="ipo-sec">${title} <span>${list.length} · ${note}</span></div>
        <table class="ipo-table"><thead><tr>
          <th>#</th><th>Stock</th><th>Listed</th><th>Days</th><th title="close on the listing day">Listing close</th>
          <th>LTP</th><th title="LTP vs listing-day close">Since listing</th>
          <th title="NIFTY 500 over the same dates">NIFTY 500</th>
          <th title="(1 + stock) / (1 + NIFTY 500) − 1">vs NIFTY 500</th><th title="Trading sessions until the stock has a full ${win}-day window: it then gets a regular RS_STS% ranking, counts in its group's RS index and leaves this tab">Full RS in</th>
        </tr></thead><tbody>${rows}</tbody></table>`;
    };
    const measured = shown.filter(i => i.xret != null);
    const out = measured.filter(i => i.xret >= 0).sort((a, b) => b.xret - a.xret);
    const under = measured.filter(i => i.xret < 0).sort((a, b) => a.xret - b.xret);
    const fresh = shown.filter(i => i.xret == null);
    $.content.innerHTML = `<div class="mbrd-head">New listings — awaiting first ${win}-day ranking
      <span> · ${out.length} of ${measured.length} beating NIFTY 500 since listing · performance from the listing-day close (issue price not in the data) · click a name for its RS chart</span></div>
      ${ranked('Outperformers', out, 'ranked best first')}
      ${ranked('Underperformers', under, 'ranked worst first')}
      ${ranked('Too new to measure', fresh, 'first session only')}`;
    $.content.querySelectorAll('.ipo-row').forEach(r => {
      r.addEventListener('click', () => openStockModal(r.dataset.sym));
    });
  }


  // =========================================================================
  // FOCUS + SWING: decision pages.  The rules live in rs_engine/decide.py —
  // the build computes them once, so the pages, the pick log (track record)
  // and the evening Telegram brief always say the same thing.
  // =========================================================================
  // One record per stock with its macro / sector / industry / basic names.
  function stockIndex() {
    const stocks = new Map();
    for (const g of state.levelData.macro.groups) {
      for (const m of g.members) stocks.set(m.s, { ...m, macro: g.name });
    }
    for (const key of ['sector', 'industry', 'basic']) {
      for (const g of (state.levelData[key] && state.levelData[key].groups) || []) {
        for (const m of g.members) { const st = stocks.get(m.s); if (st) st[key] = g.name; }
      }
    }
    return [...stocks.values()];
  }

  async function loadDecisionData() {
    for (const lv of state.levels) {
      if (!state.levelData[lv.key] || state.levelData[lv.key]._error) {
        state.levelData[lv.key] = await api.level(lv.key);
      }
    }
    if (!state.decide) state.decide = await api.decide();
    if (!state.track) {
      try { state.track = await api.track(); } catch (e) { state.track = {}; }
    }
  }

  const sgn = (v, dp = 1) => v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(dp)}%`;
  const tone = (v, dp = 1) => v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${sgn(v, dp)}</span>`;
  const pctTxt = v => v == null ? '—' : `${v.toFixed(0)}%`;

  const REGIME = {
    on: { word: 'Risk-on', line: 'trend and breadth agree — normal size, act on breakouts in the leading groups.',
      size: 'Exposure 75–100% · risk ~1% of capital per trade · 4–6 positions' },
    mixed: { word: 'Mixed', line: 'signals disagree — be selective: half size, only the best setups in leading groups, book profits sooner.',
      size: 'Exposure 25–50% · risk ~0.5% per trade · 2–3 positions' },
    off: { word: 'Risk-off', line: 'trend and breadth are weak — protect capital: mostly cash, small pilot positions only.',
      size: 'Exposure 0–20% · risk ≤0.5% per trade · pilots only' },
  };
  const QUAD_TIP = {
    Leading: 'beating the average stock over 1M and 3M',
    Improving: 'behind over 3M but beating the average stock over 1M — turning up',
    Weakening: 'ahead over 3M but lagging over 1M — losing steam',
    Lagging: 'behind the average stock over 1M and 3M',
  };
  const quadTag = q => `<span class="dc-q q-${q.toLowerCase()}" title="${QUAD_TIP[q]}">${q}</span>`;

  const asOfText = () => {
    const d = ((state.meta && state.meta.drange) || '').split('→').pop().trim();
    if (!/^\d{4}-\d\d-\d\d$/.test(d)) return '';
    const [y, m, dd] = d.split('-');
    return `${+dd} ${MON[+m - 1]} ${y}`;
  };
  const stockLink = m => `<button type="button" class="dc-stk" data-sym="${utils.esc(m.s)}" title="${utils.esc(m.n || m.s)}">${utils.esc(m.s)}</button>`;
  const bindStockLinks = () => $.content.querySelectorAll('[data-sym]').forEach(el =>
    el.addEventListener('click', () => openStockModal(el.dataset.sym)));
  const decisionError = e => {
    $.content.innerHTML = `<div class="brd-empty">Failed to load data: ${utils.esc(e.message)}</div>`;
  };
  const noDecisions = () => {
    $.content.innerHTML = '<div class="brd-empty">No Focus / Swing data yet — run a build (<code>build_rs.py</code>).</div>';
  };

  // ---- track record ---------------------------------------------------------
  const HZ = ['5', '10', '20'];
  // one stat cell: average edge + how often the call was right
  const edgeCell = (e, hitWord) => !e ? '<td class="tnum">—</td>'
    : `<td class="tnum">${tone(e.avg * 100, 1)}<span class="dc-hit">${(e.hit * 100).toFixed(0)}% ${hitWord}</span></td>`;
  const listCell = l => !l ? '<td class="tnum">—</td>'
    : `<td class="tnum">${tone(l.ex * 100, 1)}<span class="dc-hit">${(l.hit * 100).toFixed(0)}% beat N500</span></td>`;
  function trackIntro(t) {
    if (!t || !t.n) return '';
    const fmt = d => { const [y, m, dd] = d.split('-'); return `${+dd} ${MON[+m - 1]} ${y}`; };
    return `<div class="dc-note">${t.n} sessions of calls since ${fmt(t.since)}${t.live_since
      ? ` (logged live since ${fmt(t.live_since)}; earlier days rebuilt from price history with the same rules)`
      : ' — rebuilt from price history with the same rules; live logging adds a day every build'}.
      Results use the next 5 / 10 / 20 sessions. Days overlap, so treat hit rates as a guide, not proof.</div>`;
  }
  function focusTrack(t) {
    const s = t && t.summary;
    if (!s || !Object.keys(s).length) return '<div class="dc-empty">The first results appear 5 sessions after the first logged call.</div>';
    const row = (label, key, word, tip) => `<tr><td title="${tip}">${label}</td>${HZ.map(h => edgeCell(s[h] && s[h][key], word)).join('')}</tr>`;
    const recent = (t.rows || []).slice(0, 12).map(r => {
      const x = r.h['10'] || r.h['5'];
      const which = r.h['10'] ? '10' : r.h['5'] ? '5' : '';
      return `<tr><td>${r.date}${r.bt ? '' : ' <span class="dc-live">live</span>'}</td>
        <td><span class="dc-q ${r.regime === 'on' ? 'q-leading' : r.regime === 'mixed' ? 'q-weakening' : 'q-lagging'}">${REGIME[r.regime].word}</span></td>
        <td class="dc-ind">${utils.esc(r.focus.join(', '))}</td><td>${utils.esc(CAP_LABEL[r.cap] || r.cap || '—')}</td>
        <td class="tnum">${x && x.focus != null ? tone(x.focus * 100) : '<span class="dc-muted">pending</span>'}${which ? `<span class="dc-hit">${which}d</span>` : ''}</td></tr>`;
    }).join('');
    return `${trackIntro(t)}
      <div class="scan-table-wrap"><table class="scan-table dc-table dc-track">
        <thead><tr><th>Call</th><th>5 sessions</th><th>10 sessions</th><th>20 sessions</th></tr></thead>
        <tbody>${row('Focus sectors vs the average stock', 'focus', 'of days ahead', 'average return of the focus sectors’ stocks minus the average stock')}
          ${row('Avoid sectors trailed the average stock by', 'avoid', 'of days right', 'average stock minus the avoid sectors’ stocks — positive = the avoid call was right')}
          ${row('Size pick vs the average stock', 'cap', 'of days ahead', 'the picked size class minus the average stock')}</tbody></table></div>
      <h3 class="dc-h3b">Recent calls</h3>
      <div class="scan-table-wrap"><table class="scan-table dc-table dc-track">
        <thead><tr><th>Date</th><th>Market</th><th>Focus sectors</th><th>Size</th><th title="focus sectors vs the average stock over the next 10 sessions (5 when 10 aren't in yet)">Result</th></tr></thead>
        <tbody>${recent}</tbody></table></div>`;
  }
  function swingTrack(t) {
    const s = t && t.summary;
    if (!s || !Object.keys(s).length) return '<div class="dc-empty">The first results appear 5 sessions after the first logged call.</div>';
    const reg = h => {
      const r = s[h] && s[h].regime;
      if (!r) return '<td>—</td>';
      return `<td class="dc-reg">${['on', 'mixed', 'off'].filter(k => r[k]).map(k =>
        `<div>${REGIME[k].word} ${tone(r[k].nifty * 100)} <i>${(r[k].up * 100).toFixed(0)}% up · ${r[k].n}d</i></div>`).join('')}</td>`;
    };
    const brkReg = h => {
      const r = s[h] && s[h].brk_regime;
      if (!r) return '<td>—</td>';
      return `<td class="dc-reg">${['on', 'mixed', 'off'].filter(k => r[k]).map(k =>
        `<div>${REGIME[k].word} ${tone(r[k].ex * 100)} <i>${(r[k].hit * 100).toFixed(0)}% beat · ${r[k].n}d</i></div>`).join('')}</td>`;
    };
    return `${trackIntro(t)}
      <div class="scan-table-wrap"><table class="scan-table dc-table dc-track">
        <thead><tr><th>Call</th><th>5 sessions</th><th>10 sessions</th><th>20 sessions</th></tr></thead>
        <tbody><tr><td title="average return of the day's top 25 breakout candidates minus NIFTY 500">Breakout watch vs NIFTY 500</td>${HZ.map(h => listCell(s[h] && s[h].brk)).join('')}</tr>
          <tr><td title="average return of the day's top 15 pullback candidates minus NIFTY 500">Pullbacks vs NIFTY 500</td>${HZ.map(h => listCell(s[h] && s[h].pb)).join('')}</tr>
          <tr><td title="average return of the day's top 15 IPO bases minus NIFTY 500">IPO bases vs NIFTY 500</td>${HZ.map(h => listCell(s[h] && s[h].ipo)).join('')}</tr>
          <tr><td title="breakout watch vs NIFTY 500, split by the market regime on the day of the call">Breakouts by regime</td>${HZ.map(brkReg).join('')}</tr>
          <tr><td title="NIFTY 500's average return after days with each regime reading">NIFTY 500 after each regime</td>${HZ.map(reg).join('')}</tr></tbody></table></div>
      <div class="dc-note">Lists are bought at that day's close and held, without stops or costs — the raw edge of the screen, not a trading result.</div>`;
  }

  // ---- FOCUS: one answer + one-liners --------------------------------------
  async function renderFocus() {
    try { await loadDecisionData(); } catch (e) { return decisionError(e); }
    const D = state.decide;
    if (!D || !D.sectors || !D.sectors.length) return noDecisions();
    const reg = D.regime, R = REGIME[reg.level], base = D.base || {};
    const sec = Object.fromEntries(D.sectors.map(r => [r.name, r]));
    const byS = new Map(stockIndex().map(m => [m.s, m]));
    const focus = D.focus.map(n => sec[n]).filter(Boolean);
    const turning = D.turning.map(n => sec[n]).filter(Boolean);
    const avoid = D.avoid.map(n => sec[n]).filter(Boolean);
    const capTop = D.caps.find(r => r.name === D.cap);
    const capName = k => CAP_LABEL[k] || k;
    const line = r => `median stock ${sgn(r.m1)} in 1M and ${sgn(r.m3)} in 3M (all stocks ${sgn(base.m1)} / ${sgn(base.m3)}) · `
      + `${pctTxt(r.p50)} above the 50-day EMA · ${r.lead} leader${r.lead === 1 ? '' : 's'} (RS ≥ 80)`;
    const secRow = (r, extra) => `<div class="dc-row">
        <div class="dc-row-h"><b>${utils.esc(r.name)}</b>${quadTag(r.quad)}<span class="dc-score" title="composite score vs other sectors (0-100)">${r.score.toFixed(0)}</span></div>
        <div class="dc-line">${line(r)}</div>${extra || ''}</div>`;
    const focusRows = focus.map(r => {
      const ind = r.inds || [], ld = (r.leaders || []).map(s => byS.get(s) || { s });
      return secRow(r, `<div class="dc-sub">${ind.length ? `Strongest industries: ${ind.map(utils.esc).join(', ')}` : ''}${ld.length ? `${ind.length ? ' · ' : ''}Leaders: ${ld.map(stockLink).join(' ')}` : ''}</div>`);
    }).join('');
    const capRows = D.caps.map((r, i) => `<div class="dc-row">
        <div class="dc-row-h"><b>${capName(r.name)}</b><span class="dc-q ${i === 0 ? 'q-leading' : i === 1 ? 'q-improving' : 'q-lagging'}">${i === 0 ? 'Focus' : i === 1 ? 'Next best' : 'Lighter'}</span><span class="dc-score">${r.score.toFixed(0)}</span></div>
        <div class="dc-line">median ${sgn(r.w1)} 1W · ${sgn(r.m1)} 1M · ${sgn(r.m3)} 3M · ${pctTxt(r.p50)} above 50-EMA · ${pctTxt(r.nearHi)} within 10% of a 52-week high</div></div>`).join('');
    const names = focus.map(r => `<b>${utils.esc(r.name)}</b>`);
    const answer = `Focus on ${names.length > 1 ? names.slice(0, -1).join(', ') + (names.length > 2 ? ', and ' : ' and ') + names[names.length - 1] : names[0]}`
      + (capTop ? `, in <b>${capName(capTop.name).toLowerCase()}s</b>` : '');
    $.content.innerHTML = `<div class="scan-card dc">
      <div class="scan-head"><div><div class="scan-title">Where to focus next</div>
        <div class="scan-sub">one answer from RS, momentum, participation and breadth · as of ${asOfText()}</div></div></div>
      <div class="dc-body">
        <div class="dc-answer"><span class="dc-dot r-${reg.level}"></span><div>
          <div class="dc-answer-t">${answer}.</div>
          <div class="dc-answer-s">Market: <b class="r-${reg.level}-t">${R.word}</b> (${reg.pass} of ${reg.known} checks) — ${R.line}</div></div></div>
        <ul class="dc-bullets">
          <li><b>Sectors:</b> ${focus.map(r => `${utils.esc(r.name)} (${r.quad.toLowerCase()})`).join(', ')} lead on combined strength.</li>
          ${turning.length ? `<li><b>Turning up:</b> ${turning.map(r => `${utils.esc(r.name)} (${sgn(r.rel1)} vs the average stock in 1M)`).join(', ')} — early, watch for follow-through.</li>` : ''}
          ${capTop ? `<li><b>Size:</b> ${capName(capTop.name)} is strongest — median ${sgn(capTop.m1)} in 1M, ${pctTxt(capTop.p50)} above the 50-day EMA.</li>` : ''}
          ${avoid.length ? `<li><b>Avoid for now:</b> ${avoid.map(r => utils.esc(r.name)).join(', ')}.</li>` : ''}
        </ul>
        <div class="dc-grid">
          <section><h3>Sectors to focus</h3>${focusRows}</section>
          <section><h3>Market cap</h3>${capRows}</section>
          ${turning.length ? `<section><h3>Turning up — watch next</h3>${turning.map(r => secRow(r)).join('')}</section>` : ''}
          ${avoid.length ? `<section><h3>Avoid for now</h3>${avoid.map(r => secRow(r)).join('')}</section>` : ''}
        </div>
        <section class="dc-wide"><h3>Track record — did these calls work?</h3>${focusTrack(state.track)}</section>
        <div class="dc-foot">How it's decided: sectors with ≥ 5 stocks are ranked on 1M (30%) and 3M (20%) median return vs the average stock,
          share above the 50-day EMA (20%), share of RS ≥ 80 leaders (15%) and the group's RS_STS% (15%).
          Leading / Improving / Weakening / Lagging compare 3M and 1M with the average stock. Size classes are ranked the same way.
          Not investment advice.</div>
      </div></div>`;
    bindStockLinks();
  }

  // ---- SWING: what I'd check every evening ----------------------------------
  const TAG_WORD = { tight: 'Tight', dry: 'Vol dry-up', surge: 'Vol surge', dhi: 'High delivery', dlo: 'Weak delivery' };
  const TAG_TIP = {
    tight: '10-day range within 2.5 average daily ranges — a quiet base (ranked higher)',
    dry: '10-day volume below 85% of the prior 50 days — sellers drying up (ranked higher)',
    surge: 'today’s volume ≥ 1.5× average — buying this close is chasing; wait for a pause (ranked lower)',
    dhi: '20-day average delivery ≥ 50% — steady buying into demat (breakouts ranked higher)',
    dlo: 'today’s delivery below 80% of its average — more intraday churn than buying (breakouts ranked lower)',
  };
  // upcoming event within 14 days: results get the loud badge (gap risk)
  function evBadge(ev) {
    if (!ev) return '';
    const [d, ...rest] = ev.split(' ');
    const what = rest.join(' ');
    const [, mo, dd] = d.split('-');
    const res = /\bResults\b/.test(what);
    return ` <span class="dc-ev${res ? ' res' : ''}" title="${utils.esc(what)} on ${d} — ${res ? 'results can gap the stock past any stop: avoid holding through them' : 'corporate event'}">${res ? '⚠ ' : ''}${utils.esc(what.split(',')[0])} ${+dd} ${MON[+mo - 1]}</span>`;
  }
  async function renderSwing() {
    try { await loadDecisionData(); } catch (e) { return decisionError(e); }
    const D = state.decide;
    if (!D || !D.regime) return noDecisions();
    const reg = D.regime, R = REGIME[reg.level], S = D.rules;
    const byS = new Map(stockIndex().map(m => [m.s, m]));
    const hot = new Set(D.hot || []);
    const inLead = m => hot.has(m.industry) || hot.has(m.sector);
    const pick = syms => syms.map(s => byS.get(s)).filter(Boolean);
    const breakouts = pick(D.breakouts), pullbacks = pick(D.pullbacks), extended = pick(D.extended);
    const ipos = pick(D.ipos || []), IR = D.ipo_rules || {};
    const ind = Object.fromEntries(D.industries.map(r => [r.name, r]));
    const leadInd = D.lead_ind.map(n => ind[n]).filter(Boolean);

    const table = (list, max, empty) => list.length ? `<div class="scan-table-wrap"><table class="scan-table dc-table">
      <thead><tr><th>#</th><th>Stock</th><th>Industry</th><th>Price</th>
        <th title="RS rating 1-99 vs all stocks">RS</th><th>1W</th><th>1M</th>
        <th title="% below the 52-week high">Off high</th><th title="average daily range, 20 days — size the stop with it">ADR</th>
        <th title="average daily traded value, 20 sessions">₹ cr/day</th>
        <th title="10-session high-low range as % of price — small = a tight base">10d range</th>
        <th title="today's volume ÷ its 50-session average">Vol ×</th>
        <th title="delivery % today (20-session average) — share of traded quantity taken into demat">Deliv</th><th>Setup</th></tr></thead>
      <tbody>${list.slice(0, max).map((m, i) => `<tr class="dc-tr" data-sym="${utils.esc(m.s)}">
        <td class="tnum">${i + 1}</td>
        <td class="dc-nm">${utils.esc(m.n.replace(/\s+(Limited|Ltd\.?)$/i, ''))}<span class="msym">${utils.esc(m.s)} · ${utils.esc((CAP_LABEL[m.cap] || '').replace(' cap', ''))}${evBadge(m.ev)}</span></td>
        <td class="dc-ind">${inLead(m) ? '<span class="dc-hot" title="in a leading industry / sector">●</span>' : ''}${utils.esc(m.industry || '')}</td>
        <td class="tnum">${utils.fmtPrice(m.l)}</td>
        <td class="tnum"><b>${m.rr ?? '—'}</b></td>
        <td class="tnum">${tone(m.w1)}</td><td class="tnum">${tone(m.m1)}</td>
        <td class="tnum">${m.h == null ? '—' : m.h.toFixed(1) + '%'}</td>
        <td class="tnum">${m.a == null ? '—' : m.a.toFixed(1) + '%'}</td>
        <td class="tnum">${m.tv == null ? '—' : m.tv.toFixed(0)}</td>
        <td class="tnum">${m.tt == null ? '—' : m.tt.toFixed(1) + '%'}</td>
        <td class="tnum">${m.vr == null ? '—' : m.vr.toFixed(1) + '×'}</td>
        <td class="tnum">${m.dl == null ? '—' : `${m.dl.toFixed(0)}%<span class="dc-sub2">${m.dla == null ? '' : m.dla.toFixed(0) + '% avg'}</span>`}</td>
        <td>${((D.tags || {})[m.s] || []).map(t => `<span class="dc-tag t-${t}" title="${TAG_TIP[t]}">${TAG_WORD[t]}</span>`).join('')}</td></tr>`).join('')}</tbody></table></div>`
      : `<div class="dc-empty">${empty}</div>`;

    const fmtDay = d => { const [, mo, dd] = d.split('-'); return `${+dd} ${MON[+mo - 1]}`; };
    const tagCell = m => ((D.tags || {})[m.s] || []).map(t => `<span class="dc-tag t-${t}" title="${TAG_TIP[t]}">${TAG_WORD[t]}</span>`).join('');
    const ipoTable = list => list.length ? `<div class="scan-table-wrap"><table class="scan-table dc-table">
      <thead><tr><th>#</th><th>Stock</th><th>Industry</th><th title="listing day · market sessions since">Listed</th>
        <th title="IPO issue price, adjusted for any later split / bonus">Issue</th><th>Price</th><th title="% above the issue price">vs issue</th>
        <th title="out-/under-performance vs NIFTY 500 since the listing-day close">vs N500</th><th>1W</th>
        <th title="% below the highest intraday price since listing">Off high</th><th title="average daily range, 20 days">ADR</th>
        <th title="average daily traded value, 20 sessions">₹ cr/day</th>
        <th title="10-session high-low range as % of price — small = a tight base">10d range</th><th>Setup</th></tr></thead>
      <tbody>${list.slice(0, 15).map((m, i) => `<tr class="dc-tr" data-sym="${utils.esc(m.s)}">
        <td class="tnum">${i + 1}</td>
        <td class="dc-nm">${utils.esc(m.n.replace(/\s+(Limited|Ltd\.?)$/i, ''))}<span class="msym">${utils.esc(m.s)}${evBadge(m.ev)}</span></td>
        <td class="dc-ind">${inLead(m) ? '<span class="dc-hot" title="in a leading industry / sector">●</span>' : ''}${utils.esc(m.industry || '')}</td>
        <td class="tnum">${fmtDay(m.ipo.d)}<span class="dc-sub2">${m.ipo.n} sessions</span></td>
        <td class="tnum">${m.ipo.p == null ? '—' : utils.fmtPrice(m.ipo.p)}</td>
        <td class="tnum">${utils.fmtPrice(m.l)}</td>
        <td class="tnum">${tone(m.ipo.g, 0)}</td><td class="tnum">${tone(m.ipo.x, 0)}</td>
        <td class="tnum">${tone(m.w1)}</td>
        <td class="tnum">${m.h == null ? '—' : m.h.toFixed(1) + '%'}</td>
        <td class="tnum">${m.a == null ? '—' : m.a.toFixed(1) + '%'}</td>
        <td class="tnum">${m.tv == null ? '—' : m.tv.toFixed(0)}</td>
        <td class="tnum">${m.tt == null ? '—' : m.tt.toFixed(1) + '%'}</td>
        <td>${tagCell(m)}</td></tr>`).join('')}</tbody></table></div>`
      : '<div class="dc-empty">No recent IPO is basing near its high right now.</div>';
    const checks = reg.checks.map(c => `<li class="${c.ok === null ? 'na' : c.ok ? 'ok' : 'no'}">
        <span class="dc-ck">${c.ok === null ? '–' : c.ok ? '✓' : '✗'}</span>${c.t}<span class="dc-cv">${utils.esc(c.v)}</span></li>`).join('');
    const indRows = leadInd.map(r => `<div class="dc-ind-row"><b>${utils.esc(r.name)}</b>
        <span class="dc-muted">${utils.esc(r.sector)}</span>${quadTag(r.quad)}
        <span class="dc-line">${sgn(r.m1)} 1M · ${pctTxt(r.p50)} > 50-EMA · ${r.lead} leaders</span></div>`).join('');
    const ext = extended.map(m => `${stockLink(m)} <span class="dc-muted">${sgn(m.w1, 0)} 1W</span>`).join(' · ');
    let sec = 6;
    $.content.innerHTML = `<div class="scan-card dc">
      <div class="scan-head"><div><div class="scan-title">Swing-trading desk</div>
        <div class="scan-sub">what I would check every evening before the next session · as of ${asOfText()}</div></div></div>
      <div class="dc-body">
        <div class="dc-answer"><span class="dc-dot r-${reg.level}"></span><div>
          <div class="dc-answer-t">Market: <b class="r-${reg.level}-t">${R.word}</b> — ${reg.pass} of ${reg.known} checks pass.</div>
          <div class="dc-answer-s">${R.size}. ${R.line.charAt(0).toUpperCase() + R.line.slice(1)}</div></div></div>
        <div class="dc-grid">
          <section><h3>1 · Market regime checklist</h3><ul class="dc-checks">${checks}</ul></section>
          <section><h3>2 · Leading industries — where setups work best</h3>${indRows || '<div class="dc-empty">No industry is beating the average stock right now.</div>'}</section>
        </div>
        <section class="dc-wide"><h3>3 · Breakout watch — leaders near their highs <span class="dc-muted">${breakouts.length} stocks</span></h3>
          <div class="dc-note">RS ≥ ${S.minRS}, above the 20/50/100/150/200-day EMAs, RS line above its 21-EMA, within ${S.maxOffHigh}% of the 52-week high,
            ADR ${S.minAdr}–${S.maxAdr}%, ≥ ₹${S.minTurnoverCr} cr/day, not up > ${S.maxWeek}% this week or > ${S.maxMonth}% this month. ● = in a leading group (ranked first).
            Buy only on a breakout from a tight range on rising volume; stop under the range low (≈ 1 ADR).
            Ranked higher when the 10-day range is <b>tight</b>, volume is <b>drying up</b> and delivery is steadily high; a volume-surge or weak-delivery day ranks lower
            (in the backtest buying that close lagged). <span class="dc-ev res">⚠ Results</span> = reports within 14 days — don't hold through it.</div>
          ${table(breakouts, 25, 'No stock passes the breakout filter today — that itself says: stay patient.')}</section>
        <section class="dc-wide"><h3>4 · Pullbacks in leaders — lower-risk entries <span class="dc-muted">${pullbacks.length} stocks</span></h3>
          <div class="dc-note">RS ≥ ${S.pbMinRS}, above the 50 and 200-day EMAs but back below the 20-day, ${S.pbOffHigh[0]}–${S.pbOffHigh[1]}% off the high.
            Enter when it turns back up (reclaims the prior day's high / the 20-EMA); stop under the pullback low.</div>
          ${table(pullbacks, 15, 'No leader is pulling back in an orderly way right now.')}</section>
        <section class="dc-wide"><h3>5 · IPO bases — new listings near their highs <span class="dc-muted">${ipos.length} stocks</span></h3>
          <div class="dc-note">Mainboard IPOs ${IR.minAge}–${IR.maxAge} sessions old — too young for an RS rating or a 200-day EMA, so the breakout watch can't see them.
            Above the issue price, ahead of NIFTY 500 since the listing day, above every EMA it has, within ${IR.maxOffHigh}% of the high since listing,
            ADR ${IR.minAdr}–${IR.maxAdr}%, ≥ ₹${S.minTurnoverCr} cr/day, not up > ${IR.maxWeek}% this week.
            The classic entry is a breakout above the post-listing high after a few quiet weeks; stop under the base low. Young stocks move fast — size smaller.</div>
          ${ipoTable(ipos)}</section>
        ${extended.length ? `<section class="dc-wide"><h3>${sec++} · Don't chase — extended leaders</h3>
          <div class="dc-note">Up > 20% in a week or > ${S.maxMonth}% in a month: wait for a base or a pullback.</div>
          <div class="dc-chips">${ext}</div></section>` : ''}
        <section class="dc-wide"><h3>${sec++} · Track record — does the screen work?</h3>${swingTrack(state.track)}</section>
        <section class="dc-wide"><h3>${sec++} · Rules I'd trade by</h3>
          <ul class="dc-rules">
            <li><b>Regime first:</b> size follows the checklist above — cut size when it turns Mixed, mostly cash when Risk-off.</li>
            <li><b>Risk per trade:</b> decide the stop before entry; lose at most 0.5–1% of capital if it hits. Shares = risk ₹ ÷ (entry − stop).</li>
            <li><b>Stop:</b> below the setup's low, usually ≤ 1× ADR from entry; never widen it.</li>
            <li><b>Profits:</b> sell a third to half at 2–3× risk or after 3–5 strong days; move the stop to breakeven; trail the rest with the 10/20-day EMA.</li>
            <li><b>Leaders only:</b> RS ≥ 80 stocks in leading groups; skip stocks reporting results within the holding period.</li>
            <li><b>Review:</b> if 3–4 breakouts in a row fail, the market is telling you to step back.</li>
          </ul></section>
        <div class="dc-foot">Screens use the latest close; levels are a starting point for your own chart review, not investment advice.
          Click a stock for its RS chart.</div>
      </div></div>`;
    bindStockLinks();
  }

  // =========================================================================
  // FII / DII: monthly net cash-market flows (NSE provisional, ₹ crore)
  // =========================================================================
  const FLOW_RANGES = { '1Y': 12, '3Y': 36, '5Y': 60, 'All': 0 };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const monLabel = m => `${MON[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
  const crore = v => `${v >= 0 ? '+' : '−'}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`;
  const croreCell = v => `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : '−'}${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>`;
  // axis ticks in lakh / thousand crore: 1,00,000 cr = 1L
  const axisCr = v => v === 0 ? '0' : (Math.abs(v) >= 1e5
    ? `${v < 0 ? '−' : ''}${+(Math.abs(v) / 1e5).toFixed(1)}L` : `${v < 0 ? '−' : ''}${+(Math.abs(v) / 1e3).toFixed(0)}k`);

  function renderFlows() {
    if (state.flowsData) return drawFlows(state.flowsData);
    api.flows().then(d => { state.flowsData = d; drawFlows(d); }).catch(e => {
      $.content.innerHTML = `<div class="brd-empty">Failed to load FII / DII data: ${utils.esc(e.message)}</div>`;
    });
  }

  function niceStep(span) {
    const raw = span / 5, p = Math.pow(10, Math.floor(Math.log10(raw)));
    return [1, 2, 2.5, 5, 10].map(k => k * p).find(s => s >= raw);
  }

  function flowChartSVG(rows, W) {
    const H = 300, L = 46, R = 8, T = 12, B = 30;
    const vals = rows.flatMap(r => [r.fii, r.dii]);
    const step = niceStep(Math.max(1, Math.max(...vals, 0) - Math.min(...vals, 0)));
    const hi = Math.ceil(Math.max(...vals, 0) / step) * step;
    const lo = Math.floor(Math.min(...vals, 0) / step) * step;
    const y = v => T + (hi - v) / (hi - lo || 1) * (H - T - B);
    const slot = (W - L - R) / rows.length;
    const gap = Math.min(2, slot * 0.08);                     // surface gap between the pair
    const bw = Math.max(1, Math.min(14, (slot * 0.72 - gap) / 2));
    const grid = [];
    for (let v = lo; v <= hi + 1e-6; v += step) {
      grid.push(`<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="${v === 0 ? 'fl-zero' : 'fl-grid'}"/>
        <text x="${L - 6}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" class="fl-ax">${axisCr(v)}</text>`);
    }
    // x labels: every month when they fit, else every quarter / January
    const every = slot >= 34 ? 1 : slot >= 11 ? 3 : 12;
    const bar = (v, x, cls) => {
      const y0 = y(0), y1 = y(v), h = Math.max(1, Math.abs(y1 - y0)), r = Math.min(4, bw / 2, h);
      // rounded data end, square at the zero baseline
      const top = v >= 0 ? y1 : y0, bot = v >= 0 ? y0 : y1;
      const d = v >= 0
        ? `M${x},${bot}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${bot}Z`
        : `M${x},${top}V${bot - r}Q${x},${bot} ${x + r},${bot}H${x + bw - r}Q${x + bw},${bot} ${x + bw},${bot - r}V${top}Z`;
      return `<path d="${d}" class="${cls}"/>`;
    };
    const bars = rows.map((r, i) => {
      const cx = L + slot * i + slot / 2, x1 = cx - gap / 2 - bw, x2 = cx + gap / 2;
      const mtd = r.to && r.to.slice(0, 7) === r.m && i === rows.length - 1 ? ' fl-mtd' : '';
      const lbl = (+r.m.slice(5, 7) - 1) % every === 0 || every === 1
        ? `<text x="${cx.toFixed(1)}" y="${H - B + 16}" text-anchor="middle" class="fl-ax">${every === 12 ? r.m.slice(0, 4) : every === 3 && r.m.slice(5, 7) !== '01' ? MON[+r.m.slice(5, 7) - 1] : monLabel(r.m).replace(' 20', " '")}</text>` : '';
      return `<g class="fl-col${mtd}" data-i="${i}">
        <rect x="${(L + slot * i).toFixed(1)}" y="${T}" width="${slot.toFixed(1)}" height="${H - T - B}" class="fl-hit"/>
        ${bar(r.fii, x1, 'fl-fii')}${bar(r.dii, x2, 'fl-dii')}${lbl}</g>`;
    }).join('');
    return `<svg class="fl-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Monthly FII and DII net cash flows, ${monLabel(rows[0].m)} to ${monLabel(rows[rows.length - 1].m)}">
      ${grid.join('')}${bars}</svg>`;
  }

  function drawFlows(data) {
    const all = data.months || [];
    if (!all.length) {
      $.content.innerHTML = '<div class="brd-empty">No FII / DII data yet — run <code>refresh_flows.py</code> and a build.</div>';
      return;
    }
    const n = FLOW_RANGES[state.flowRange];
    const rows = n ? all.slice(-n) : all;
    const last = all[all.length - 1];
    const fmtD = d => { const [y, m, dd] = d.split('-'); return `${+dd} ${MON[+m - 1]} ${y}`; };
    const running = last.to && last.to.slice(0, 7) === last.m;
    const sum = k => rows.reduce((a, r) => a + r[k], 0);
    const table = rows.slice().reverse().map(r => `<tr>
        <td>${monLabel(r.m)}${r === last && running ? ` <span class="fl-to">to ${fmtD(r.to)}</span>` : ''}</td>
        <td class="tnum">${croreCell(r.fii)}</td><td class="tnum">${croreCell(r.dii)}</td>
        <td class="tnum fl-sep">${croreCell(r.fii + r.dii)}</td>
        <td class="tnum fl-gross">${r.fb.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
        <td class="tnum fl-gross">${r.fs.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
        <td class="tnum fl-gross">${r.db.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
        <td class="tnum fl-gross">${r.ds.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td></tr>`).join('');
    $.content.innerHTML = `<div class="scan-card">
      <div class="scan-head">
        <div><div class="scan-title">FII / DII cash flows · monthly net</div>
          <div class="scan-sub">NSE provisional cash market, ₹ crore · ${monLabel(rows[0].m)} – ${monLabel(last.m)}${running ? ` (to ${fmtD(last.to)})` : ''}</div></div>
        <div class="seg">${Object.keys(FLOW_RANGES).map(k => `<button type="button" data-range="${k}" class="${k === state.flowRange ? 'on' : ''}">${k}</button>`).join('')}</div>
      </div>
      <div class="fl-body">
        <div class="fl-legend">
          <span><i class="fl-key fl-fii"></i>FII net <b class="tnum">${crore(sum('fii'))}</b></span>
          <span><i class="fl-key fl-dii"></i>DII net <b class="tnum">${crore(sum('dii'))}</b></span>
          <span class="fl-note">totals over the ${rows.length} months shown</span>
        </div>
        <div class="fl-viz" id="fl-viz"></div>
        <div class="scan-table-wrap"><table class="scan-table fl-table">
          <thead><tr><th>Month</th><th>FII net</th><th>DII net</th><th class="fl-sep">FII + DII</th>
            <th title="FII gross purchase">FII buy</th><th title="FII gross sales">FII sell</th>
            <th title="DII gross purchase">DII buy</th><th title="DII gross sales">DII sell</th></tr></thead>
          <tbody>${table}</tbody></table></div>
      </div>
    </div>`;
    const viz = document.getElementById('fl-viz');
    const paint = () => {
      viz.innerHTML = flowChartSVG(rows, Math.max(300, viz.clientWidth)) + '<div class="scan-tip" id="fl-tip"></div>';
      const tip = document.getElementById('fl-tip');
      viz.querySelectorAll('.fl-col').forEach(g => {
        g.addEventListener('mousemove', ev => {
          const r = rows[+g.dataset.i];
          tip.innerHTML = `<b>${monLabel(r.m)}${r.to && r === last && running ? ` · to ${fmtD(r.to)}` : ''}</b>
            <div><i class="fl-key fl-fii"></i>FII net ${crore(r.fii)}</div>
            <div><i class="fl-key fl-dii"></i>DII net ${crore(r.dii)}</div>
            <div class="fl-tip-sum">Combined ${crore(r.fii + r.dii)}</div>`;
          const box = viz.getBoundingClientRect();
          const x = ev.clientX - box.left, yy = ev.clientY - box.top;
          tip.style.visibility = 'visible';
          tip.style.left = `${x + 14 + tip.offsetWidth > viz.clientWidth ? Math.max(0, x - tip.offsetWidth - 14) : x + 14}px`;
          tip.style.top = `${Math.max(0, yy - tip.offsetHeight - 10)}px`;
        });
        g.addEventListener('mouseleave', () => { tip.style.visibility = 'hidden'; });
      });
    };
    paint();
    state.flowPaint = paint;
    $.content.querySelectorAll('[data-range]').forEach(b => b.addEventListener('click', () => {
      state.flowRange = b.dataset.range;
      drawFlows(data);
    }));
  }

  let flowResize = null;
  window.addEventListener('resize', () => {
    clearTimeout(flowResize);
    flowResize = setTimeout(() => {
      if (state.activeTab === 'flows' && document.getElementById('fl-viz') && state.flowPaint) state.flowPaint();
    }, 150);
  });

  // =========================================================================
  // SCANS: scan summary of the 1-month gainers by sector / sub-industry / size
  // =========================================================================
  // 1-month gainer: up >= 14% over 20 sessions, average daily traded value
  // >= ₹10 crore (20 sessions), price >= ₹100 — the rule that best reproduces
  // the reference scan (12-Nov-2026: 99 stocks, 17 / 17 / 15 / 50 by size).
  const GAINER = { minGain: 14, minTurnoverCr: 10, minPrice: 100 };
  const SCAN_DIMS = [['sector', 'Sector', 'sectors'], ['basic', 'Sub-industry', 'sub-industries'],
    ['cap', 'Market cap', 'sizes']];
  const CAP_ORDER = ['Large', 'Mid', 'Small', 'Micro', 'New'];
  const CAP_LABEL = { Large: 'Large cap', Mid: 'Mid cap', Small: 'Small cap', Micro: 'Micro cap',
    New: 'No market cap' };
  const SCAN_SLOTS = 5;   // coloured donut segments; smaller groups fold into "Other"

  async function renderScans() {
    // a stock's sector / sub-industry comes from those levels' members
    try {
      for (const lv of state.levels) {
        if (!state.levelData[lv.key] || state.levelData[lv.key]._error) {
          state.levelData[lv.key] = await api.level(lv.key);
        }
      }
    } catch (e) {
      $.content.innerHTML = `<div class="brd-empty">Failed to load data: ${utils.esc(e.message)}</div>`;
      return;
    }
    drawScans();
  }

  function median(xs) {
    const v = xs.filter(x => x != null).sort((a, b) => a - b);
    if (!v.length) return null;
    const h = v.length >> 1;
    return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2;
  }

  // Donut of the scan's split: one stroked circle per segment, 2px surface gap
  function scanDonut(segs, total, groupsN, unit) {
    const R = 74, W = 22, C = 2 * Math.PI * R, GAP = 2;
    let off = 0;
    const arcs = segs.map((sg, i) => {
      const len = total ? C * sg.n / total : 0;
      const dash = Math.max(0, len - (segs.length > 1 ? GAP : 0));
      const el = `<circle class="sd-seg" data-i="${i}" r="${R}" cx="100" cy="100" fill="none"
        style="stroke:${sg.color}" stroke-width="${W}" stroke-dasharray="${dash.toFixed(2)} ${(C - dash).toFixed(2)}"
        stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 100 100)"/>`;
      off += len;
      return el;
    }).join('');
    return `<svg class="scan-donut" viewBox="0 0 200 200" role="img"
      aria-label="${total} stocks across ${groupsN} ${unit}">
      <circle r="${R}" cx="100" cy="100" fill="none" class="sd-track" stroke-width="${W}"/>
      ${arcs}
      <text x="100" y="98" text-anchor="middle" class="sd-hero">${total}</text>
      <text x="100" y="122" text-anchor="middle" class="sd-sub">stocks · ${groupsN} ${unit}</text>
    </svg>`;
  }

  function drawScans() {
    const dim = state.scan.dim;
    const all = stockIndex();
    const hits = all.filter(m => m.m1 != null && m.m1 >= GAINER.minGain
      && m.tv != null && m.tv >= GAINER.minTurnoverCr && m.l != null && m.l >= GAINER.minPrice);
    const groupOf = m => (dim === 'cap' ? (m.cap || 'New') : m[dim]);
    const total = new Map(), by = new Map(), members = new Map();
    for (const m of all) {
      const k = groupOf(m);
      if (!k) continue;
      total.set(k, (total.get(k) || 0) + 1);
      if (!members.has(k)) members.set(k, []);
      members.get(k).push(m);
    }
    // whole-group move (every stock in the group, not just the gainers):
    // equal-weight average of the members' 1-day / 1-week changes
    const mean = xs => { const v = xs.filter(x => x != null); return v.length ? v.reduce((a, x) => a + x, 0) / v.length : null; };
    const chg = (v, dp) => v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${v.toFixed(dp)}%</span>`;
    for (const m of hits) {
      const k = groupOf(m);
      if (!k) continue;
      if (!by.has(k)) by.set(k, []);
      by.get(k).push(m);
    }
    const count = k => (by.get(k) || []).length;
    const keys = dim === 'cap'
      ? CAP_ORDER.filter(k => total.has(k))
      : [...by.keys()].sort((a, b) => count(b) - count(a) || a.localeCompare(b));
    // colour follows the entity: fixed per size class; otherwise the largest
    // groups of the list take the first slots and the rest share "Other"
    const OTHER = 'var(--sc-other)';
    const color = {};
    keys.forEach((k, i) => {
      if (dim === 'cap') color[k] = k === 'New' ? OTHER : `var(--sc-${CAP_ORDER.indexOf(k) + 1})`;
      else color[k] = i < SCAN_SLOTS ? `var(--sc-${i + 1})` : OTHER;
    });
    let segs = keys.filter(k => count(k)).map(k => ({ name: dim === 'cap' ? CAP_LABEL[k] : k, n: count(k), color: color[k] }));
    if (dim !== 'cap' && segs.length > SCAN_SLOTS) {
      const rest = segs.slice(SCAN_SLOTS);
      segs = segs.slice(0, SCAN_SLOTS).concat([{ name: `Other (${rest.length})`,
        n: rest.reduce((a, x) => a + x.n, 0), color: OTHER }]);
    }
    const n = hits.length;
    const pctOf = (c, t) => (t ? (c / t * 100).toFixed(c / t < 0.1 ? 1 : 0) : '0.0') + '%';
    const rows = keys.map(k => {
      const list = by.get(k) || [], c = list.length, tot = total.get(k) || 0;
      const share = n ? c / n * 100 : 0;
      const rs = median(list.map(m => m.rr));
      const m3 = median(list.map(m => m.m3));
      const grp = members.get(k) || [];
      const g1d = mean(grp.map(m => m.d1)), g1w = mean(grp.map(m => m.w1));
      return `<tr class="scan-row${c ? '' : ' empty'}">
        <td class="sg-name"><span class="sw" style="background:${c ? color[k] : 'transparent'}"></span>${utils.esc(dim === 'cap' ? CAP_LABEL[k] : k)}</td>
        <td class="tnum sg-n">${c}</td>
        <td class="sg-share"><span class="bar"><span style="width:${share.toFixed(1)}%;background:${color[k]}"></span></span><span class="tnum">${c ? share.toFixed(0) + '%' : '—'}</span></td>
        <td class="tnum sg-of">${c} of ${tot} <span class="muted">(${pctOf(c, tot)})</span></td>
        <td class="tnum">${rs == null ? '—' : Math.round(rs)}</td>
        <td class="tnum">${chg(m3, 0)}</td>
        <td class="tnum sg-grp">${chg(g1d, 2)}</td>
        <td class="tnum">${chg(g1w, 2)}</td>
      </tr>`;
    }).join('');
    const asOf = ((state.meta && state.meta.drange) || '').split('→').pop().trim();   // window end
    const fmtDay = d => { const [y, mo, da] = d.split('-'); return `${+da} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+mo - 1]} ${y}`; };
    const [, label, unit] = SCAN_DIMS.find(d => d[0] === dim);
    const nGroups = keys.filter(k => count(k)).length;
    $.content.innerHTML = `<div class="scan-card">
      <div class="scan-head">
        <div><div class="scan-title">Scan summary · 1-month gainers</div>
          <div class="scan-sub">${n} stocks · as of ${/^\d{4}-\d\d-\d\d$/.test(asOf) ? fmtDay(asOf) : '—'}</div></div>
        <div class="seg">${SCAN_DIMS.map(([k, v]) => `<button type="button" data-dim="${k}" class="${k === dim ? 'on' : ''}">${v}</button>`).join('')}</div>
      </div>
      <div class="scan-body">
        <div class="scan-viz">${scanDonut(segs, n, nGroups, unit)}<div class="mtip scan-tip" id="scan-tip"></div></div>
        <div class="scan-table-wrap"><table class="scan-table">
          <thead><tr><th>${dim === 'cap' ? 'Size' : label}</th><th>Stocks</th><th>Share of list</th>
            <th>Of the group</th><th title="median RS rating (1-99)">RS</th><th title="median 3-month return">3M</th>
            <th class="sg-grp" title="whole group: average 1-day change of all its stocks (not just the gainers)">Group 1D</th>
            <th title="whole group: average 1-week (5-session) change of all its stocks (not just the gainers)">Group 1W</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="8" class="brd-empty">No 1-month gainers today.</td></tr>'}</tbody>
        </table></div>
      </div>
    </div>`;

    $.content.querySelectorAll('[data-dim]').forEach(b => b.addEventListener('click', () => {
      state.scan.dim = b.dataset.dim;
      drawScans();
    }));
    const tip = $.content.querySelector('#scan-tip');
    $.content.querySelectorAll('.sd-seg').forEach(c => {
      c.addEventListener('mousemove', ev => {
        const sg = segs[+c.dataset.i];
        tip.innerHTML = `<b>${utils.esc(sg.name)}</b>${sg.n} stock${sg.n === 1 ? '' : 's'} · ${(sg.n / n * 100).toFixed(0)}%`;
        const box = c.ownerSVGElement.parentNode.getBoundingClientRect();
        tip.style.left = (ev.clientX - box.left + 12) + 'px';
        tip.style.top = (ev.clientY - box.top - 10) + 'px';
        tip.style.visibility = 'visible';
      });
      c.addEventListener('mouseleave', () => { tip.style.visibility = 'hidden'; });
    });
  }

  // ---- Stock RS line chart (TradingView-style: ratio + EMA21) ----
  function lineChartSVG(vals, ema, uid, W, H) {
    const L = 8, R = 52, T = 10, B = 14;
    const ph = H - T - B, pw = W - L - R;
    const step = 1;   // every session is drawn and hoverable (no downsampling)
    const idx = [];
    for (let k = 0; k < vals.length; k += step) idx.push(k);
    if (idx[idx.length - 1] !== vals.length - 1) idx.push(vals.length - 1);
    const v = idx.map(k => vals[k]);
    const e = ema ? idx.map(k => ema[k]) : null;
    const all = e ? v.concat(e) : v;
    const lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.02 || 0.01;
    const y0 = lo - pad, y1 = hi + pad;
    const n = v.length;
    const X = k => L + pw * k / (n - 1);
    const Y = x => T + ph * (1 - (x - y0) / (y1 - y0));
    const seg = (arr, col, w) =>       // one polyline: cheap even for ~550 points
      `<polyline fill="none" stroke="${col}" stroke-width="${w}" stroke-linejoin="round" points="${arr.map((y, k) => `${X(k).toFixed(1)},${Y(y).toFixed(1)}`).join(' ')}"/>`;
    const blue = state.theme === 'dark' ? '#60a5fa' : '#2563eb';
    const amber = state.theme === 'dark' ? '#fbbf24' : '#b45309';
    const muted = state.theme === 'dark' ? '#9ca3af' : '#7a8794';
    const p = [];
    if (y0 < 1 && y1 > 1) {
      p.push(`<line x1="${L}" y1="${Y(1).toFixed(1)}" x2="${L + pw}" y2="${Y(1).toFixed(1)}" stroke="${muted}" stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>`);
    }
    p.push(seg(v, blue, 1.5));
    if (e) p.push(seg(e, amber, 1.2));
    p.push(`<text x="${L + pw + 4}" y="${Y(y1) + 3}" font-size="9" fill="${muted}">${y1.toFixed(2)}</text>`);
    p.push(`<text x="${L + pw + 4}" y="${Y(y0) + 3}" font-size="9" fill="${muted}">${y0.toFixed(2)}</text>`);
    p.push(`<line id="${uid}-cross" x1="0" y1="${T}" x2="0" y2="${T + ph}" stroke="${muted}" stroke-width="1" stroke-dasharray="3 3" style="visibility:hidden"/>`);
    p.push(`<circle id="${uid}-dot" r="3" fill="${state.theme === 'dark' ? '#e8eaf0' : '#111'}" style="visibility:hidden"/>`);
    return `<svg id="${uid}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="mbrd-svg"
      data-step="${step}" data-n="${vals.length}">${p.join('')}</svg>`;
  }

  function bindLineChart(uid, dates, vals, ema, tip) {
    const svg = document.getElementById(uid);
    if (!svg || !tip) return;
    const W = +svg.getAttribute('width'), H = +svg.getAttribute('height');
    const step = +svg.dataset.step, n0 = +svg.dataset.n;
    const L = 8, R = 52, T = 10, B = 14;
    const ph = H - T - B, pw = W - L - R;
    const idx = [];
    for (let k = 0; k < n0; k += step) idx.push(k);
    if (idx[idx.length - 1] !== n0 - 1) idx.push(n0 - 1);
    const v = idx.map(k => vals[k]);
    const e = ema ? idx.map(k => ema[k]) : null;
    const all = e ? v.concat(e) : v;
    const lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.02 || 0.01;
    const y0 = lo - pad, y1 = hi + pad;
    const n = v.length;
    const X = k => L + pw * k / (n - 1);
    const Y = x => T + ph * (1 - (x - y0) / (y1 - y0));
    const cross = svg.querySelector('line[id$="-cross"]');
    const dot = svg.querySelector('circle[id$="-dot"]');
    const fmtD = s => {
      const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const a = s.split('-');
      return a[2] + ' ' + m[+a[1] - 1] + ' ' + a[0];
    };
    svg.addEventListener('mousemove', function (ev) {
      const r = svg.getBoundingClientRect();
      const x = (ev.clientX - r.left) * (W / r.width);
      let k = Math.round((x - L) / pw * (n - 1));
      if (k < 0) k = 0; if (k >= n) k = n - 1;
      const px = X(k), py = Y(v[k]);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px);
      cross.style.visibility = 'visible';
      dot.setAttribute('cx', px); dot.setAttribute('cy', py);
      dot.style.visibility = 'visible';
      const raw = idx[k];
      tip.innerHTML = `<b>${fmtD(dates[raw])}</b>${v[k].toFixed(4)}` +
        (e ? `<i class="tip-ema">${e[k].toFixed(4)}</i>` : '');
      tip.style.visibility = 'visible';
      const tipW = tip.offsetWidth;
      const plotW = svg.parentNode.clientWidth;
      let left = (ev.clientX - r.left) - tipW / 2;
      left = Math.max(2, Math.min(left, plotW - tipW - 2));
      tip.style.left = left + 'px';
      tip.style.top = (py * (r.height / H) - 30) + 'px';
    });
    svg.addEventListener('mouseleave', function () {
      cross.style.visibility = 'hidden';
      dot.style.visibility = 'hidden';
      tip.style.visibility = 'hidden';
    });
  }

  // ---- Stock detail modal ----
  function findMember(sym) {
    for (const lv of Object.values(state.levelData)) {
      if (!lv || !lv.groups) continue;
      for (const g of lv.groups) {
        const m = (g.members || []).find(x => x.s === sym);
        if (m) return m;
      }
    }
    return null;
  }

  function lookupName(sym) {
    const m = findMember(sym);
    if (m) return m.n;
    const ipo = (state.meta && state.meta.ipo) || [];
    const i = ipo.find(x => x.s === sym);
    return i ? i.n : sym;
  }

  function openStockModal(sym) {
    const modal = document.getElementById('stock-modal');
    const name = lookupName(sym);
    const m = findMember(sym);
    modal.classList.add('open');
    modal.querySelector('.sm-name').textContent = name === sym ? sym : `${name} — ${sym}`;
    const plot = modal.querySelector('.sm-plot');
    plot.innerHTML = '<div class="loading">Loading</div>';
    api.get('/api/stock/' + encodeURIComponent(sym)).then(d => {
      plot.innerHTML = `<div class="sm-legend"><span class="lg-rs">RS line (stock ÷ NIFTY 500)</span><span class="lg-ema">EMA21</span><span class="sm-ltp">LTP ${utils.fmtPrice(d.ltp)} · ${d.rse === 1 ? 'above' : 'below'} EMA21</span></div>
        ${lineChartSVG(d.rs, d.ema21, 'sm-chart', 700, 260)}
        <div class="mtip sm-tip" id="sm-tip"></div>`;
      bindLineChart('sm-chart', d.dates, d.rs, d.ema21, document.getElementById('sm-tip'));
    }).catch(() => {
      // no /api/stock (static site / old server) — use embedded data instead
      const ipo = ((state.meta && state.meta.ipo) || []).find(x => x.s === sym);
      if (ipo && ipo.rs && ipo.rs.length > 1) {
        const above = ipo.rs[ipo.rs.length - 1] >= ipo.ema21[ipo.ema21.length - 1];
        plot.innerHTML = `<div class="sm-legend"><span class="lg-rs">RS line (stock ÷ NIFTY 500)</span><span class="lg-ema">EMA21</span><span class="sm-ltp">LTP ${utils.fmtPrice(ipo.ltp)} · ${above ? 'above' : 'below'} EMA21</span></div>
          ${lineChartSVG(ipo.rs, ipo.ema21, 'sm-chart', 700, 260)}
          <div class="mtip sm-tip" id="sm-tip"></div>`;
        bindLineChart('sm-chart', ipo.dates, ipo.rs, ipo.ema21,
          document.getElementById('sm-tip'));
      } else if (m && m.r) {
        plot.innerHTML = `<div class="sm-legend"><span class="lg-rs">26-day RS window</span><span class="sm-ltp">full chart needs the local server</span></div>
          ${lineChartSVG(m.r, null, 'sm-chart', 700, 220)}
          <div class="mtip sm-tip" id="sm-tip"></div>`;
        bindLineChart('sm-chart', (state.meta.window_dates || m.r.map((_, i) => 'd' + i)), m.r, null,
          document.getElementById('sm-tip'));
      } else {
        plot.innerHTML = '<div class="brd-empty">Chart unavailable — restart the local server (bash run_server.sh) to enable full charts.</div>';
      }
    });
  }

  function closeStockModal() {
    document.getElementById('stock-modal').classList.remove('open');
  }

  // ---- Watchlist (localStorage) ----
  function loadWatchlist() {
    try { return new Set(JSON.parse(localStorage.getItem('rs_watchlist') || '[]')); }
    catch (e) { return new Set(); }
  }

  function toggleWatchlist(sym) {
    if (state.watchlist.has(sym)) state.watchlist.delete(sym);
    else state.watchlist.add(sym);
    localStorage.setItem('rs_watchlist', JSON.stringify([...state.watchlist]));
    syncWatchlist();
    document.querySelectorAll(`.wstar[data-sym="${CSS.escape(sym)}"]`).forEach(b => {
      b.classList.toggle('on', state.watchlist.has(sym));
      b.textContent = state.watchlist.has(sym) ? '★' : '☆';
    });
  }

  // Local server: mirror the stars to ~/.config/nse-rs/watchlist.txt so the
  // evening Telegram brief can alert on them (the static site can't).
  function syncWatchlist() {
    if (staticData) return;
    fetch('/api/watchlist', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: [...state.watchlist] }) }).catch(() => {});
  }
  async function mergeServerWatchlist() {
    if (staticData) return;
    try {
      const r = await fetch('/api/watchlist');
      if (!r.ok) return;
      const server = (await r.json()).symbols || [];
      const before = state.watchlist.size;
      server.forEach(s => state.watchlist.add(s));
      if (state.watchlist.size !== before) {
        localStorage.setItem('rs_watchlist', JSON.stringify([...state.watchlist]));
      }
      if (state.watchlist.size !== server.length) syncWatchlist();
    } catch (e) { /* older server without /api/watchlist */ }
  }

  // ---- CSV export of the current level tab ----
  function exportCSV() {
    const tab = state.activeTab;
    const data = state.levelData[tab];
    if (!data || !data.groups) { flashMsg('Nothing to export'); return; }
    const q = ($.searchInput.value || '').trim().toLowerCase();
    const filtering = q || state.emaFilter.size || state.hiFilter.on ||
      state.adrFilter.on || state.rsFilter.on || state.rseFilter || state.watchlistOnly;
    const head = ['level', 'group', 'group_n', 'group_rs_pct', 'group_delta',
      'symbol', 'name', 'rs_pct', 'delta', 'ltp', 'ema20', 'ema50', 'ema100',
      'ema150', 'ema200', 'off_high_pct', 'adr_pct', 'rs_ema21', 'new_listing_days'];
    const lines = [head.join(',')];
    const esc = s => `"${String(s == null ? '' : s).replace(/"/g, '""')}"`;
    for (const g of data.groups) {
      const members = filtering
        ? (g.members || []).filter(m => memberPasses(m, q, q && g.name.toLowerCase().includes(q)))
        : (g.members || []);
      for (const m of members) {
        lines.push([tab, g.name, g.n, (g.pct * 100).toFixed(1),
          g.dp != null ? g.dp.toFixed(1) : '', m.s, m.n, (m.p * 100).toFixed(1),
          m.d != null ? m.d.toFixed(1) : '', m.l, ...(m.e || []), m.h, m.a,
          m.b === 1 ? 'above' : (m.b === 0 ? 'below' : ''), m.nw].map(esc).join(','));
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nse_rs_${tab}_${(state.meta.generated || '').split(' ')[0] || 'export'}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    flashMsg('CSV downloaded');
  }

  // =========================================================================
  // TABLE EVENTS
  // =========================================================================
  function bindTableEvents() {
    const table = document.getElementById('level-table');
    if (!table) return;

    // Group row click → expand/collapse · member name → stock chart · star → watchlist
    table.addEventListener('click', function (e) {
      const star = e.target.closest('.wstar');
      if (star) {
        e.stopPropagation();
        toggleWatchlist(star.dataset.sym);
        return;
      }
      // Don't toggle when clicking checkboxes
      if (e.target.tagName === 'INPUT') return;

      const grp = e.target.closest('tr.grp');
      if (grp) {
        const body = grp.parentNode;
        expandGroup(body);
        return;
      }
      const mrow = e.target.closest('tr[data-sym]');
      if (mrow) openStockModal(mrow.dataset.sym);
    });

    // Sort on header click
    table.querySelectorAll('th[data-sort]').forEach(th => {
      th.addEventListener('click', function () {
        const k = th.dataset.sort;
        if (state.sortKey === k) {
          state.sortAsc = !state.sortAsc;
        } else {
          state.sortKey = k;
          state.sortAsc = (k === 'name'); // default: name ascending, pct descending
        }
        refreshCurrentView();
      });
    });

    // Checkbox changes (delegated)
    table.addEventListener('change', function (e) {
      const t = e.target;
      if (t.classList.contains('pick')) {
        if (t.checked) state.selected.add(t.dataset.sym);
        else state.selected.delete(t.dataset.sym);
        syncCheckboxes(t.dataset.sym, t.checked);
        updateSelectionUI();
      } else if (t.classList.contains('gpick')) {
        const body = t.closest('tbody.gb');
        const sub = body.querySelector('tr.sub');
        const isExpanded = !sub.classList.contains('hide');
        let pickList;

        if (isExpanded) {
          // Only select visible (filtered, non-hidden) member rows
          const rows = body.querySelectorAll('.sub-table tbody tr');
          pickList = Array.from(rows)
            .filter(r => r.offsetParent !== null)
            .map(r => r.querySelector('input.pick'))
            .filter(cb => cb)
            .map(cb => cb.dataset.sym);
        } else {
          // Group not expanded — get members from cache or level data
          const gid = +body.dataset.gid;
          const members = getGroupMembersSync(gid) || [];
          // Apply current filter
          const q = ($.searchInput.value || '').trim().toLowerCase();
          const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter || state.watchlistOnly;
          const gmatch = q && (body.dataset.name || '').toLowerCase().includes(q);
          pickList = members
            .filter(m => !filtering || memberPasses(m, q, gmatch))
            .map(m => m.s);
        }

        if (t.checked) pickList.forEach(s => state.selected.add(s));
        else pickList.forEach(s => state.selected.delete(s));

        // Sync visible checkboxes
        if (isExpanded) {
          body.querySelectorAll('input.pick').forEach(cb => {
            cb.checked = t.checked;
          });
        }
        pickList.forEach(s => syncCheckboxes(s, t.checked));
        updateSelectionUI();
      }
    });
  }

  function syncCheckboxes(sym, checked) {
    // CSS.escape is well-supported but provide a fallback for ancient browsers
    const escSym = typeof CSS !== 'undefined' && CSS.escape
      ? CSS.escape(sym) : sym.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
    document.querySelectorAll(`input.pick[data-sym="${escSym}"]`).forEach(cb => {
      cb.checked = checked;
    });
  }

  // =========================================================================
  // SELECTION TOOLS
  // =========================================================================
  function updateSelectionUI() {
    $.selCount.textContent = state.selected.size + ' selected';
  }

  function selectVisible(checked) {
    const table = document.getElementById('level-table');
    if (!table) return;

    // Collect symbols from expanded member rows (visible, non-hidden)
    table.querySelectorAll('.sub-table tbody tr').forEach(row => {
      if (row.offsetParent === null) return;
      const cb = row.querySelector('input.pick');
      if (!cb) return;
      cb.checked = checked;
      if (checked) state.selected.add(cb.dataset.sym);
      else state.selected.delete(cb.dataset.sym);
      syncCheckboxes(cb.dataset.sym, checked);
    });

    // Also cover unexpanded groups: read from cached member data, filtered
    const q = ($.searchInput.value || '').trim().toLowerCase();
    const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter || state.watchlistOnly;
    table.querySelectorAll('tbody.gb').forEach(body => {
      const sub = body.querySelector('tr.sub');
      if (!sub.classList.contains('hide')) return; // already handled above (expanded)
      const gid = +body.dataset.gid;
      const members = getGroupMembersSync(gid) || [];
      const gmatch = q && (body.dataset.name || '').toLowerCase().includes(q);
      const pickList = members
        .filter(m => !filtering || memberPasses(m, q, gmatch))
        .map(m => m.s);
      if (checked) pickList.forEach(s => state.selected.add(s));
      else pickList.forEach(s => state.selected.delete(s));
      pickList.forEach(s => syncCheckboxes(s, checked));
    });

    updateSelectionUI();
  }

  function clearSelection() {
    state.selected.clear();
    document.querySelectorAll('input.pick, input.gpick').forEach(x => x.checked = false);
    updateSelectionUI();
  }

  function tvText() {
    return Array.from(state.selected).map(s => 'NSE:' + s).join(',\n');
  }

  function copyTV() {
    if (!state.selected.size) { flashMsg('Nothing selected'); return; }
    const txt = tvText();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(
        () => flashMsg('Copied ' + state.selected.size),
        () => fallbackCopy(txt)
      );
    } else {
      fallbackCopy(txt);
    }
  }

  function fallbackCopy(txt) {
    const ta = document.createElement('textarea');
    ta.value = txt;
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); flashMsg('Copied ' + state.selected.size); }
    catch (e) { flashMsg('Copy failed'); }
    document.body.removeChild(ta);
  }

  function downloadTV() {
    if (!state.selected.size) { flashMsg('Nothing selected'); return; }
    const blob = new Blob([tvText()], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'tradingview_watchlist.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    flashMsg('Downloaded ' + state.selected.size);
  }

  function flashMsg(msg) {
    $.flash.textContent = msg;
    $.flash.classList.add('show');
    setTimeout(() => $.flash.classList.remove('show'), 2200);
  }

  // =========================================================================
  // SEARCH / FILTER BINDINGS
  // =========================================================================
  function bindToolbarEvents() {
    // Search
    $.searchInput.addEventListener('input', utils.debounce(() => {
      refreshCurrentView();
    }, 150));

    $.searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { $.searchInput.value = ''; refreshCurrentView(); }
    });

    // EMA toggles
    document.querySelectorAll('.ema-tog[data-ema]').forEach(btn => {
      btn.addEventListener('click', function () {
        const i = +btn.dataset.ema;
        if (state.emaFilter.has(i)) { state.emaFilter.delete(i); btn.classList.remove('on'); }
        else { state.emaFilter.add(i); btn.classList.add('on'); }
        updateFilterInfo();
        refreshCurrentView();
      });
    });

    document.getElementById('ema-clear').addEventListener('click', function () {
      state.emaFilter.clear();
      document.querySelectorAll('.ema-tog[data-ema]').forEach(b => b.classList.remove('on'));
      updateFilterInfo();
      refreshCurrentView();
    });

    // 52-week high filter
    function syncHi() {
      state.hiFilter.on = $.hiOn.checked;
      state.hiFilter.max = parseFloat($.hiMax.value) || 0;
      $.hiChip.classList.toggle('on', state.hiFilter.on);
      $.hiChip.classList.toggle('hi', state.hiFilter.on);
      updateFilterInfo();
      refreshCurrentView();
    }
    $.hiOn.addEventListener('change', syncHi);
    $.hiMax.addEventListener('input', function () {
      if ($.hiMax.value !== '' && !$.hiOn.checked) $.hiOn.checked = true;
      syncHi();
    });

    // ADR filter
    function syncAdr() {
      state.adrFilter.on = $.adrOn.checked;
      state.adrFilter.min = parseFloat($.adrMin.value) || 0;
      $.adrChip.classList.toggle('on', state.adrFilter.on);
      $.adrChip.classList.toggle('adr', state.adrFilter.on);
      updateFilterInfo();
      refreshCurrentView();
    }
    $.adrOn.addEventListener('change', syncAdr);
    $.adrMin.addEventListener('input', function () {
      if ($.adrMin.value !== '' && !$.adrOn.checked) $.adrOn.checked = true;
      syncAdr();
    });

    // RS% filter
    function syncRs() {
      state.rsFilter.on = $.rsOn.checked;
      state.rsFilter.min = parseFloat($.rsMin.value) || 0;
      $.rsChip.classList.toggle('on', state.rsFilter.on);
      $.rsChip.classList.toggle('rs', state.rsFilter.on);
      updateFilterInfo();
      refreshCurrentView();
    }
    $.rsOn.addEventListener('change', syncRs);
    $.rsMin.addEventListener('input', function () {
      if ($.rsMin.value !== '' && !$.rsOn.checked) $.rsOn.checked = true;
      syncRs();
    });

    // RS-above-EMA21 filter
    $.rseOn.addEventListener('change', function () {
      state.rseFilter = $.rseOn.checked;
      $.rseChip.classList.toggle('on', state.rseFilter);
      $.rseChip.classList.toggle('rse', state.rseFilter);
      updateFilterInfo();
      refreshCurrentView();
    });

    // Selection tools
    document.getElementById('sel-vis').addEventListener('click', () => selectVisible(true));
    document.getElementById('sel-clear').addEventListener('click', clearSelection);
    document.getElementById('btn-copy').addEventListener('click', copyTV);
    document.getElementById('btn-dl').addEventListener('click', downloadTV);
  }

  function updateFilterInfo() {
    const bits = [];
    if (state.emaFilter.size) bits.push('above ' + state.emaFilter.size + ' EMA' + (state.emaFilter.size > 1 ? 's' : ''));
    if (state.hiFilter.on) bits.push('≤' + state.hiFilter.max + '% off high');
    if (state.adrFilter.on) bits.push('ADR≥' + state.adrFilter.min + '%');
    if (state.rsFilter.on) bits.push('RS≥' + state.rsFilter.min + '%');
    if (state.rseFilter) bits.push('RS>EMA21');
    if (state.watchlistOnly) bits.push('★ watchlist');
    $.filterInfo.textContent = bits.join(' · ');
  }

  // =========================================================================
  // ACTION BUTTONS (pipeline triggers)
  // =========================================================================
  function bindActionButtons() {
    // Shared polling + feedback for pipeline buttons
    function runPipeline(url, btn, label) {
      if (btn.disabled) return;
      const origText = btn.textContent;
      btn.textContent = 'Running…';
      btn.disabled = true;
      btn.style.opacity = '0.7';

      fetch(url, { method: 'POST' })
        .then(r => {
          if (!r.ok) return r.json().then(d => { throw new Error(d.detail || 'Failed'); });
          return r.json();
        })
        .then(data => {
          flashMsg(`${label} started — fetching data…`);
          pollUntilDone(btn, origText);
        })
        .catch(err => {
          flashMsg(`Error: ${err.message}`);
          btn.textContent = origText;
          btn.disabled = false;
          btn.style.opacity = '';
        });
    }

    function pollUntilDone(btn, origText) {
      let attempts = 0;
      const maxAttempts = 180; // 15 minutes at 5s intervals
      const interval = setInterval(() => {
        attempts++;
        fetch('/api/pipeline-status')
          .then(r => r.json())
          .then(status => {
            if (!status.running) {
              clearInterval(interval);
              btn.textContent = origText;
              btn.disabled = false;
              btn.style.opacity = '';
              if (status.last_result === 'ok') {
                flashMsg('Done — data updated. Reloading…');
                // Reload API data + refresh current view
                setTimeout(() => {
                  Promise.all([api.meta(), api.levels()]).then(([meta, levels]) => {
                    state.meta = meta;
                    state.levels = levels;
                    state.levelData = {};
                    state.groupMembers = {};
                    state.breadthData = null;
                    state.rotationData = null;
                    state.flowsData = null;
                    state.decide = null;
                    state.track = null;
                    document.getElementById('meta-drange').textContent = meta.drange;
                    document.getElementById('stat-gen').textContent = (meta.generated || '').split(' ')[0] || '';
                    document.getElementById('stat-gen-sub').textContent = (meta.generated || '').split(' ')[1] || '';
                    refreshCurrentView();
                  });
                }, 500);
              } else {
                const why = (status.last_output || '').split('\n').filter(Boolean).slice(-3).join(' · ');   // error is at the end
                flashMsg(`Failed: ${why ? why.slice(0, 150) : status.last_result}`);
              }
            } else if (attempts > maxAttempts) {
              clearInterval(interval);
              btn.textContent = origText;
              btn.disabled = false;
              btn.style.opacity = '';
              flashMsg('Timed out — still running in background');
            }
          });
      }, 5000);
    }

    $.btnUpdate.addEventListener('click', () => {
      runPipeline('/api/update-prices', $.btnUpdate, 'Update Prices');
    });
    $.btnRefreshStocks.addEventListener('click', () => {
      runPipeline('/api/refresh-stocks', $.btnRefreshStocks, 'Refresh Stocks');
    });
  }

  // =========================================================================
  // INIT
  // =========================================================================
  async function init() {
    // Collect DOM refs
    $.themeToggle = document.getElementById('theme-toggle');
    $.tabBar = document.getElementById('tab-bar');
    $.toolbarSection = document.getElementById('toolbar-section');  // exists in HTML
    $.searchInput = document.getElementById('search-input');
    $.searchInfo = document.getElementById('search-info');
    $.filterInfo = document.getElementById('filter-info');
    $.selCount = document.getElementById('sel-count');
    $.flash = document.getElementById('flash');
    $.content = document.getElementById('content');
    $.note = document.getElementById('note');
    $.hiOn = document.getElementById('hi-on');
    $.hiMax = document.getElementById('hi-max');
    $.hiChip = document.getElementById('hi-chip');
    $.adrOn = document.getElementById('adr-on');
    $.adrMin = document.getElementById('adr-min');
    $.adrChip = document.getElementById('adr-chip');
    $.rsOn = document.getElementById('rs-on');
    $.rsMin = document.getElementById('rs-min');
    $.rsChip = document.getElementById('rs-chip');
    $.rseOn = document.getElementById('rse-on');
    $.rseChip = document.getElementById('rse-chip');
    $.btnUpdate = document.getElementById('btn-update');
    $.btnRefreshStocks = document.getElementById('btn-refresh-stocks');

    // Theme
    initTheme();
    $.themeToggle.addEventListener('click', toggleTheme);

    // Boot the API — falls back to rs_data.json on the static export
    try {
      await bootApi();
      await mergeServerWatchlist();
    } catch (e) {
      $.content.innerHTML = `<div class="brd-empty">Failed to load data.<br><br><code>${utils.esc(e.message)}</code></div>`;
      return;
    }
    if (staticData) {
      $.btnUpdate.style.display = 'none';
      $.btnRefreshStocks.style.display = 'none';
      const tag = document.createElement('span');
      tag.className = 'static-tag';
      tag.textContent = 'read-only snapshot';
      $.note.appendChild(document.createTextNode(' '));
      $.note.appendChild(tag);
    }

    // Fetch meta + levels
    try {
      const [meta, levels] = await Promise.all([api.meta(), api.levels()]);
      state.meta = meta;
      state.levels = levels;
    } catch (e) {
      $.content.innerHTML = `<div class="brd-empty">Failed to connect to backend.<br><br><code>${utils.esc(e.message)}</code></div>`;
      return;
    }

    // Update header
    document.getElementById('meta-drange').textContent = state.meta.drange;

    // Populate stat cards
    document.getElementById('stat-stocks').textContent = state.meta.n_stocks.toLocaleString();
    const nWindow = state.meta.n_window || state.meta.n_stocks;
    const nThin = (state.meta.illiquid || []).length;
    const sub = document.getElementById('stat-stocks-sub');
    sub.textContent = `${nWindow.toLocaleString()} ranked · ${(state.meta.n_stocks - nWindow).toLocaleString()} left out today`
      + (nThin ? ` (${nThin} thinly traded)` : '');
    if (nThin) sub.title = `Thinly traded — skipped a session in the last ${state.meta.window || 26} and trade under ₹1 cr a day, so their RS isn't real: ${state.meta.illiquid.join(', ')}`;
    const totalGroups = state.meta.n_groups_per_level.reduce((a, b) => a + b, 0);
    document.getElementById('stat-groups').textContent = totalGroups;
    document.getElementById('stat-groups-sub').textContent =
      state.meta.n_groups_per_level.map((n, i) => `${n} ${state.levels[i]?.label?.toLowerCase() || ''}`).join(', ');
    const genDate = state.meta.generated;
    document.getElementById('stat-gen').textContent = genDate.split(' ')[0] || genDate;
    document.getElementById('stat-gen-sub').textContent = genDate.split(' ')[1] || '';

    // Fetch breadth for stat card (non-blocking)
    api.breadth().then(data => {
      if (data.latest != null) {
        const el = document.getElementById('stat-breadth');
        el.textContent = (data.latest >= 0 ? '+' : '') + data.latest.toFixed(1);
        el.className = 'stat-val ' + (data.latest >= 0 ? 'val-up' : 'val-down');
        document.getElementById('stat-breadth-sub').textContent = data.n + ' stocks · ' + data.span;
      }
    }).catch(() => {});

    // Build tab bar
    let tabHTML = '';
    for (const lv of state.levels) {
      tabHTML += `<button class="tab" data-tab="${lv.key}">${lv.label} <span class="badge">${lv.n_groups}</span></button>`;
    }
    tabHTML += '<button class="tab" data-tab="breadth">Market Breadth</button>';
    tabHTML += '<button class="tab" data-tab="rotation">Rotation</button>';
    tabHTML += '<button class="tab" data-tab="ipo">New Listings</button>';
    tabHTML += '<button class="tab" data-tab="scans">Scans</button>';
    tabHTML += '<button class="tab" data-tab="flows">FII / DII</button>';
    tabHTML += '<button class="tab" data-tab="focus">Focus</button>';
    tabHTML += '<button class="tab" data-tab="swing">Swing</button>';
    $.tabBar.innerHTML = tabHTML;

    // Tab click handlers
    $.tabBar.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => setHashTab(btn.dataset.tab));
    });

    // Toolbar events
    bindToolbarEvents();
    bindActionButtons();

    // Phase-4 events: CSV export, watchlist chip, stock modal
    document.getElementById('btn-csv').addEventListener('click', exportCSV);
    const watchTog = document.getElementById('watch-tog');
    watchTog.addEventListener('click', function () {
      state.watchlistOnly = !state.watchlistOnly;
      watchTog.classList.toggle('on', state.watchlistOnly);
      updateFilterInfo();
      refreshCurrentView();
    });
    document.getElementById('modal-close').addEventListener('click', closeStockModal);
    document.getElementById('stock-modal').addEventListener('click', function (e) {
      if (e.target === this) closeStockModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeStockModal();
    });

    // Route to the correct tab from URL hash
    const initialTab = getHashTab();
    // Validate against known levels
    const validTabs = state.levels.map(l => l.key).concat(['breadth', 'rotation', 'ipo', 'scans', 'flows', 'focus', 'swing']);
    const tab = validTabs.includes(initialTab) ? initialTab : 'macro';
    if (tab !== initialTab) setHashTab(tab);
    else activateTab(tab);
  }

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
