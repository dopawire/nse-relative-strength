import type { ReactNode } from 'react';
import { parseEvent, sgn, fmtDay } from '../lib/format';
import { useApp } from './AppContext';

export function Card({ title, count, sub, tools, children, flush, id, className }: {
  title?: ReactNode; count?: ReactNode; sub?: ReactNode; tools?: ReactNode; children?: ReactNode;
  flush?: boolean; id?: string; className?: string;
}) {
  return (
    <section className={`card ${className ?? ''}`} id={id} data-testid={id}>
      {(title || tools) && (
        <div className="card-h">
          <div>
            {title && <div className="card-t">{title}{count != null && <span className="count">{count}</span>}</div>}
            {sub && <div className="card-s">{sub}</div>}
          </div>
          {tools && <div className="card-tools">{tools}</div>}
        </div>
      )}
      <div className={`card-b ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label, testid }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label?: string; testid?: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label} data-testid={testid}>
      {options.map(o => (
        <button key={o.value} type="button" className={o.value === value ? 'on' : ''}
          aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export const Loading = ({ what = 'Loading' }: { what?: string }) => <div className="loading">{what}</div>;
export const ErrorBox = ({ error }: { error: unknown }) =>
  <div className="error">Couldn't load this: {error instanceof Error ? error.message : String(error)}</div>;
export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;

/** signed, coloured percent */
export const Tone = ({ v, dp = 1 }: { v: number | null | undefined; dp?: number }) =>
  v == null ? <span className="muted">—</span> : <span className={v >= 0 ? 'pos' : 'neg'}>{sgn(v, dp)}</span>;

export function Stat({ label, value, sub, tone, testid }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: 'pos' | 'neg'; testid?: string;
}) {
  return (
    <div className="card stat" data-testid={testid}>
      <div className="stat-l">{label}</div>
      <div className={`stat-v ${tone ?? ''}`}>{value}</div>
      {sub && <div className="stat-s">{sub}</div>}
    </div>
  );
}

/** a stock symbol that opens its RS chart */
export function StockLink({ sym, name }: { sym: string; name?: string }) {
  const { openStock } = useApp();
  return <button type="button" className="stk-link" title={name ?? sym} onClick={() => openStock(sym)}>{sym}</button>;
}

/** upcoming corporate event within 14 days — results get the loud badge */
export function EvBadge({ ev }: { ev?: string | null }) {
  const e = parseEvent(ev);
  if (!e) return null;
  const tip = `${e.what} on ${e.date} — ${e.results ? 'results can gap the stock past any stop: avoid holding through them' : 'corporate event'}`;
  return <span className={`ev ${e.results ? 'res' : ''}`} title={tip}>{e.results ? '⚠ ' : ''}{e.short} {fmtDay(e.date)}</span>;
}

/** green-intensity background for an RS_STS% value 0..1 */
export function rsPillStyle(pct: number, dark: boolean) {
  const p = Math.max(0, Math.min(1, pct));
  if (dark) {
    const a = 0.12 + p * 0.78;
    return { background: `rgba(52,199,123,${a.toFixed(3)})`, color: p > 0.5 ? '#06130c' : 'var(--text)' };
  }
  const r = Math.round(255 + (34 - 255) * p), g = Math.round(255 + (160 - 255) * p), b = Math.round(255 + (96 - 255) * p);
  return { background: `rgb(${r},${g},${b})`, color: p > 0.55 ? '#fff' : '#0b3d24', boxShadow: 'inset 0 0 0 1px rgba(15,23,38,.06)' };
}
