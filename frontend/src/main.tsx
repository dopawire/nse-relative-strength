import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { initialTheme } from './components/AppContext';
import './styles/app.css';

// theme before first paint (no flash)
document.documentElement.dataset.theme = initialTheme();

// old hash links (#/swing) from the pre-2.0 site → real paths
if (window.location.hash.startsWith('#/')) {
  const tab = window.location.hash.slice(2);
  const map: Record<string, string> = { ipo: '/listings', macro: '/rankings/macro', sector: '/rankings/sector',
    industry: '/rankings/industry', basic: '/rankings/basic' };
  window.history.replaceState(null, '', map[tab] ?? `/${tab}`);
}

const qc = new QueryClient({
  defaultOptions: { queries: { retry: (n, e) => n < 2 && !(e as { status?: number }).status, refetchOnWindowFocus: true } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
