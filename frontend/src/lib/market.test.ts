import { describe, expect, it } from 'vitest';
import type { Level, Member } from '../api/types';
import { axisCr, crore, fmtDate, fmtPrice, median, parseEvent, sgn, shortName } from './format';
import { flowRows, isGainer, memberPasses, NO_FILTERS, rebase, rotStartIndex, scanGroups, stockIndex } from './market';
import { tvList, tvSections, tvSym } from './tv';

const mem = (s: string, over: Partial<Member> = {}): Member => ({
  n: `${s} Ltd`, s, r: [1, 2], p: 0.5, e: [1, 1, 1, 1, 1], b: 1, h: 5, a: 4, ...over,
});

describe('format', () => {
  it('formats numbers the Indian way', () => {
    expect(fmtPrice(1234567.5)).toBe('12,34,567.50');
    expect(fmtPrice(null)).toBe('—');
    expect(crore(122101)).toBe('+₹1,22,101 cr');
    expect(crore(-60528.4)).toBe('−₹60,528 cr');
    expect(sgn(3.14)).toBe('+3.1%');
    expect(sgn(-2, 0)).toBe('−2%');
    expect(axisCr(150000)).toBe('1.5L');
    expect(axisCr(-20000)).toBe('−20k');
  });
  it('dates and names', () => {
    expect(fmtDate('2026-11-25')).toBe('25 Nov 2026');
    expect(shortName('Milky Mist Dairy Food Limited')).toBe('Milky Mist Dairy Food');
    expect(median([3, 1, null, 2])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
    expect(parseEvent('2026-12-03 Results, Dividend')).toMatchObject({ short: 'Results', results: true });
    expect(parseEvent(null)).toBeNull();
  });
});

describe('TradingView export', () => {
  it('maps & and - to _', () => {
    expect(tvSym('M&M')).toBe('NSE:M_M');
    expect(tvSym('BAJAJ-AUTO')).toBe('NSE:BAJAJ_AUTO');
    expect(tvList(['TCS', 'M&M'])).toBe('NSE:TCS,NSE:M_M');
    expect(tvSections([{ name: 'A', syms: ['X'] }, { name: 'Empty', syms: [] }, { name: 'B', syms: ['Y', 'Z'] }]))
      .toBe('###A,NSE:X,###B,NSE:Y,NSE:Z');
  });
});

describe('ranking filters', () => {
  const watch = new Set(['WATCHED']);
  it('search, EMA, off-high, ADR, RS%, RS line, watchlist', () => {
    const m = mem('TCS', { e: [1, 0, 1, 1, 1], h: 12, a: 2.5, p: 0.85, b: 0 });
    expect(memberPasses(m, { ...NO_FILTERS, q: 'tcs' }, false, watch)).toBe(true);
    expect(memberPasses(m, { ...NO_FILTERS, q: 'infy' }, false, watch)).toBe(false);
    expect(memberPasses(m, { ...NO_FILTERS, q: 'infy' }, true, watch)).toBe(true);   // group name matched
    expect(memberPasses(m, { ...NO_FILTERS, ema: [0] }, false, watch)).toBe(true);
    expect(memberPasses(m, { ...NO_FILTERS, ema: [1] }, false, watch)).toBe(false);
    expect(memberPasses(m, { ...NO_FILTERS, hi: 10 }, false, watch)).toBe(false);
    expect(memberPasses(m, { ...NO_FILTERS, adr: 3 }, false, watch)).toBe(false);
    expect(memberPasses(m, { ...NO_FILTERS, rs: 80 }, false, watch)).toBe(true);
    expect(memberPasses(m, { ...NO_FILTERS, rse: true }, false, watch)).toBe(false);
    expect(memberPasses(m, { ...NO_FILTERS, watchOnly: true }, false, watch)).toBe(false);
    expect(memberPasses(mem('WATCHED'), { ...NO_FILTERS, watchOnly: true }, false, watch)).toBe(true);
  });
});

describe('rotation periods', () => {
  const dates = ['2026-07-28', '2026-07-29', '2026-07-30', '2026-07-31', '2026-10-30'];
  it('base session = same date N months back, or the last before it', () => {
    expect(rotStartIndex(dates, 3)).toBe(2);              // 30-Oct − 3M = 30-Jul
    expect(rotStartIndex(dates, 0)).toBe(0);
    expect(rotStartIndex(['2026-02-27', '2026-03-02', '2026-05-31'], 3)).toBe(0);   // → 28-Feb → 27-Feb close
    expect(rebase([2, 4, 6], 1)).toEqual([1, 1.5]);
  });
});

describe('stock index + scans', () => {
  const lv = (key: string, groups: [string, Member[]][]): Level =>
    ({ key, label: key, groups: groups.map(([name, members], id) => ({ id, name, n: members.length, pct: 0.5, r: [], members })) });
  const gainer = (s: string, cap: string) => mem(s, { m1: 20, tv: 50, l: 500, cap });
  const levels = {
    macro: lv('macro', [['Energy', [gainer('A', 'Large'), mem('B', { cap: 'Small' })]]]),
    sector: lv('sector', [['Oil', [gainer('A', 'Large'), mem('B')]]]),
    industry: lv('industry', [['Refining', [gainer('A', 'Large'), mem('B')]]]),
    basic: lv('basic', [['Refineries', [gainer('A', 'Large')]], ['Gas', [mem('B')]]]),
  };
  it('joins every level onto one record per stock', () => {
    const idx = stockIndex(levels);
    expect(idx).toHaveLength(2);
    expect(idx.find(m => m.s === 'A')).toMatchObject({ macro: 'Energy', sector: 'Oil', industry: 'Refining', basic: 'Refineries' });
  });
  it('counts 1-month gainers by group', () => {
    expect(isGainer(gainer('A', 'Large'))).toBe(true);
    expect(isGainer(mem('B', { m1: 20, tv: 5, l: 500 }))).toBe(false);          // too thin
    const sg = scanGroups(stockIndex(levels), 'cap');
    expect(sg.keys).toEqual(['Large', 'Small']);
    expect(sg.count('Large')).toBe(1);
    expect(sg.total).toBe(1);
    expect(scanGroups(stockIndex(levels), 'basic').keys).toEqual(['Refineries']);
  });
});

describe('FII / DII rows', () => {
  const months = Array.from({ length: 40 }, (_, i) => ({ m: `20${23 + Math.floor(i / 12)}-${String(i % 12 + 1).padStart(2, '0')}`,
    fb: 1, fs: 1, fii: i, db: 1, ds: 1, dii: -i }));
  const days = [{ d: '2026-11-24', fii: 5, dii: -1 }, { d: '2026-11-25', fii: 6, dii: 2, fb: 10, fs: 4, db: 3, ds: 1 }];
  it('slices the period and keeps net-only days', () => {
    expect(flowRows(months, days, 'M', '1Y')).toHaveLength(12);
    expect(flowRows(months, days, 'M', 'All')).toHaveLength(40);
    const d = flowRows(months, days, 'D', '1M');
    expect(d).toHaveLength(2);
    expect(d[0].fb).toBeNull();
    expect(d[1]).toMatchObject({ k: '2026-11-25', fii: 6, fb: 10 });
  });
});
