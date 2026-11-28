import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useMe } from './api/client';
import { AppProvider } from './components/AppContext';
import { Layout } from './components/Layout';
import { Loading } from './components/ui';
import { Login } from './pages/Login';
import { Overview } from './pages/Overview';
import { Focus } from './pages/Focus';
import { Swing } from './pages/Swing';
import { Rankings } from './pages/Rankings';
import { Breadth } from './pages/Breadth';
import { RotationPage } from './pages/Rotation';
import { FlowsPage } from './pages/Flows';
import { Scans } from './pages/Scans';
import { Listings } from './pages/Listings';

export function App() {
  const me = useMe();
  const qc = useQueryClient();
  const loc = useLocation();

  // any 401 (session expired / signed out elsewhere) → back to the login page
  useEffect(() => {
    const onUnauth = () => { qc.setQueryData(['me'], null); qc.removeQueries({ predicate: q => q.queryKey[0] !== 'me' }); };
    window.addEventListener('nse-rs:unauthorized', onUnauth);
    return () => window.removeEventListener('nse-rs:unauthorized', onUnauth);
  }, [qc]);

  if (me.isLoading) return <div className="login-wrap"><Loading what="Signing in" /></div>;
  if (!me.data) {
    if (loc.pathname !== '/login') return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;
    return <Login />;
  }
  return (
    <AppProvider me={me.data}>
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="focus" element={<Focus />} />
          <Route path="swing" element={<Swing />} />
          <Route path="rankings" element={<Navigate to="/rankings/macro" replace />} />
          <Route path="rankings/:level" element={<Rankings />} />
          <Route path="listings" element={<Listings />} />
          <Route path="breadth" element={<Breadth />} />
          <Route path="rotation" element={<RotationPage />} />
          <Route path="flows" element={<FlowsPage />} />
          <Route path="scans" element={<Scans />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AppProvider>
  );
}
