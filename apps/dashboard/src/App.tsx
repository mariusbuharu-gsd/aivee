import { Navigate, Outlet, Route, Routes } from 'react-router';
import { useAuth } from './auth/context';
import { RequireAuth, RequirePermission } from './auth/RequireAuth';
import { Layout } from './components/Layout';
import { AlertsPage } from './pages/AlertsPage';
import { DevicesPage } from './pages/DevicesPage';
import { HistoryPage } from './pages/HistoryPage';
import { InvitePage } from './pages/InvitePage';
import { LivePage } from './pages/LivePage';
import { LocationsPage } from './pages/LocationsPage';
import { LoginPage } from './pages/LoginPage';
import { MetricsPage } from './pages/MetricsPage';
import { RegisterPage } from './pages/RegisterPage';
import { RulesPage } from './pages/RulesPage';
import { TeamPage } from './pages/TeamPage';
import { VideoPage } from './pages/VideoPage';
import { ZonesPage } from './pages/ZonesPage';
import { LiveDataProvider } from './state/LiveData';

/** Shared data reloads from scratch when the user switches location. */
function LocationScope() {
  const { location } = useAuth();
  return (
    <LiveDataProvider key={location?.id ?? 'none'}>
      <Outlet />
    </LiveDataProvider>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="intra" element={<LoginPage />} />
      <Route path="cont-nou" element={<RegisterPage />} />
      <Route path="invitatie/:token" element={<InvitePage />} />
      <Route element={<RequireAuth />}>
        <Route element={<LocationScope />}>
          <Route element={<Layout />}>
            <Route element={<RequirePermission any={['alerts.view']} />}>
              <Route index element={<LivePage />} />
              <Route path="alerte" element={<AlertsPage />} />
              <Route path="metrici" element={<MetricsPage />} />
            </Route>
            <Route element={<RequirePermission any={['rules.manage']} />}>
              <Route path="reguli" element={<RulesPage />} />
            </Route>
            <Route element={<RequirePermission any={['devices.manage']} />}>
              <Route path="dispozitive" element={<DevicesPage />} />
              <Route path="camere/:cameraId/zone" element={<ZonesPage />} />
              <Route path="video" element={<VideoPage />} />
            </Route>
            <Route element={<RequirePermission any={['audit.view', 'audit.view.own']} />}>
              <Route path="istoric" element={<HistoryPage />} />
            </Route>
            <Route element={<RequirePermission any={['users.manage']} />}>
              <Route path="echipa" element={<TeamPage />} />
            </Route>
            <Route element={<RequirePermission any={['locations.manage']} />}>
              <Route path="locatii" element={<LocationsPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}
