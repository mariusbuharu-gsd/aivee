import { lazy, Suspense, type ComponentType, type ReactNode } from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router';
import { useAuth } from './auth/context';
import { RequireAuth, RequirePermission } from './auth/RequireAuth';
import { Layout } from './components/Layout';
import { LivePage } from './pages/LivePage';
import { LoginPage } from './pages/LoginPage';
import { CapabilitiesProvider, RequireCapability } from './state/capabilities';
import { LiveDataProvider } from './state/LiveData';
import { Skeleton } from './ui/controls';

/** A page as its own chunk: the first screen (login, Live) stays in the main bundle. */
function page<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(async () => ({ default: (await load())[name] }));
}

const AlertsPage = page(() => import('./pages/AlertsPage'), 'AlertsPage');
const DevicesPage = page(() => import('./pages/DevicesPage'), 'DevicesPage');
const HistoryPage = page(() => import('./pages/HistoryPage'), 'HistoryPage');
const InvitePage = page(() => import('./pages/InvitePage'), 'InvitePage');
const LocationsPage = page(() => import('./pages/LocationsPage'), 'LocationsPage');
const MetricsPage = page(() => import('./pages/MetricsPage'), 'MetricsPage');
const NewStaffPage = page(() => import('./pages/NewStaffPage'), 'NewStaffPage');
const PhoneCameraPage = page(() => import('./pages/PhoneCameraPage'), 'PhoneCameraPage');
const RegisterPage = page(() => import('./pages/RegisterPage'), 'RegisterPage');
const RulesPage = page(() => import('./pages/RulesPage'), 'RulesPage');
const TeamPage = page(() => import('./pages/TeamPage'), 'TeamPage');
const VideoPage = page(() => import('./pages/VideoPage'), 'VideoPage');
const ZonesPage = page(() => import('./pages/ZonesPage'), 'ZonesPage');

/** Public pages outside the app shell wait for their chunk here. */
const pub = (el: ReactNode) => (
  <Suspense fallback={<Skeleton rows={1} label="Se încarcă" />}>{el}</Suspense>
);

/** Shared data reloads from scratch when the user switches location. */
function LocationScope() {
  const { location } = useAuth();
  return (
    <CapabilitiesProvider>
      <LiveDataProvider key={location?.id ?? 'none'}>
        <Outlet />
      </LiveDataProvider>
    </CapabilitiesProvider>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="intra" element={<LoginPage />} />
      <Route path="cont-nou" element={pub(<RegisterPage />)} />
      <Route path="invitatie/:token" element={pub(<InvitePage />)} />
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
            <Route element={<RequirePermission any={['staff.enrol']} />}>
              <Route path="angajat-nou" element={<NewStaffPage />} />
            </Route>
            <Route element={<RequirePermission any={['devices.manage']} />}>
              <Route path="dispozitive" element={<DevicesPage />} />
              {/* The page is called "Camere" now; the old path stays the canonical one. */}
              <Route path="camere" element={<Navigate to="/dispozitive" replace />} />
              <Route path="camere/:cameraId/zone" element={<ZonesPage />} />
              <Route element={<RequireCapability name="videos" />}>
                <Route path="video" element={<VideoPage />} />
              </Route>
              <Route path="telefon" element={<PhoneCameraPage />} />
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
