import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuth } from './context';

/** Renders the nested routes for a signed-in owner; otherwise goes to /intra and back after. */
export function RequireAuth() {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) {
    const next = location.pathname + location.search;
    return (
      <Navigate to={next === '/' ? '/intra' : `/intra?next=${encodeURIComponent(next)}`} replace />
    );
  }
  return <Outlet />;
}
