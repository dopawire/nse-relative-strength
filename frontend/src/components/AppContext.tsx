import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { getWatchlist, putWatchlist } from '../api/client';
import type { Me } from '../api/types';

type Theme = 'dark' | 'light';
interface AppCtx {
  me: Me;
  theme: Theme; toggleTheme: () => void;
  toast: (msg: string) => void;
  openStock: (sym: string) => void; stock: string | null; closeStock: () => void;
  watch: Set<string>; toggleWatch: (sym: string) => void;
}

const Ctx = createContext<AppCtx | null>(null);
export const useApp = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error('useApp outside <AppProvider>');
  return c;
};

const store = {
  get(k: string) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

export function initialTheme(): Theme {
  const saved = store.get('rs-theme');
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function AppProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [msg, setMsg] = useState<string | null>(null);
  const [stock, setStock] = useState<string | null>(null);
  const [watch, setWatch] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(store.get('rs_watchlist') || '[]')); } catch { return new Set(); }
  });
  const timer = useRef<number>();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    store.set('rs-theme', theme);
  }, [theme]);

  const toast = useCallback((m: string) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(null), 2400);
  }, []);

  // Admins: the stars are mirrored to the server's watchlist file, which the
  // evening Telegram brief alerts on.  Merge the server's list once at start.
  useEffect(() => {
    if (!me.can.edit_watchlist) return;
    getWatchlist().then(r => {
      setWatch(prev => {
        const merged = new Set([...prev, ...(r.symbols || [])]);
        if (merged.size !== (r.symbols || []).length) putWatchlist([...merged]).catch(() => {});
        return merged;
      });
    }).catch(() => {});
  }, [me.can.edit_watchlist]);

  const toggleWatch = useCallback((sym: string) => {
    setWatch(prev => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym); else next.add(sym);
      store.set('rs_watchlist', JSON.stringify([...next]));
      if (me.can.edit_watchlist) putWatchlist([...next]).catch(() => {});
      return next;
    });
  }, [me.can.edit_watchlist]);

  const value = useMemo<AppCtx>(() => ({
    me, theme, toggleTheme: () => setTheme(t => (t === 'dark' ? 'light' : 'dark')),
    toast, openStock: setStock, stock, closeStock: () => setStock(null), watch, toggleWatch,
  }), [me, theme, toast, stock, watch, toggleWatch]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {msg && <div className="toast" role="status">{msg}</div>}
    </Ctx.Provider>
  );
}
