import { useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../auth/context';
import { ServiceStats } from '../components/ServiceStats';
import { Segmented } from '../ui/controls';
import './MetricsPage.css';

const PERIODS = [
  { value: '1', label: 'Azi' },
  { value: '7', label: '7 zile' },
  { value: '30', label: '30 de zile' },
];

/** How fast guests are served. Device numbers (FPS, CPU) live on Dispozitive. */
export function MetricsPage() {
  const { can } = useAuth();
  const [period, setPeriod] = useState('7');
  return (
    <div className="page metrics-page">
      <header className="page-head">
        <h1>Metrici</h1>
        <Segmented
          label="Perioadă"
          hideLabel
          value={period}
          options={PERIODS}
          onChange={setPeriod}
        />
      </header>
      <ServiceStats days={Number(period)} />
      <details className="card terms">
        <summary>Cum citești cifrele</summary>
        <dl className="roles">
          <dt>Masă neservită</dt>
          <dd>
            Clienții stau la masă și nu a venit nimeni de la personal în timpul din regulă. Atunci
            pornește alerta.
          </dd>
          <dt>Așteptare</dt>
          <dd>
            De la alertă până ajunge cineva de la personal la masă (sau până se închide alerta).
            Clienții așteptau deja de dinainte, cât spune regula.
          </dd>
          <dt>Reacție</dt>
          <dd>De la alertă până apasă cineva „Merg eu”.</dd>
          <dt>Drum</dt>
          <dd>De la „Merg eu” până ajunge omul la masă.</dd>
        </dl>
        <p className="small muted">
          Mediana: jumătate din alerte au fost mai rapide, jumătate mai lente. p90: 9 din 10 alerte
          au fost cel mult atât.
        </p>
      </details>
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
