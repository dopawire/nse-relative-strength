export const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const WDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** 1234.5 → "1,234.50" (Indian grouping) · null → "—" */
export const fmtPrice = (p: number | null | undefined) =>
  isNum(p) ? p.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';

/** signed percent: 3.14 → "+3.1%", -2 → "−2.0%" (a real minus sign) */
export const sgn = (v: number | null | undefined, dp = 1) =>
  isNum(v) ? `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(dp)}%` : '—';

/** plain percent: 42.4 → "42%" */
export const pctTxt = (v: number | null | undefined, dp = 0) => (isNum(v) ? `${v.toFixed(dp)}%` : '—');

/** 0..1 share → "57%" */
export const fmtShare = (v: number | null | undefined) => (isNum(v) ? `${Math.round(v * 100)}%` : '—');

/** ₹ crore with Indian grouping and a sign: 122101 → "+₹1,22,101 cr" */
export const crore = (v: number) =>
  `${v >= 0 ? '+' : '−'}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`;

export const num0 = (v: number | null | undefined) =>
  isNum(v) ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—';

/** "2026-11-25" → "25 Nov 2026" */
export const fmtDate = (d: string | null | undefined) => {
  if (!d || !/^\d{4}-\d\d-\d\d$/.test(d)) return d ?? '';
  const [y, m, dd] = d.split('-');
  return `${+dd} ${MON[+m - 1]} ${y}`;
};
/** "2026-11-25" → "25 Nov" */
export const fmtDay = (d: string | null | undefined) => {
  if (!d || !/^\d{4}-\d\d-\d\d$/.test(d)) return d ?? '';
  const [, m, dd] = d.split('-');
  return `${+dd} ${MON[+m - 1]}`;
};
/** "2026-11" → "Nov 2026" */
export const monLabel = (m: string) => `${MON[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
/** "2026-11-25" → "Wed 25 Nov 2026" */
export const dayLabel = (d: string) => `${WDAY[new Date(d + 'T00:00:00Z').getUTCDay()]} ${fmtDate(d)}`;

/** axis ticks in thousand / lakh crore: 150000 → "1.5L", -20000 → "−20k" */
export const axisCr = (v: number) => {
  if (v === 0) return '0';
  const s = v < 0 ? '−' : '';
  const a = Math.abs(v);
  return a >= 1e5 ? `${s}${+(a / 1e5).toFixed(1)}L` : `${s}${+(a / 1e3).toFixed(0)}k`;
};

/** company name without the trailing "Limited" / "Ltd" */
export const shortName = (n: string) => n.replace(/\s+(Limited|Ltd\.?)$/i, '');

export const CAP_ORDER = ['Large', 'Mid', 'Small', 'Micro', 'New'] as const;
export const CAP_LABEL: Record<string, string> = {
  Large: 'Large cap', Mid: 'Mid cap', Small: 'Small cap', Micro: 'Micro cap', New: 'No market cap',
};

export function median(xs: (number | null | undefined)[]): number | null {
  const v = xs.filter(isNum).sort((a, b) => a - b);
  if (!v.length) return null;
  const h = v.length >> 1;
  return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2;
}

export function mean(xs: (number | null | undefined)[]): number | null {
  const v = xs.filter(isNum);
  return v.length ? v.reduce((a, x) => a + x, 0) / v.length : null;
}

/** "2026-12-03 Results, Dividend" → { date, what, results } */
export function parseEvent(ev: string | null | undefined) {
  if (!ev) return null;
  const [date, ...rest] = ev.split(' ');
  const what = rest.join(' ');
  return { date, what, short: what.split(',')[0], results: /\bResults\b/.test(what) };
}
