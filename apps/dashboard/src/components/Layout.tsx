import { useCallback, useMemo, useRef, useState, type MouseEvent } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router';
import type { Permission } from '../api/client';
import { useApi } from '../api/context';
import { OfflineBanner } from '../pwa/OfflineBanner';
import { useAuth } from '../auth/context';
import { locationTypeLabel, ROLE_LABEL } from '../auth/session';
import { useLiveData, type LoadError } from '../state/context';
import { LeaveGuardContext, type LeaveGuard, type LeaveGuardApi } from '../state/leaveGuard';
import { Banner } from '../ui/Banner';
import { Dialog } from '../ui/Dialog';
import { Select } from '../ui/Select';
import { useToast } from '../ui/toast';
import { PHONE, useMedia } from '../ui/useMedia';
import { Icon, Logo, type IconName } from './Icon';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** A link shows when the role holds any of these at the current location. */
  any: Permission[];
}

const NAV: NavItem[] = [
  { to: '/', label: 'Live', icon: 'live', any: ['alerts.view'] },
  { to: '/alerte', label: 'Alerte', icon: 'alerts', any: ['alerts.view'] },
  { to: '/reguli', label: 'Reguli', icon: 'rules', any: ['rules.manage'] },
  { to: '/dispozitive', label: 'Dispozitive', icon: 'devices', any: ['devices.manage'] },
  { to: '/video', label: 'Analiză video', icon: 'video', any: ['devices.manage'] },
  { to: '/metrici', label: 'Metrici', icon: 'metrics', any: ['alerts.view'] },
  { to: '/istoric', label: 'Istoric', icon: 'history', any: ['audit.view', 'audit.view.own'] },
  { to: '/echipa', label: 'Echipă', icon: 'team', any: ['users.manage'] },
  { to: '/locatii', label: 'Locații', icon: 'location', any: ['locations.manage'] },
];

/** Tabs that fit the phone's bottom bar; the rest go under "Mai mult". */
const TABS = 4;

export function Layout() {
  const api = useApi();
  const { me, location, setLocation, can, logout } = useAuth();
  const { error, retry, suggestions, alerts } = useLiveData();
  const toast = useToast();
  const navigate = useNavigate();
  const phone = useMedia(PHONE);
  const [more, setMore] = useState(false);

  const guard = useRef<LeaveGuard | null>(null);
  const guardApi = useMemo<LeaveGuardApi>(
    () => ({
      set: (g) => {
        guard.current = g;
      },
      leave: (go) => {
        if (!guard.current?.(go)) go();
      },
    }),
    [],
  );

  const openCount = alerts.filter((a) => a.closed_at === null).length;
  const badge = openCount + (can('staff.review') ? suggestions.length : 0);
  const locations = me?.locations ?? [];
  const links = NAV.filter((n) => n.any.some(can));

  const follow = useCallback(
    (to: string) => (e: MouseEvent<HTMLAnchorElement>) => {
      setMore(false);
      if (!guard.current) return;
      e.preventDefault();
      guardApi.leave(() => navigate(to));
    },
    [guardApi, navigate],
  );

  function switchLocation(id: string) {
    guardApi.leave(() => {
      setLocation(id);
      const name = locations.find((l) => l.id === id)?.name;
      if (name) toast({ kind: 'info', title: `Acum vezi ${name}` });
    });
  }

  const link = (n: NavItem, tab = false) => (
    <NavLink
      to={n.to}
      end={n.to === '/'}
      className={tab ? 'tab' : 'nav-link'}
      onClick={follow(n.to)}
    >
      <Icon name={n.icon} />
      <span>{n.label}</span>
      {n.to === '/alerte' && badge > 0 && (
        <span className="nav-count" aria-label={`${badge} noi`}>
          {badge}
        </span>
      )}
    </NavLink>
  );

  const switcher =
    locations.length > 1 ? (
      <Select
        id="location-switch"
        className="loc-select"
        label="Locația"
        hideLabel
        icon={<Icon name="location" size={16} />}
        value={location?.id ?? ''}
        options={locations.map((l) => ({
          value: l.id,
          label: l.name,
          hint: `${locationTypeLabel(l.type)} · ${ROLE_LABEL[l.role]}`,
        }))}
        onChange={switchLocation}
      />
    ) : (
      location && (
        <p className="loc-switch is-static">
          <Icon name="location" size={16} />
          <span>{location.name}</span>
        </p>
      )
    );

  const account = me && (
    <div className="account">
      <span className="account-name">{me.user.name}</span>
      <span className="account-mail small muted">
        {location ? ROLE_LABEL[location.role] : 'Proprietar'} · {me.user.email}
      </span>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => void logout()}>
        Ieși din cont
      </button>
    </div>
  );

  return (
    <LeaveGuardContext.Provider value={guardApi}>
      <div className={`app ${phone ? 'is-phone' : ''}`}>
        <a href="#main" className="skip">
          Sari la conținut
        </a>
        <aside className="sidebar">
          <span title={api.kind === 'mock' ? 'Date demo (mock)' : 'Conectat la API'}>
            <Logo />
          </span>
          {switcher}
          {!phone && (
            <>
              <nav aria-label="Principal">
                <ul className="nav">
                  {links.map((n) => (
                    <li key={n.to}>{link(n)}</li>
                  ))}
                </ul>
              </nav>
              <div className="sidebar-foot">{account}</div>
            </>
          )}
        </aside>
        <main id="main" className="main">
          <OfflineBanner />
          {error && <LoadBanner error={error} onRetry={retry} />}
          <Outlet />
        </main>
        {phone && (
          <nav aria-label="Principal" className="tabbar">
            <ul>
              {links.slice(0, TABS).map((n) => (
                <li key={n.to}>{link(n, true)}</li>
              ))}
              <li>
                <button
                  type="button"
                  className="tab"
                  aria-haspopup="dialog"
                  aria-expanded={more}
                  onClick={() => setMore(true)}
                >
                  <Icon name="dots" />
                  <span>Mai mult</span>
                </button>
              </li>
            </ul>
            {more && (
              <Dialog
                title="Mai mult"
                className="dialog-sheet"
                onClose={() => setMore(false)}
                actions={
                  <button type="button" className="btn" onClick={() => setMore(false)}>
                    Închide
                  </button>
                }
              >
                {links.length > TABS && (
                  <ul className="sheet-links">
                    {links.slice(TABS).map((n) => (
                      <li key={n.to}>{link(n)}</li>
                    ))}
                  </ul>
                )}
                {account}
              </Dialog>
            )}
          </nav>
        )}
      </div>
    </LeaveGuardContext.Provider>
  );
}

/** A 403 is "you may not", not "the network is down"; only the latter offers a retry. */
function LoadBanner({ error, onRetry }: { error: LoadError; onRetry: () => void }) {
  const retry = (
    <button type="button" className="btn btn-sm" onClick={onRetry}>
      Încearcă acum
    </button>
  );
  if (error.kind === 'forbidden') {
    return (
      <Banner tone="warn" title="Nu ai acces la o parte din date.">
        {error.message} Dacă ai nevoie de ele, cere-i proprietarului alt rol.
      </Banner>
    );
  }
  if (error.kind === 'network') {
    return (
      <Banner tone="error" title="Nu ne putem conecta la server." action={retry}>
        Ce vezi acum poate fi vechi. Reîncercăm singuri la câteva secunde.
      </Banner>
    );
  }
  return (
    <Banner tone="error" title="Nu am putut încărca datele." action={retry}>
      {error.message}
    </Banner>
  );
}
