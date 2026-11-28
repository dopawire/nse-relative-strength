import { useEffect, useMemo } from 'react';
import { useAllLevels, useMeta, useStock } from '../api/client';
import { CAP_LABEL, fmtPrice, sgn, shortName } from '../lib/format';
import { stockIndex } from '../lib/market';
import { tvSym, copyText } from '../lib/tv';
import { useApp } from './AppContext';
import { LineChart } from './charts';
import { IconCopy, IconStar, IconX } from './Icons';
import { EvBadge, Loading } from './ui';

/** RS line (stock ÷ NIFTY 500) with its 21-day EMA, plus the stock's key numbers. */
export function StockModal() {
  const { stock, closeStock, watch, toggleWatch, toast } = useApp();
  const { data, isLoading, error } = useStock(stock);
  const { levels } = useAllLevels();
  const meta = useMeta().data;
  const m = useMemo(() => (levels && stock ? stockIndex(levels).find(x => x.s === stock) : undefined), [levels, stock]);
  const ipo = meta?.ipo.find(i => i.s === stock);

  useEffect(() => {
    if (!stock) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeStock(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [stock, closeStock]);
  if (!stock) return null;

  const name = data?.name || m?.n || ipo?.n || stock;
  const chart = data ? { dates: data.dates, rs: data.rs, ema: data.ema21, ltp: data.ltp, above: data.rse === 1 }
    : ipo?.rs && ipo.dates && ipo.ema21 && ipo.rs.length > 1
      ? { dates: ipo.dates, rs: ipo.rs, ema: ipo.ema21, ltp: ipo.ltp, above: ipo.rs[ipo.rs.length - 1] >= ipo.ema21[ipo.ema21.length - 1] }
      : null;
  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) closeStock(); }} data-testid="stock-modal">
      <div className="modal" role="dialog" aria-modal="true" aria-label={`${name} chart`}>
        <div className="modal-h">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2>{shortName(name)}</h2>
            <div className="soft" style={{ fontSize: 12.5 }}>
              <span style={{ fontFamily: 'var(--mono)' }}>NSE:{stock}</span>
              {m?.cap && <> · {CAP_LABEL[m.cap] ?? m.cap}</>}
              {m?.industry && <> · {m.industry}</>}
              <EvBadge ev={m?.ev} />
            </div>
          </div>
          <button className={`btn sm ${watch.has(stock) ? 'ok' : ''}`} onClick={() => toggleWatch(stock)} title="watchlist">
            <IconStar />{watch.has(stock) ? 'Watching' : 'Watch'}
          </button>
          <button className="btn sm" onClick={async () => toast((await copyText(tvSym(stock))) ? `Copied ${tvSym(stock)}` : 'Copy failed')}>
            <IconCopy />TradingView
          </button>
          <button className="btn icon ghost" onClick={closeStock} aria-label="Close"><IconX /></button>
        </div>
        <div className="modal-b">
          {m && <div className="kv">
            <div>Price<b>{fmtPrice(m.l)}</b></div>
            <div>RS rating<b>{m.rr ?? '—'}</b></div>
            <div>RS_STS%<b>{Math.round(m.p * 100)}%</b></div>
            <div>1W / 1M<b><span className={(m.w1 ?? 0) >= 0 ? 'pos' : 'neg'}>{sgn(m.w1)}</span> / <span className={(m.m1 ?? 0) >= 0 ? 'pos' : 'neg'}>{sgn(m.m1)}</span></b></div>
            <div>Off 52w high<b>{m.h == null ? '—' : `${m.h.toFixed(1)}%`}</b></div>
            <div>ADR<b>{m.a == null ? '—' : `${m.a.toFixed(1)}%`}</b></div>
            <div>₹ cr/day<b>{m.tv == null ? '—' : m.tv.toFixed(0)}</b></div>
            {m.wk && <div>vs 10W SMA<b>{sgn(m.wk.d)}</b></div>}
          </div>}
          {isLoading && !chart && <Loading />}
          {chart ? <>
            <div className="legend" style={{ marginBottom: 6 }}>
              <span><i style={{ background: 'var(--accent)' }} />RS line (stock ÷ NIFTY 500)</span>
              <span><i style={{ background: 'var(--warn)' }} />EMA21</span>
              <span className="muted">{chart.above ? 'RS line above its EMA21' : 'RS line below its EMA21'}</span>
            </div>
            <LineChart testid="stock-chart" dates={chart.dates} height={280} baseline={1}
              series={[{ values: chart.rs, color: 'var(--accent)', label: 'RS', width: 1.7 },
                { values: chart.ema, color: 'var(--warn)', label: 'EMA21', width: 1.3 }]} />
          </> : !isLoading && <div className="empty">{error ? 'No chart for this symbol.' : ''}</div>}
        </div>
      </div>
    </div>
  );
}
