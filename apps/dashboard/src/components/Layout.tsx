import { NavLink, Outlet } from 'react-router';
import type { Permission } from '../api/client';
import { useApi } from '../api/context';
import { OfflineBanner } from '../pwa/OfflineBanner';
import { useAuth } from '../auth/context';
import { ROLE_LABEL } from '../auth/session';
import { useLiveData } from '../state/context';
import { Icon, Logo, type IconName } from './Icon';

/** A link shows when the role holds any of `any` at the current location. */
const NAV: { to: string; label: string; icon: IconName; any: Permission[] }[] = [
  { to: '/', label: 'Live', icon: 'live', any: ['alerts.view'] },
  { to: '/alerte', label: 'Alerte', icon: 'alerts', any: ['alerts.view'] },
  { to: '/reguli', label: 'Reguli', icon: 'rules', any: ['rules.manage'] },
  { to: '/dispozitive', label: 'Dispozitive', icon: 'devices', any: ['devices.manage'] },
  { to: '/metrici', label: 'Metrici', icon: 'metrics', any: ['alerts.view'] },
  { to: '/istoric', label: 'Istoric', icon: 'history', any: ['audit.view', 'audit.view.own'] },
  { to: '/echipa', label: 'Echipă', icon: 'team', any: ['users.manage'] },
  { to: '/locatii', label: 'Locații', icon: 'location', any: ['locations.manage'] },
];

export function Layout() {
  const api = useApi();
  const { me, location, setLocation, can, logout } = useAuth();
  const { error, suggestions, alerts } = useLiveData();
  const openCount = alerts.filter((a) => a.closed_at === null).length;
  const badge = openCount + (can('staff.review') ? suggestions.length : 0);
  const locations = me?.locations ?? [];
  return (
    <div className="app">
      <a href="#main" className="skip">
        Sari la conținut
      </a>
      <aside className="sidebar">
        <Logo />
        {locations.length > 1 ? (
          <label className="loc-switch">
            <span className="sr-only">Locația</span>
            <Icon name="location" size={16} />
            <select
              id="location-switch"
              value={location?.id ?? ''}
              onChange={(e) => setLocation(e.target.value)}
            >
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          location && (
            <p className="loc-switch is-static">
              <Icon name="location" size={16} />
              <span>{location.name}</span>
            </p>
          )
        )}
        <nav aria-label="Principal">
          <ul className="nav">
            {NAV.filter((n) => n.any.some(can)).map((n) => (
              <li key={n.to}>
                <NavLink to={n.to} end={n.to === '/'} className="nav-link">
                  <Icon name={n.icon} />
                  <span>{n.label}</span>
                  {n.to === '/alerte' && badge > 0 && (
                    <span className="nav-count" aria-label={`${badge} noi`}>
                      {badge}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-foot">
          {me && (
            <div className="account">
              <span className="account-name">{me.user.name}</span>
              <span className="account-mail small muted">
                {location ? ROLE_LABEL[location.role] : 'Proprietar'} · {me.user.email}
              </span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void logout()}>
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
