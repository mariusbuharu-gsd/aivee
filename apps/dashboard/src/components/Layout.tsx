import { NavLink, Outlet } from 'react-router';
import { useApi } from '../api/context';
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
        <p className="sidebar-foot muted small mono">
          {api.kind === 'mock' ? 'date demo (mock)' : 'conectat la API'}
        </p>
      </aside>
      <main id="main" className="main">
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
