import { Link } from 'react-router';
import { useAuth } from '../auth/context';
import { ServiceStats } from '../components/ServiceStats';

/** How fast guests are served. Device numbers (FPS, CPU) live on Dispozitive. */
export function MetricsPage() {
  const { can } = useAuth();
  return (
    <div className="page">
      <header className="page-head">
        <h1>Metrici</h1>
      </header>
      <ServiceStats />
      {can('devices.manage') && (
        <p className="muted small">
          Cifrele camerelor și ale dispozitivelor (FPS, procesor) sunt pe{' '}
          <Link to="/dispozitive" className="link">
            Dispozitive
          </Link>
          .
        </p>
      )}
    </div>
  );
}
