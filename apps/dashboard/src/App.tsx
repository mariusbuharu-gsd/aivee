import { Navigate, Route, Routes } from 'react-router';
import { RequireAuth } from './auth/RequireAuth';
import { Layout } from './components/Layout';
import { AlertsPage } from './pages/AlertsPage';
import { DevicesPage } from './pages/DevicesPage';
import { LivePage } from './pages/LivePage';
import { LoginPage } from './pages/LoginPage';
import { MetricsPage } from './pages/MetricsPage';
import { RegisterPage } from './pages/RegisterPage';
import { RulesPage } from './pages/RulesPage';
import { ZonesPage } from './pages/ZonesPage';

export function App() {
  return (
    <Routes>
      <Route path="intra" element={<LoginPage />} />
      <Route path="cont-nou" element={<RegisterPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<LivePage />} />
          <Route path="camere/:cameraId/zone" element={<ZonesPage />} />
          <Route path="reguli" element={<RulesPage />} />
          <Route path="alerte" element={<AlertsPage />} />
          <Route path="dispozitive" element={<DevicesPage />} />
          <Route path="metrici" element={<MetricsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
