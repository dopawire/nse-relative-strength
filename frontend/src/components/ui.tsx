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

export const Loading = ({ what }: { what?: string }) => what ? <div className="loading">{what}</div> : <PageSkeleton />;
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

// ---------------------------------------------------------------- v2 building blocks

/** page title + subtitle + actions */
export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="ph">
      <div><h2 className="ph-t">{title}</h2>{sub && <div className="ph-s">{sub}</div>}</div>
      {actions && <div className="ph-a">{actions}</div>}
    </div>
  );
}

/** KPI: label, value, footnote, optional chart */
export function Kpi({ label, value, valueTone, sub, chart, testid }: {
  label: string; value: ReactNode; valueTone?: 'pos' | 'neg' | 'r-on' | 'r-mixed' | 'r-off'; sub?: ReactNode; chart?: ReactNode; testid?: string;
}) {
  return (
    <div className="card kpi" data-testid={testid}>
      <div className="stat-l">{label}</div>
      <div className={`stat-v ${valueTone ?? ''}`}>{value}</div>
      {sub && <div className="stat-s">{sub}</div>}
      {chart && <div className="kpi-spark">{chart}</div>}
    </div>
  );
}

/** RS rating 1-99 as a tinted badge */
export function RsBadge({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="muted">—</span>;
  const cls = v >= 95 ? 'r1' : v >= 85 ? 'r2' : v >= 70 ? 'r3' : 'r4';
  return <span className={`rr ${cls}`} title="RS rating 1-99 vs all stocks">{v}</span>;
}

/** ticker first, company name underneath (how trading tools list stocks) */
export function StockCell({ name, sym, extra }: { name: string; sym: string; extra?: ReactNode }) {
  return (
    <div className="stk">
      <span className="ticker">{sym}</span>
      <span className="stk-sym">{name}{extra}</span>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, testid }: {
  tabs: { value: T; label: string; n?: number }[]; value: T; onChange: (v: T) => void; testid?: string;
}) {
  return (
    <div className="tabs" role="tablist" data-testid={testid}>
      {tabs.map(t => <button key={t.value} role="tab" aria-selected={t.value === value} className={t.value === value ? 'on' : ''}
        onClick={() => onChange(t.value)}>{t.label}{t.n != null && <span className="n">{t.n}</span>}</button>)}
    </div>
  );
}

/** shimmering placeholders while data loads */
export function Skeleton({ h = 16, w = '100%', style }: { h?: number | string; w?: number | string; style?: React.CSSProperties }) {
  return <div className="skel" style={{ height: h, width: w, maxWidth: '100%', ...style }} />;
}
export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <Skeleton h={30} w={280} style={{ marginBottom: 10 }} /><Skeleton h={14} w={460} style={{ marginBottom: 24 }} />
      <div className="grid four">{[0, 1, 2, 3].map(i => <Skeleton key={i} h={128} />)}</div>
      <Skeleton h={260} style={{ marginTop: 18 }} />
      <div className="grid two" style={{ marginTop: 18 }}><Skeleton h={220} /><Skeleton h={220} /></div>
    </div>
  );
}
