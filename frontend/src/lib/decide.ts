// Wording for the Focus / Swing pages — the rules themselves live in
// rs_engine/decide.py (the build computes them once, so the site, the pick
// log and the Telegram brief always agree).

export const REGIME = {
  on: { word: 'Risk-on', line: 'trend and breadth agree — normal size, act on breakouts in the leading groups.',
    size: 'Exposure 75–100% · risk ~1% of capital per trade · 4–6 positions' },
  mixed: { word: 'Mixed', line: 'signals disagree — be selective: half size, only the best setups in leading groups, book profits sooner.',
    size: 'Exposure 25–50% · risk ~0.5% per trade · 2–3 positions' },
  off: { word: 'Risk-off', line: 'trend and breadth are weak — protect capital: mostly cash, small pilot positions only.',
    size: 'Exposure 0–20% · risk ≤0.5% per trade · pilots only' },
} as const;

export const QUAD_TIP: Record<string, string> = {
  Leading: 'beating the average stock over 1M and 3M',
  Improving: 'behind over 3M but beating the average stock over 1M — turning up',
  Weakening: 'ahead over 3M but lagging over 1M — losing steam',
  Lagging: 'behind the average stock over 1M and 3M',
};

export const TAG_WORD: Record<string, string> = {
  tight: 'Tight', dry: 'Vol dry-up', surge: 'Vol surge', dhi: 'High delivery', dlo: 'Weak delivery',
  near10: 'Near 10W', vdry: 'Flag vol dry-up',
};
export const TAG_TONE: Record<string, string> = {
  tight: 'pos', dry: 'info', surge: 'warn', dhi: 'pos', dlo: 'neg', near10: 'info', vdry: 'pos',
};
export const TAG_TIP: Record<string, string> = {
  tight: '10-day range within 2.5 average daily ranges — a quiet base (ranked higher)',
  dry: '10-day volume below 85% of the prior 50 days — sellers drying up (ranked higher)',
  surge: 'today’s volume ≥ 1.5× average — buying this close is chasing; wait for a pause (ranked lower)',
  dhi: '20-day average delivery ≥ 50% — steady buying into demat (breakouts ranked higher)',
  dlo: 'today’s delivery below 80% of its average — more intraday churn than buying (breakouts ranked lower)',
  near10: 'within 5% above its 10-week SMA — close to the weekly support line, a low-risk entry',
  vdry: 'average volume in the flag under 70% of the pole’s — sellers gone; in the NSE test these HTFs did far better (ranked first)',
};

/** "A", "A and B", "A, B, and C" */
export const joinNames = (xs: string[]) =>
  xs.length <= 1 ? xs.join('') : xs.length === 2 ? `${xs[0]} and ${xs[1]}` : `${xs.slice(0, -1).join(', ')}, and ${xs[xs.length - 1]}`;
