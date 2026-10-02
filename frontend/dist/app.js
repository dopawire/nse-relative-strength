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
      src: m.src || {},
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
    // Show/hide toolbars for breadth vs level tabs
    const isBreadth = tab === 'breadth';
    $.toolbarSection.style.display = isBreadth ? 'none' : '';
    $.note.style.display = isBreadth ? 'none' : '';
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

    // Fetch level data if not cached
    if (!state.levelData[tab]) {
      try {
        state.levelData[tab] = await api.level(tab);
      } catch (e) {
        // Cache the error so we don't keep retrying on tab switch
        state.levelData[tab] = { _error: e.message };
        $.content.innerHTML = `<div class="brd-empty">Failed to load data: ${e.message}<br><small>Switch tabs and come back to retry.</small></div>`;
        return;
      }
    } else if (state.levelData[tab]._error) {
      // Previously failed — retry once
      try {
        state.levelData[tab] = await api.level(tab);
      } catch (e) {
        state.levelData[tab] = { _error: e.message };
        $.content.innerHTML = `<div class="brd-empty">Failed to load data: ${e.message}</div>`;
        return;
      }
    }

    const data = state.levelData[tab];
    renderLevelTable(tab, data);
  }

  function refreshCurrentView() {
    if (state.activeTab === 'breadth') {
      renderBreadth(true);   // use cached data — avoid re-fetching
    } else if (state.levelData[state.activeTab]) {
      renderLevelTable(state.activeTab, state.levelData[state.activeTab]);
    }
  }

  // =========================================================================
  // RENDER: LEVEL TABLE
  // =========================================================================
  function renderLevelTable(tab, data) {
    const q = ($.searchInput.value || '').trim().toLowerCase();
    const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter;

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
      rows += `<span class="car">▶</span>${nm}<span class="cnt">${filtering ? filteredMembers.length : g.n}</span></td>`;
      rows += `<td class="sp">${spark}</td>`;
      rows += `<td class="pc"><span class="rs-pct" style="${bg}">${utils.fmtPct(g.pct)}</span></td>`;
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
    const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter;
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
      mrows += `<tr>
        <td class="mck"><input type="checkbox" class="pick" data-sym="${utils.esc(m.s)}"${ck}></td>
        <td class="mnm">${utils.esc(m.n)}<span class="msym">${utils.esc(m.s)}</span></td>
        <td class="msp">${spark}</td>
        <td class="mpc"><span class="rs-pct" style="${bg}">${utils.fmtPct(m.p)}</span></td>
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
      $.content.innerHTML = `<div class="brd-empty">Failed to load breadth data: ${e.message}</div>`;
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
  // TABLE EVENTS
  // =========================================================================
  function bindTableEvents() {
    const table = document.getElementById('level-table');
    if (!table) return;

    // Group row click → expand/collapse
    table.addEventListener('click', function (e) {
      // Don't toggle when clicking checkboxes
      if (e.target.tagName === 'INPUT') return;

      const grp = e.target.closest('tr.grp');
      if (!grp) return;

      const body = grp.parentNode;
      expandGroup(body);
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
          const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter;
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
    const filtering = q || state.emaFilter.size || state.hiFilter.on || state.adrFilter.on || state.rsFilter.on || state.rseFilter;
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
                    document.getElementById('meta-drange').textContent = meta.drange;
                    document.getElementById('stat-gen').textContent = (meta.generated || '').split(' ')[0] || '';
                    document.getElementById('stat-gen-sub').textContent = (meta.generated || '').split(' ')[1] || '';
                    refreshCurrentView();
                  });
                }, 500);
              } else {
                const why = (status.last_output || '').split('\n').filter(Boolean).slice(0, 3).join(' · ');
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
    } catch (e) {
      $.content.innerHTML = `<div class="brd-empty">Failed to load data.<br><br><code>${e.message}</code></div>`;
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
      $.content.innerHTML = `<div class="brd-empty">Failed to connect to backend.<br><br><code>${e.message}</code></div>`;
      return;
    }

    // Update header
    document.getElementById('meta-drange').textContent = state.meta.drange;

    // Populate stat cards
    document.getElementById('stat-stocks').textContent = state.meta.n_stocks.toLocaleString();
    const nWindow = state.meta.n_window || state.meta.n_stocks;
    document.getElementById('stat-stocks-sub').textContent =
      `${nWindow.toLocaleString()} in window · ${(state.meta.n_stocks - nWindow).toLocaleString()} excluded today`;
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
    $.tabBar.innerHTML = tabHTML;

    // Tab click handlers
    $.tabBar.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => setHashTab(btn.dataset.tab));
    });

    // Toolbar events
    bindToolbarEvents();
    bindActionButtons();

    // Route to the correct tab from URL hash
    const initialTab = getHashTab();
    // Validate against known levels
    const validTabs = state.levels.map(l => l.key).concat(['breadth']);
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
