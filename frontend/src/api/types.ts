// Shapes of the FastAPI responses (backend/main.py, backend/models.py).

export interface IpoWatch {
  n: string; s: string; first: string; days: number;
  base: number | null; ltp: number; ret: number | null; bret: number | null; xret: number | null;
  uc?: boolean; eta: number;
  dates?: string[]; rs?: number[]; ema21?: number[];
}

export interface Meta {
  benchmark: string; window: number; drange: string; generated: string;
  n_stocks: number; n_groups_per_level: number[]; n_window: number;
  excluded: string[]; illiquid: string[]; src: Record<string, string>; ipo: IpoWatch[];
}

export interface LevelSummary { key: string; label: string; n_groups: number }

export interface IpoInfo { d: string; p: number | null; n: number; g: number | null; x: number | null }
export interface WeeklyInfo { s: number; d: number | null; u: number; n: number }
export interface HtfInfo {
  p: number; g: number; pw: number; fd: number; fw: number; dist: number;
  dry: number | null; bo: number | null; et: number | null; es: number | null; eb: number | null;
  vx: number | null; bod?: string | null; ebd?: string | null;
}

export interface Member {
  n: string; s: string; r: number[]; p: number; e: number[]; b: number;
  d?: number | null; l?: number | null; h: number | null; a: number | null; nw?: number | null;
  m1?: number | null; m3?: number | null; d1?: number | null; w1?: number | null;
  cap?: string | null; tv?: number | null; rr?: number | null; vr?: number | null; vd?: number | null;
  tt?: number | null; dl?: number | null; dla?: number | null; ev?: string | null;
  ipo?: IpoInfo | null; wk?: WeeklyInfo | null; htf?: HtfInfo | null;
}

export interface Group { id: number; name: string; n: number; pct: number; dp?: number | null; r: number[]; members: Member[] }
export interface Level { key: string; label: string; groups: Group[] }

export interface MacroBreadth { name: string; dates: string[]; osc: number[]; latest: number }
export interface Breadth {
  dates: string[]; osc: number[]; n: number; latest: number; span: string;
  macros: MacroBreadth[]; divergence: { state?: string; note?: string }; market: Record<string, unknown>;
}

export interface Rotation { dates: string[]; groups: { name: string; rs: number[] }[] }

export interface FlowMonth { m: string; fb: number; fs: number; fii: number; db: number; ds: number; dii: number; to?: string | null }
export interface FlowDay { d: string; fii: number; dii: number; fb?: number | null; fs?: number | null; db?: number | null; ds?: number | null }
export interface Flows { months: FlowMonth[]; days: FlowDay[]; asof: string | null; src: string }

export interface StockDetail { sym: string; name: string; dates: string[]; rs: number[]; ema21: number[]; ltp: number; rse: number }

export type RegimeLevel = 'on' | 'mixed' | 'off';
export interface RegimeCheck { t: string; ok: boolean | null; v: string }
export interface GroupRow {
  name: string; quad: 'Leading' | 'Improving' | 'Weakening' | 'Lagging'; score: number;
  m1: number | null; m3: number | null; w1?: number | null; rel1: number | null; rel3?: number | null;
  p50: number | null; lead: number; nearHi?: number | null; inds?: string[]; leaders?: string[]; sector?: string; n?: number;
}
export interface Decide {
  asof: string;
  regime: { level: RegimeLevel; pass: number; known: number; checks: RegimeCheck[] };
  base: { m1: number | null; m3: number | null };
  sectors: GroupRow[]; industries: GroupRow[]; caps: GroupRow[];
  focus: string[]; turning: string[]; avoid: string[]; cap: string | null;
  lead_ind: string[]; hot: string[];
  breakouts: string[]; pullbacks: string[]; extended: string[]; ipos: string[]; weekly: string[]; htf: string[];
  rules: Record<string, number | number[]>;
  ipo_rules: Record<string, number>; weekly_rules: Record<string, number>;
  htf_rules: Record<string, number | number[]>;
  tags: Record<string, string[]>;
}

export interface ListStat { n: number; ret: number; ex: number; hit: number }
export interface EdgeStat { n: number; avg: number; hit: number }
export interface TrackHorizon {
  days: number; focus: EdgeStat | null; avoid: EdgeStat | null; cap: EdgeStat | null;
  brk: ListStat | null; pb: ListStat | null; ipo: ListStat | null; wkl: ListStat | null; htf: ListStat | null;
  regime: Record<string, { n: number; nifty: number; up: number }>;
  brk_regime: Record<string, { n: number; ex: number; hit: number }>;
}
export interface TrackRow {
  date: string; bt?: boolean; regime: RegimeLevel; focus: string[]; cap: string | null;
  h: Record<string, { focus?: number | null } & Record<string, unknown>>;
}
export interface Track { n?: number; since?: string; live_since?: string | null; rows?: TrackRow[]; summary?: Record<string, TrackHorizon> }

export interface Me {
  user: string; role: 'admin' | 'viewer'; auth: boolean;
  can: { update_prices: boolean; refresh_stocks: boolean; edit_watchlist: boolean };
}

export interface PipelineStatus {
  running: boolean; task: string | null; started_at: string | null; finished_at: string | null;
  last_result: string | null; last_output: string;
}
