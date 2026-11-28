import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { login } from '../api/client';
import { Logo } from '../components/Icons';

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
  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={submit} data-testid="login-form">
        <div className="brand-mark" style={{ width: 40, height: 40, borderRadius: 11 }}><Logo size={22} /></div>
        <h1>NSE Relative Strength</h1>
        <p>Sign in to see the rankings, setups and market data.</p>
        <label htmlFor="u">Username</label>
        <input id="u" className="input" autoComplete="username" value={user} onChange={e => setUser(e.target.value)} autoFocus required />
        <label htmlFor="p">Password</label>
        <input id="p" className="input" type="password" autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} required />
        <button className="btn primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        {err && <div className="err" role="alert">{err}</div>}
      </form>
    </div>
  );
}
