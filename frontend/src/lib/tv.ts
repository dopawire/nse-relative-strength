// TradingView export: NSE symbols, clipboard, .txt download.

/** TradingView writes '&' and '-' as '_': M&M → NSE:M_M, BAJAJ-AUTO → NSE:BAJAJ_AUTO */
export const tvSym = (s: string) => 'NSE:' + s.replace(/[&-]/g, '_');

/** comma-separated list for a watchlist's add-symbol box */
export const tvList = (syms: string[]) => syms.map(tvSym).join(',');

/** one importable watchlist file with a ### section per list */
export const tvSections = (sections: { name: string; syms: string[] }[]) =>
  sections.filter(s => s.syms.length).map(s => `###${s.name},${tvList(s.syms)}`).join(',');

export async function copyText(txt: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(txt);
      return true;
    }
  } catch { /* fall back below */ }
  const ta = document.createElement('textarea');
  ta.value = txt;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

export function saveText(txt: string, name: string, type = 'text/plain') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([txt], { type }));
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}
