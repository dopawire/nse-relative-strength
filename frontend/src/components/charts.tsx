// Hand-drawn SVG charts: sparkline, line chart, breadth oscillator, paired
// bars (FII / DII) and a donut.  Every chart has a hover crosshair / tooltip.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { axisCr, fmtDate, MON } from '../lib/format';

/** container width via ResizeObserver */
export function useWidth<T extends HTMLElement>(fallback = 600) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth || fallback);
    const ro = new ResizeObserver(es => { for (const e of es) setW(Math.round(e.contentRect.width) || fallback); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, w] as const;
}

interface TipState { x: number; y: number; body: ReactNode }
function Tip({ tip, width }: { tip: TipState | null; width: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tw, setTw] = useState(120);
  useEffect(() => { if (ref.current) setTw(ref.current.offsetWidth); });
  if (!tip) return null;
  const left = tip.x + 14 + tw > width ? Math.max(0, tip.x - tw - 14) : tip.x + 14;
  return <div ref={ref} className="tip" style={{ left, top: Math.max(0, tip.y - 44) }}>{tip.body}</div>;
}

// ---------------------------------------------------------------- sparkline
/** 26-session RS series as bars; the highest bar highlighted */
export function Sparkline({ series, w = 120, h = 22 }: { series: number[]; w?: number; h?: number }) {
  if (!series?.length) return null;
  const lo = Math.min(...series), hi = Math.max(...series), rng = hi - lo || 1;
  const n = series.length, gap = 1.5, bw = (w - gap * (n - 1)) / n;
  let top = 0;
  series.forEach((v, i) => { if (v > series[top]) top = i; });
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      {series.map((v, i) => {
        const bh = 3 + ((v - lo) / rng) * (h - 4);
        return <rect key={i} x={i * (bw + gap)} y={h - bh} width={bw} height={bh} rx={0.6}
          fill={i === top ? 'var(--pos)' : 'color-mix(in srgb, var(--pos) 38%, transparent)'} />;
      })}
    </svg>
  );
}

// ---------------------------------------------------------------- line chart
export interface Series { values: (number | null)[]; color: string; label: string; width?: number }

/** Lines over dates with a hover crosshair; optional dashed baseline (1.0 for RS). */
export function LineChart({ dates, series, height = 220, baseline, fmt = v => v.toFixed(4), testid }: {
  dates: string[]; series: Series[]; height?: number; baseline?: number;
  fmt?: (v: number) => string; testid?: string;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const L = 8, R = 56, T = 10, B = 16;
  const pw = Math.max(50, W - L - R), ph = height - T - B, n = dates.length;
  const all = series.flatMap(s => s.values.filter((v): v is number => v != null));
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.02 || 0.01;
  const y0 = lo - pad, y1 = hi + pad;
  const X = (k: number) => L + (n > 1 ? (pw * k) / (n - 1) : pw / 2);
  const Y = (v: number) => T + ph * (1 - (v - y0) / (y1 - y0));
  const path = (vals: (number | null)[]) => {
    let d = '', pen = false;
    vals.forEach((v, k) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${X(k).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const k = Math.round(((e.clientX - r.left - L) / pw) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, k)));
  };
  if (!n || !all.length) return null;
  const k = hover;
  const main = k != null ? series[0].values[k] : null;
  return (
    <div className="chart" ref={ref} data-testid={testid}>
      <svg width={W} height={height} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {baseline != null && y0 < baseline && y1 > baseline &&
          <line x1={L} x2={L + pw} y1={Y(baseline)} y2={Y(baseline)} className="cross" opacity={0.7} />}
        {series.map((s, i) => <path key={i} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={s.width ?? 1.6} strokeLinejoin="round" />)}
        <text x={L + pw + 6} y={Y(y1) + 4}>{fmt(y1)}</text>
        <text x={L + pw + 6} y={Y(y0) + 4}>{fmt(y0)}</text>
        {k != null && <>
          <line x1={X(k)} x2={X(k)} y1={T} y2={T + ph} className="cross" />
          {main != null && <circle cx={X(k)} cy={Y(main)} r={3.5} fill="var(--text)" stroke="var(--surface)" strokeWidth={1.5} />}
        </>}
      </svg>
      <Tip width={W} tip={k == null ? null : {
        x: X(k), y: main != null ? Y(main) : T + ph / 2,
        body: <><b>{fmtDate(dates[k])}</b>{series.map((s, i) => s.values[k] != null &&
          <div key={i}><i className="sw" style={{ background: s.color }} />{s.label} {fmt(s.values[k] as number)}</div>)}</>,
      }} />
    </div>
  );
}

// ---------------------------------------------------------------- oscillators
/** McClellan-style breadth oscillator: green above zero, red below,
 *  ±40 extremes shaded; month / year axis.  `perPoint` px per session
 *  (the main chart scrolls horizontally), else fits the width. */
export function Oscillator({ dates, osc, height = 320, perPoint, zones = true, axis = true, testid }: {
  dates: string[]; osc: number[]; height?: number; perPoint?: number; zones?: boolean; axis?: boolean; testid?: string;
}) {
  const [ref, cw] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const n = osc.length;
  const L = axis ? 44 : 6, R = 44, T = 12, B = axis ? 40 : 12;
  const pw = perPoint ? Math.max(cw - L - R, perPoint * (n - 1)) : Math.max(50, cw - L - R);
  const W = L + pw + R, ph = height - T - B;
  const amax = Math.max(...osc.map(Math.abs), 1);
  const ymax = axis ? Math.max(20, Math.ceil(amax / 10) * 10) : Math.ceil(amax / 10) * 10 + 10;
  const X = (i: number) => L + (pw * i) / Math.max(1, n - 1);
  const Y = (v: number) => T + ph * (1 - (v + ymax) / (2 * ymax));
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => { if (perPoint && scroller.current) scroller.current.scrollLeft = scroller.current.scrollWidth; }, [perPoint, n, cw]);

  const segs = useMemo(() => {
    const out: { d: string; up: boolean }[] = [];
    for (let i = 1; i < n; i++) {
      const up = (osc[i - 1] + osc[i]) / 2 >= 0;
      const d = `M${X(i - 1).toFixed(1)},${Y(osc[i - 1]).toFixed(1)}L${X(i).toFixed(1)},${Y(osc[i]).toFixed(1)}`;
      const last = out[out.length - 1];
      if (last && last.up === up) last.d += `L${X(i).toFixed(1)},${Y(osc[i]).toFixed(1)}`; else out.push({ d, up });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [osc, pw, height]);

  const ticks: number[] = [];
  const step = ymax <= 40 ? 10 : ymax <= 80 ? 20 : 40;
  if (axis) for (let v = 0; v <= ymax + 0.1; v += step) { ticks.push(v); if (v) ticks.push(-v); }   // centred on zero
  const months: { i: number; ym: string; year: boolean }[] = [];
  if (axis) {
    let prev = '', prevY = '';
    dates.forEach((d, i) => {
      const ym = d.slice(0, 7);
      if (ym !== prev) { months.push({ i, ym, year: d.slice(0, 4) !== prevY }); prev = ym; prevY = d.slice(0, 4); }
    });
  }
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left - L) / pw) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  const scrollLeft = scroller.current?.scrollLeft ?? 0;
  return (
    <div ref={ref} data-testid={testid}>
      <div ref={scroller} className={perPoint ? 'scroll-x' : ''} style={{ position: 'relative' }}>
        <div className="chart" style={{ width: W }}>
          <svg width={W} height={height} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
            {zones && ymax > 40 && <>
              <rect x={L} y={T} width={pw} height={Y(40) - T} fill="var(--zone-up)" />
              <rect x={L} y={Y(-40)} width={pw} height={T + ph - Y(-40)} fill="var(--zone-dn)" />
            </>}
            {ticks.map(v => <g key={v}>
              <line x1={L} x2={L + pw} y1={Y(v)} y2={Y(v)} className={v === 0 ? 'zero-line' : 'grid-line'} />
              <text x={L - 8} y={Y(v) + 3.5} textAnchor="end">{v > 0 ? '+' : ''}{v}</text>
              <text x={L + pw + 8} y={Y(v) + 3.5}>{v > 0 ? '+' : ''}{v}</text>
            </g>)}
            {!axis && <line x1={L} x2={L + pw} y1={Y(0)} y2={Y(0)} className="zero-line" />}
            {months.map((m, k) => {
              const next = months[k + 1]?.i ?? n - 1;
              const mid = X((m.i + next) / 2);
              return <g key={m.ym}>
                <line x1={X(m.i)} x2={X(m.i)} y1={T} y2={T + ph} className="grid-line" strokeWidth={m.year ? 1.4 : 1} />
                {next - m.i >= 6 && <text x={mid} y={T + ph + 15} textAnchor="middle">{MON[+m.ym.slice(5) - 1]}</text>}
                {m.year && <text x={X(m.i) + 2} y={T + ph + 31} fontWeight={700} style={{ fill: 'var(--text-2)' }}>{m.ym.slice(0, 4)}</text>}
              </g>;
            })}
            {segs.map((s, i) => <path key={i} d={s.d} fill="none" stroke={s.up ? 'var(--pos)' : 'var(--neg)'} strokeWidth={axis ? 1.7 : 1.4} strokeLinejoin="round" />)}
            {n > 0 && <circle cx={X(n - 1)} cy={Y(osc[n - 1])} r={3} fill="var(--text)" />}
            {!axis && <>
              <text x={L + pw + 6} y={Y(ymax) + 9}>+{ymax}</text>
              <text x={L + pw + 6} y={Y(-ymax)}>−{ymax}</text>
            </>}
            {hover != null && <>
              <line x1={X(hover)} x2={X(hover)} y1={T} y2={T + ph} className="cross" />
              <circle cx={X(hover)} cy={Y(osc[hover])} r={3.5} fill="var(--text)" stroke="var(--surface)" strokeWidth={1.5} />
            </>}
          </svg>
          <Tip width={perPoint ? scrollLeft + cw : W} tip={hover == null ? null : {
            x: X(hover), y: Y(osc[hover]),
            body: <><b>{fmtDate(dates[hover])}</b><span className={osc[hover] >= 0 ? 'pos' : 'neg'}>{osc[hover] >= 0 ? '+' : ''}{osc[hover].toFixed(1)}</span></>,
          }} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- paired bars
export interface PairRow { k: string; a: number; b: number; partial?: boolean }

function niceStep(span: number) {
  const raw = span / 5, p = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 2.5, 5, 10].map(k => k * p).find(s => s >= raw) ?? raw;
}

/** two bars per period (FII blue, DII orange) around zero, ₹ crore axis */
export function PairBars({ rows, tick, tip, height = 300, testid }: {
  rows: PairRow[]; tick: (i: number, slot: number) => string; tip: (r: PairRow) => ReactNode; height?: number; testid?: string;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const L = 46, R = 8, T = 12, B = 30, H = height;
  const vals = rows.flatMap(r => [r.a, r.b]);
  const step = niceStep(Math.max(1, Math.max(...vals, 0) - Math.min(...vals, 0)));
  const hi = Math.ceil(Math.max(...vals, 0) / step) * step, lo = Math.floor(Math.min(...vals, 0) / step) * step;
  const y = (v: number) => T + ((hi - v) / (hi - lo || 1)) * (H - T - B);
  const slot = (W - L - R) / Math.max(1, rows.length);
  const gap = Math.min(2, slot * 0.08);
  const bw = Math.max(0.6, Math.min(14, (slot * 0.72 - gap) / 2));
  const grid: number[] = [];
  for (let v = lo; v <= hi + 1e-6; v += step) grid.push(v);
  const bar = (v: number, x: number, color: string, op: number) => {
    const y0 = y(0), y1 = y(v), h = Math.max(1, Math.abs(y1 - y0)), r = Math.min(3, bw / 2, h);
    const top = v >= 0 ? y1 : y0, bot = v >= 0 ? y0 : y1;
    const d = v >= 0
      ? `M${x},${bot}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${bot}Z`
      : `M${x},${top}V${bot - r}Q${x},${bot} ${x + r},${bot}H${x + bw - r}Q${x + bw},${bot} ${x + bw},${bot - r}V${top}Z`;
    return <path d={d} fill={color} opacity={op} />;
  };
  return (
    <div className="chart" ref={ref} data-testid={testid}>
      <svg width={W} height={H} role="img" aria-label="FII and DII net flows">
        {grid.map(v => <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className={v === 0 ? 'zero-line' : 'grid-line'} />
          <text x={L - 6} y={y(v) + 3.5} textAnchor="end">{axisCr(v)}</text>
        </g>)}
        {rows.map((r, i) => {
          const cx = L + slot * i + slot / 2, t = tick(i, slot);
          return <g key={r.k} data-col={i} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
            <rect x={L + slot * i} y={T} width={slot} height={H - T - B} fill={hover === i ? 'var(--hover)' : 'transparent'} />
            {bar(r.a, cx - gap / 2 - bw, 'var(--fii)', r.partial ? 0.55 : 1)}
            {bar(r.b, cx + gap / 2, 'var(--dii)', r.partial ? 0.55 : 1)}
            {t && <text x={cx} y={H - B + 16} textAnchor="middle">{t}</text>}
          </g>;
        })}
      </svg>
      <Tip width={W} tip={hover == null ? null : { x: L + slot * hover + slot / 2, y: 60, body: tip(rows[hover]) }} />
    </div>
  );
}

// ---------------------------------------------------------------- donut
export interface DonutSeg { name: string; n: number; color: string }
export function Donut({ segs, total, line1, line2 }: { segs: DonutSeg[]; total: number; line1: string; line2: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const R = 74, Wd = 22, C = 2 * Math.PI * R, GAP = 2;
  let off = 0;
  return (
    <div className="chart" style={{ maxWidth: 220, margin: '0 auto' }}>
      <svg viewBox="0 0 200 200" width="100%" role="img" aria-label={`${total} ${line1}, ${line2}`}>
        <circle r={R} cx={100} cy={100} fill="none" stroke="var(--surface-3)" strokeWidth={Wd} />
        {segs.map((s, i) => {
          const len = total ? (C * s.n) / total : 0;
          const dash = Math.max(0, len - (segs.length > 1 ? GAP : 0));
          const el = <circle key={i} r={R} cx={100} cy={100} fill="none" stroke={s.color} strokeWidth={hover === i ? Wd + 4 : Wd}
            strokeDasharray={`${dash.toFixed(2)} ${(C - dash).toFixed(2)}`} strokeDashoffset={(-off).toFixed(2)}
            transform="rotate(-90 100 100)" style={{ cursor: 'pointer', transition: 'stroke-width .12s' }}
            onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} />;
          off += len;
          return el;
        })}
        <text x={100} y={93} textAnchor="middle" style={{ fill: 'var(--text)', fontSize: String(total).length > 3 ? 30 : 38, fontWeight: 700 }}>{total}</text>
        <text x={100} y={113} textAnchor="middle" style={{ fontSize: 11, fill: 'var(--text-2)' }}>{line1}</text>
        <text x={100} y={128} textAnchor="middle" style={{ fontSize: 11, fill: 'var(--text-2)' }}>{line2}</text>
      </svg>
      {hover != null && <div className="tip" style={{ left: '50%', top: -8, transform: 'translateX(-50%)' }}>
        <b>{segs[hover].name}</b>{segs[hover].n} stock{segs[hover].n === 1 ? '' : 's'} · {total ? Math.round((segs[hover].n / total) * 100) : 0}%
      </div>}
    </div>
  );
}

// ---------------------------------------------------------------- KPI minis
/** smooth area sparkline (KPI cards), coloured by the last value's sign or a fixed colour */
export function AreaSpark({ values, color, height = 36, zero = false }: { values: number[]; color?: string; height?: number; zero?: boolean }) {
  const [ref, W] = useWidth<HTMLDivElement>(200);
  if (values.length < 2) return <div ref={ref} />;
  const lo = Math.min(...values, zero ? 0 : Infinity), hi = Math.max(...values, zero ? 0 : -Infinity), rng = hi - lo || 1;
  const X = (i: number) => (W * i) / (values.length - 1);
  const Y = (v: number) => 2 + (height - 4) * (1 - (v - lo) / rng);
  const c = color ?? (values[values.length - 1] >= 0 ? 'var(--pos)' : 'var(--neg)');
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('');
  const id = `g${Math.round(Math.random() * 1e9)}`;
  return (
    <div ref={ref} className="chart">
      <svg width={W} height={height} aria-hidden="true">
        <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={c} stopOpacity={0.28} /><stop offset="100%" stopColor={c} stopOpacity={0} /></linearGradient></defs>
        {zero && lo < 0 && hi > 0 && <line x1={0} x2={W} y1={Y(0)} y2={Y(0)} className="grid-line" strokeDasharray="3 3" />}
        <path d={`${line}L${W},${height}L0,${height}Z`} fill={`url(#${id})`} />
        <path d={line} fill="none" stroke={c} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={X(values.length - 1)} cy={Y(values[values.length - 1])} r={2.8} fill={c} />
      </svg>
    </div>
  );
}

/** small up / down bars (e.g. FII net per session this month) */
export function MiniBars({ values, height = 36 }: { values: number[]; height?: number }) {
  const [ref, W] = useWidth<HTMLDivElement>(200);
  const m = Math.max(...values.map(Math.abs), 1), mid = height / 2;
  const slot = W / Math.max(1, values.length), bw = Math.max(2, Math.min(10, slot * 0.6));
  return (
    <div ref={ref} className="chart">
      <svg width={W} height={height} aria-hidden="true">
        <line x1={0} x2={W} y1={mid} y2={mid} className="grid-line" />
        {values.map((v, i) => {
          const h = Math.max(1.5, (Math.abs(v) / m) * (mid - 2));
          return <rect key={i} x={slot * i + (slot - bw) / 2} y={v >= 0 ? mid - h : mid} width={bw} height={h} rx={1.5}
            fill={v >= 0 ? 'var(--pos)' : 'var(--neg)'} opacity={0.85} />;
        })}
      </svg>
    </div>
  );
}

/** semicircle gauge of the regime checks: `pass` of `total` segments lit */
export function Gauge({ pass, total, level }: { pass: number; total: number; level: 'on' | 'mixed' | 'off' }) {
  const c = level === 'on' ? 'var(--pos)' : level === 'mixed' ? 'var(--warn)' : 'var(--neg)';
  const R = 70, cx = 84, cy = 86, gap = 0.06;
  const seg = (i: number) => {
    const a0 = Math.PI + (Math.PI * i) / total + gap / 2, a1 = Math.PI + (Math.PI * (i + 1)) / total - gap / 2;
    const p = (a: number, r: number) => `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
    return `M${p(a0, R)}A${R},${R} 0 0 1 ${p(a1, R)}`;
  };
  return (
    <div className="gauge" role="img" aria-label={`${pass} of ${total} regime checks pass`}>
      <svg width={168} height={96}>
        {Array.from({ length: total }, (_, i) => <path key={i} d={seg(i)} fill="none" strokeWidth={12} strokeLinecap="round"
          stroke={i < pass ? c : 'var(--surface-3)'} style={i < pass ? { filter: `drop-shadow(0 0 6px ${c})` } : undefined} />)}
      </svg>
      <div className="gauge-v"><b>{pass}<span style={{ fontSize: 15, color: 'var(--text-3)' }}>/{total}</span></b><span>checks pass</span></div>
    </div>
  );
}
