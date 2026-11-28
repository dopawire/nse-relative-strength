import { useQuery, useQueries } from '@tanstack/react-query';
import type {
  Breadth, Decide, Flows, Level, LevelSummary, Me, Meta, PipelineStatus, Rotation, StockDetail, Track,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Every state-changing call carries X-NSE-RS (the server's CSRF check);
// the session itself is an HttpOnly cookie the browser sends on its own.
export async function api<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('X-NSE-RS', '1');
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const r = await fetch(url, { ...init, headers, credentials: 'same-origin' });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); if (j && j.detail) detail = String(j.detail); } catch { /* not json */ }
    if (r.status === 401) window.dispatchEvent(new CustomEvent('nse-rs:unauthorized'));
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

const HOUR = 60 * 60 * 1000;
// rs_data.json changes once an evening (plus FII/DII patches): cache for a
// while, refetch when the window regains focus.
const opts = { staleTime: 5 * 60 * 1000, gcTime: 6 * HOUR };

export const useMe = () => useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/auth/me'), retry: false, staleTime: HOUR });
export const useMeta = () => useQuery({ queryKey: ['meta'], queryFn: () => api<Meta>('/api/meta'), ...opts });
export const useLevels = () => useQuery({ queryKey: ['levels'], queryFn: () => api<LevelSummary[]>('/api/levels'), ...opts });
export const useLevel = (key: string) =>
  useQuery({ queryKey: ['level', key], queryFn: () => api<Level>(`/api/levels/${encodeURIComponent(key)}`), ...opts });
export const useBreadth = () => useQuery({ queryKey: ['breadth'], queryFn: () => api<Breadth>('/api/breadth'), ...opts });
export const useRotation = () => useQuery({ queryKey: ['rotation'], queryFn: () => api<Rotation>('/api/rotation'), ...opts });
export const useFlows = () => useQuery({ queryKey: ['flows'], queryFn: () => api<Flows>('/api/flows'), ...opts });
export const useDecide = () => useQuery({ queryKey: ['decide'], queryFn: () => api<Decide>('/api/decide'), ...opts });
export const useTrack = () => useQuery({ queryKey: ['track'], queryFn: () => api<Track>('/api/track'), ...opts });
export const useStock = (sym: string | null) =>
  useQuery({ queryKey: ['stock', sym], queryFn: () => api<StockDetail>(`/api/stock/${encodeURIComponent(sym ?? '')}`),
    enabled: !!sym, ...opts });

export const LEVEL_KEYS = ['macro', 'sector', 'industry', 'basic'] as const;

/** All four classification levels — Focus, Swing and Scans join a stock's
 *  macro / sector / industry / sub-industry names from them. */
export function useAllLevels() {
  const qs = useQueries({
    queries: LEVEL_KEYS.map(k => ({ queryKey: ['level', k], queryFn: () => api<Level>(`/api/levels/${k}`), ...opts })),
  });
  const error = qs.find(q => q.error)?.error ?? null;
  const ready = qs.every(q => q.data);
  const levels = ready ? Object.fromEntries(LEVEL_KEYS.map((k, i) => [k, qs[i].data as Level])) as Record<string, Level> : null;
  return { levels, error, isLoading: !ready && !error };
}

export const pipelineStatus = () => api<PipelineStatus>('/api/pipeline-status');
export const startUpdate = () => api<{ status: string }>('/api/update-prices', { method: 'POST' });
export const startRefreshStocks = () => api<{ status: string }>('/api/refresh-stocks', { method: 'POST' });
export const login = (username: string, password: string) =>
  api<{ user: string; role: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
export const logout = () => api<{ ok: boolean }>('/api/auth/logout', { method: 'POST' });
export const getWatchlist = () => api<{ symbols: string[] }>('/api/watchlist');
export const putWatchlist = (symbols: string[]) =>
  api<{ symbols: string[] }>('/api/watchlist', { method: 'PUT', body: JSON.stringify({ symbols }) });
