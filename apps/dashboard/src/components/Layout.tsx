import { NavLink, Outlet } from 'react-router';
import { useApi } from '../api/context';
import { OfflineBanner } from '../pwa/OfflineBanner';
import { useAuth } from '../auth/context';
import { useLiveData } from '../state/context';
import { Icon, Logo, type IconName } from './Icon';

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: '/', label: 'Live', icon: 'live' },
  { to: '/reguli', label: 'Reguli', icon: 'rules' },
  { to: '/alerte', label: 'Alerte', icon: 'alerts' },
  { to: '/dispozitive', label: 'Dispozitive', icon: 'devices' },
  { to: '/metrici', label: 'Metrici', icon: 'metrics' },
];

export function Layout() {
  const api = useApi();
  const { session, signOut } = useAuth();
  const { error, suggestions, alerts } = useLiveData();
  const openCount = alerts.filter((a) => a.closed_at === null).length;
  return (
    <div className="app">
      <a href="#main" className="skip">
        Sari la conținut
      </a>
      <aside className="sidebar">
        <Logo />
        <nav aria-label="Principal">
          <ul className="nav">
            {NAV.map((n) => (
              <li key={n.to}>
                <NavLink to={n.to} end={n.to === '/'} className="nav-link">
                  <Icon name={n.icon} />
                  <span>{n.label}</span>
                  {n.to === '/alerte' && openCount + suggestions.length > 0 && (
                    <span
                      className="nav-count"
                      aria-label={`${openCount + suggestions.length} noi`}
                    >
                      {openCount + suggestions.length}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-foot">
          {session && (
            <div className="account">
              <span className="account-name">{session.venue || session.name}</span>
              <span className="account-mail small muted">{session.email}</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={signOut}>
                Ieși din cont
              </button>
            </div>
          )}
          <p className="muted small mono">
            {api.kind === 'mock' ? 'date demo (mock)' : 'conectat la API'}
          </p>
        </div>
      </aside>
      <main id="main" className="main">
        <OfflineBanner />
        {error && (
          <p className="banner-error" role="alert">
            Eroare de conectare: {error}
          </p>
        )}
        <Outlet />
      </main>
    </div>
  );
}
