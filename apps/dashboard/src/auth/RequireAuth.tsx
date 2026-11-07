import { Navigate, Outlet, useLocation } from 'react-router';
import type { Permission } from '../api/client';
import { useAuth } from './context';
import { Loading } from '../ui/Eyes';

/** Nested routes for a signed-in user; otherwise /intra, and back to this URL afterwards. */
export function RequireAuth() {
  const { status, me } = useAuth();
  const location = useLocation();
  if (status === 'loading') {
    return <Loading page>Se încarcă…</Loading>;
  }
  if (status === 'anon' || !me) {
    const next = location.pathname + location.search;
    return (
      <Navigate to={next === '/' ? '/intra' : `/intra?next=${encodeURIComponent(next)}`} replace />
    );
  }
  // A new owner has no location yet: the first stop is creating one.
  if (me.locations.length === 0 && location.pathname !== '/locatii') {
    return <Navigate to="/locatii" replace />;
  }
  return <Outlet />;
}

/** Hides a page the role cannot use (the API refuses it anyway). */
export function RequirePermission({ any }: { any: Permission[] }) {
  const { can } = useAuth();
  return any.some(can) ? <Outlet /> : <Navigate to="/" replace />;
}
