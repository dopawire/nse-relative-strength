import { useState } from 'react';
import { copyText, saveText, tvList } from '../lib/tv';
import { IconCopy, IconDownload } from './Icons';

/** "Copy N for TradingView" + "⬇ .txt" for one list (every stock that passes,
 *  in rank order — the table may show fewer). */
export function TvButtons({ syms, file, shown, testid }: { syms: string[]; file: string; shown: number; testid?: string }) {
  const [done, setDone] = useState<string | null>(null);
  if (!syms.length) return null;
  const flash = (m: string) => { setDone(m); window.setTimeout(() => setDone(null), 1600); };
  const what = syms.length > shown
    ? `all ${syms.length} that pass, in rank order (the table shows the top ${shown})`
    : `the ${syms.length} stocks, in rank order`;
  return (
    <span className="card-tools" data-testid={testid}>
      <button type="button" className={`btn sm ${done ? 'ok' : ''}`} data-act="copy"
        title={`Copy ${what} as NSE:SYMBOL — paste into a TradingView watchlist's add-symbol box`}
        onClick={async () => flash((await copyText(tvList(syms))) ? `Copied ${syms.length} ✓` : 'Copy failed')}>
        <IconCopy />{done ?? `Copy ${syms.length} for TradingView`}
      </button>
      <button type="button" className="btn sm" data-act="dl" title={`Download ${what} as a .txt — TradingView: watchlist menu → Import list`}
        onClick={() => saveText(tvList(syms), file)}>
        <IconDownload />.txt
      </button>
    </span>
  );
}
