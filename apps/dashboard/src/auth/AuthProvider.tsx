import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, UNAUTHORIZED_EVENT, type Me, type Permission } from '../api/client';
import { useApi } from '../api/context';
import { AuthContext, type AuthState } from './context';
import { loadLocationId, saveLocationId } from './session';

export function AuthProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<AuthState['status']>('loading');
  const [locationId, setLocationId] = useState<string | null>(loadLocationId);

  /** Pick the remembered location when still allowed, else the first one; scope the API to it. */
  const adopt = useCallback(
    (next: Me | null) => {
      setMe(next);
      setStatus(next ? 'authed' : 'anon');
      if (!next) {
        api.setLocation(null);
        return;
      }
      setLocationId((prev) => {
        const id = next.locations.find((l) => l.id === prev)?.id ?? next.locations[0]?.id ?? null;
        api.setLocation(id);
        saveLocationId(id);
        return id;
      });
    },
    [api],
  );

  useEffect(() => {
    let alive = true;
    api.me().then(
      (m) => alive && adopt(m),
      (e: unknown) => {
        if (!alive) return;
        if (!(e instanceof ApiError) || e.status !== 401) console.warn('auth/me', e);
        adopt(null);
      },
    );
    const onUnauthorized = () => {
      setMe(null);
      setStatus('anon');
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      alive = false;
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, [api, adopt]);

  const location = me?.locations.find((l) => l.id === locationId) ?? null;

  const value = useMemo<AuthState>(
    () => ({
      status,
      me,
      location,
      setLocation: (id) => {
        api.setLocation(id);
        saveLocationId(id);
        setLocationId(id);
      },
      can: (p: Permission) =>
        !!location?.permissions.includes(p) || (p === 'locations.manage' && !!me?.is_owner),
      login: async (email, password) => adopt(await api.login(email.trim(), password)),
      register: async (input) => adopt(await api.register(input)),
      acceptInvite: async (token, input) => adopt(await api.acceptInvite(token, input)),
      logout: async () => {
        try {
          await api.logout();
        } finally {
          adopt(null);
        }
      },
      refresh: async () => adopt(await api.me()),
    }),
    [api, adopt, location, me, status],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
