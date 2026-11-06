import { useEffect, useState, type ReactNode } from 'react';
import { Navigate, Outlet } from 'react-router';
import type { Capabilities } from '../api/client';
import { useApi } from '../api/context';
import { CapabilitiesContext, useCapabilities } from './capabilitiesContext';

/** Asks `GET /api/capabilities` once per API client. A failure (an older API) hides nothing. */
export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [caps, setCaps] = useState<Capabilities | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    api.getCapabilities().then(
      (c) => live && setCaps(c),
      () => live && setCaps(null),
    );
    return () => {
      live = false;
    };
  }, [api]);
  return <CapabilitiesContext.Provider value={caps}>{children}</CapabilitiesContext.Provider>;
}

/**
 * Routes for a feature this server may not run: nothing until the server answers (a moment),
 * then the page, or Live when the server says it does not run the feature.
 */
export function RequireCapability({ name }: { name: keyof Capabilities }) {
  const caps = useCapabilities();
  if (caps === undefined) return null;
  return caps && !caps[name] ? <Navigate to="/" replace /> : <Outlet />;
}
