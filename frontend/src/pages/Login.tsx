import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { login } from '../api/client';
import { IconBolt, IconLayers, IconPulse, IconTarget, Logo } from '../components/Icons';

// decorative curve for the brand panel
const CURVE = [12, 14, 13, 17, 16, 21, 19, 24, 23, 29, 27, 33, 31, 38, 36, 43, 47, 45, 52, 58];

export function Login() {
  const [user, setUser] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(user.trim(), pw);
      await qc.invalidateQueries({ queryKey: ['me'] });
      const next = params.get('next');
      nav(next && next.startsWith('/') && !next.startsWith('//') ? next : '/', { replace: true });
    } catch (e2) {
      setErr((e2 as Error).message);
      setBusy(false);
    }
  };
  const W = 460, H = 120, max = Math.max(...CURVE), X = (i: number) => (W * i) / (CURVE.length - 1), Y = (v: number) => H - (v / max) * (H - 10);
  const line = CURVE.map((v, i) => `${i ? 'L' : 'M'}${X(i)},${Y(v)}`).join('');
  return (
    <div className="login-wrap">
      <aside className="login-art">
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <div className="brand-mark"><Logo /></div><b style={{ fontSize: 15 }}>NSE Relative Strength</b>
        </div>
        <div>
          <h2>Find the market's leaders before they move.</h2>
          <p>Relative strength for every NSE stock and group vs NIFTY 500, with tonight's swing setups, breadth and institutional flows.</p>
          <div className="login-feat">
            <div><i><IconTarget /></i>One clear call each evening: where to focus and how much to risk</div>
            <div><i><IconBolt /></i>Breakouts, pullbacks, high tight flags and weekly trends</div>
            <div><i><IconLayers /></i>2,500+ stocks ranked across 280 sectors and industries</div>
            <div><i><IconPulse /></i>Market breadth, rotation and FII / DII flows</div>
          </div>
          <svg className="login-chart" width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
            <defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6d8bff" stopOpacity=".45" /><stop offset="100%" stopColor="#6d8bff" stopOpacity="0" /></linearGradient></defs>
            <path d={`${line}L${W},${H}L0,${H}Z`} fill="url(#lg)" />
            <path d={line} fill="none" stroke="#9fb2ff" strokeWidth="2.5" strokeLinejoin="round" />
          </svg>
        </div>
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,.5)' }}>For research only — not investment advice.</div>
      </aside>
      <div className="login-side">
        <form className="login" onSubmit={submit} data-testid="login-form">
          <div className="brand-mark" style={{ width: 44, height: 44, borderRadius: 13 }}><Logo size={22} /></div>
          <h1>Welcome back</h1>
          <p>Sign in to your account to continue.</p>
          <label htmlFor="u">Username</label>
          <input id="u" className="input" autoComplete="username" value={user} onChange={e => setUser(e.target.value)} autoFocus required />
          <label htmlFor="p">Password</label>
          <input id="p" className="input" type="password" autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} required />
          <button className="btn primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          {err && <div className="err" role="alert">{err}</div>}
          <div className="fine">Private workspace · access is by invitation from the administrator.</div>
        </form>
      </div>
    </div>
  );
}
