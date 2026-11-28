// Pure data logic shared by the pages (unit-tested in market.test.ts).
import type { FlowDay, FlowMonth, Level, Member } from '../api/types';
import { CAP_LABEL, CAP_ORDER } from './format';

// ---------------------------------------------------------------- stocks
export interface Stock extends Member { macro?: string; sector?: string; industry?: string; basic?: string }

/** One record per stock with its macro / sector / industry / sub-industry names. */
export function stockIndex(levels: Record<string, Level>): Stock[] {
  const stocks = new Map<string, Stock>();
  for (const g of levels.macro?.groups ?? []) {
    for (const m of g.members) stocks.set(m.s, { ...m, macro: g.name });
  }
  for (const key of ['sector', 'industry', 'basic'] as const) {
    for (const g of levels[key]?.groups ?? []) {
      for (const m of g.members) {
        const st = stocks.get(m.s);
        if (st) st[key] = g.name;
      }
    }
  }
  return [...stocks.values()];
}

// ---------------------------------------------------------------- ranking filters
export interface Filters {
  q: string; ema: number[]; hi: number | null; adr: number | null; rs: number | null;
  rse: boolean; watchOnly: boolean;
}
export const NO_FILTERS: Filters = { q: '', ema: [], hi: null, adr: null, rs: null, rse: false, watchOnly: false };

export const isFiltering = (f: Filters) =>
  !!(f.q.trim() || f.ema.length || f.hi != null || f.adr != null || f.rs != null || f.rse || f.watchOnly);

/** Does a stock pass the ranking-table filters?  `groupMatch` = the search
 *  text matched the group's own name (then every member shows). */
export function memberPasses(m: Member, f: Filters, groupMatch: boolean, watch: Set<string>): boolean {
  const q = f.q.trim().toLowerCase();
  if (q && !groupMatch && !(m.n + ' ' + m.s).toLowerCase().includes(q)) return false;
  for (const i of f.ema) if (m.e[i] !== 1) return false;
  if (f.hi != null && (m.h == null || m.h > f.hi)) return false;
  if (f.adr != null && (m.a == null || m.a < f.adr)) return false;
  if (f.rs != null && (m.p == null || m.p * 100 < f.rs)) return false;
  if (f.rse && m.b !== 1) return false;
  if (f.watchOnly && !watch.has(m.s)) return false;
  return true;
}

// ---------------------------------------------------------------- rotation
export const ROT_RANGES: Record<string, number> = { '3M': 3, '6M': 6, '1Y': 12, All: 0 };

/** Index of the base session: the close on (or the last one before) the same
 *  calendar date `months` earlier than the latest date (30-Oct − 3M → 30-Jul;
 *  31-May − 3M → 28/29-Feb). */
export function rotStartIndex(dates: string[], months: number): number {
  if (!months || !dates.length) return 0;
  const [y, m, d] = dates[dates.length - 1].split('-').map(Number);
  const back = new Date(Date.UTC(y, m - 1 - months, 1));
  const lastDay = new Date(Date.UTC(back.getUTCFullYear(), back.getUTCMonth() + 1, 0)).getUTCDate();
  back.setUTCDate(Math.min(d, lastDay));
  const cutoff = back.toISOString().slice(0, 10);
  let i = 0;
  while (i + 1 < dates.length && dates[i + 1] <= cutoff) i++;
  return i;
}

/** RS lines over a period, rebased to 1.0 at its base session. */
export function rebase(rs: number[], start: number): number[] {
  const base = rs[start] || 1;
  return rs.slice(start).map(v => v / base);
}

// ---------------------------------------------------------------- scans
export const GAINER = { minGain: 14, minTurnoverCr: 10, minPrice: 100 };
export type ScanDim = 'sector' | 'basic' | 'cap';

/** 1-month gainers: up ≥ 14% over 20 sessions, ≥ ₹10 cr/day, price ≥ ₹100. */
export const isGainer = (m: Member) =>
  m.m1 != null && m.m1 >= GAINER.minGain && m.tv != null && m.tv >= GAINER.minTurnoverCr && m.l != null && m.l >= GAINER.minPrice;

export function scanGroups(all: Stock[], dim: ScanDim) {
  const groupOf = (m: Stock) => (dim === 'cap' ? m.cap || 'New' : m[dim]);
  const members = new Map<string, Stock[]>();
  const hits = new Map<string, Stock[]>();
  for (const m of all) {
    const k = groupOf(m);
    if (!k) continue;
    if (!members.has(k)) members.set(k, []);
    members.get(k)!.push(m);
    if (isGainer(m)) {
      if (!hits.has(k)) hits.set(k, []);
      hits.get(k)!.push(m);
    }
  }
  const count = (k: string) => hits.get(k)?.length ?? 0;
  const keys = dim === 'cap'
    ? CAP_ORDER.filter(k => members.has(k))
    : [...hits.keys()].sort((a, b) => count(b) - count(a) || a.localeCompare(b));
  const label = (k: string) => (dim === 'cap' ? CAP_LABEL[k] ?? k : k);
  const total = [...hits.values()].reduce((a, l) => a + l.length, 0);
  return { keys, members, hits, count, label, total };
}

// ---------------------------------------------------------------- FII / DII
export const FLOW_RANGES = {
  M: { '1Y': 12, '3Y': 36, '5Y': 60, All: 0 } as Record<string, number>,
  D: { '1M': 21, '3M': 63, '6M': 126, '1Y': 252, All: 0 } as Record<string, number>,
};
export type FlowView = 'M' | 'D';
export interface FlowRow {
  k: string; fii: number; dii: number;
  fb: number | null; fs: number | null; db: number | null; ds: number | null; to?: string | null;
}

export function flowRows(months: FlowMonth[], days: FlowDay[], view: FlowView, range: string): FlowRow[] {
  const all: FlowRow[] = view === 'D'
    ? days.map(r => ({ k: r.d, fii: r.fii, dii: r.dii, fb: r.fb ?? null, fs: r.fs ?? null, db: r.db ?? null, ds: r.ds ?? null }))
    : months.map(r => ({ k: r.m, fii: r.fii, dii: r.dii, fb: r.fb, fs: r.fs, db: r.db, ds: r.ds, to: r.to }));
  const n = FLOW_RANGES[view][range] ?? 0;
  return n ? all.slice(-n) : all;
}
