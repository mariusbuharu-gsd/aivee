import { useEffect, useState } from 'react';
import type { DurationStat, ServiceMetrics } from '../api/client';
import { useApi } from '../api/context';
import { useLocationId } from '../auth/context';
import { duration } from '../alerts/format';

const PERIODS = [
  { value: 1, label: 'Azi' },
  { value: 7, label: '7 zile' },
  { value: 30, label: '30 de zile' },
];

const CELLS: { key: 'wait' | 'reaction' | 'travel'; label: string; hint: string }[] = [
  { key: 'wait', label: 'Așteptare', hint: 'de la alertă până ajunge cineva la masă' },
  { key: 'reaction', label: 'Reacție', hint: 'până apasă cineva „Merg eu”' },
  { key: 'travel', label: 'Drum', hint: 'de la „Merg eu” până la masă' },
];

const fmt = (s: number | null) => (s === null ? '—' : duration(s));

/** Wait / reaction / travel medians and p90 for the current location. */
export function ServiceStats() {
  const api = useApi();
  const locationId = useLocationId();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<ServiceMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const from = new Date();
    from.setHours(0, 0, 0, 0);
    from.setDate(from.getDate() - (days - 1));
    api.getServiceMetrics({ location_id: locationId, from: from.toISOString() }).then(
      (m) => alive && (setData(m), setError(null)),
      (e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      alive = false;
    };
  }, [api, locationId, days]);

  return (
    <section aria-labelledby="service-h" className="service">
      <div className="side-head">
        <h2 id="service-h">Servire</h2>
        <div className="segmented" role="group" aria-label="Perioadă">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              className="btn btn-seg"
              aria-pressed={days === p.value}
              onClick={() => setDays(p.value)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <dl className="service-grid">
        {CELLS.map((c) => {
          const s: DurationStat | undefined = data?.[c.key];
          return (
            <div key={c.key} className="service-cell">
              <dt>{c.label}</dt>
              <dd>
                <span className="service-value mono">{fmt(s?.median_s ?? null)}</span>
                <span className="small muted">mediană · p90 {fmt(s?.p90_s ?? null)}</span>
                <span className="small muted">{c.hint}</span>
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="muted small">{data ? `${data.alerts} alerte în perioadă.` : 'Se încarcă…'}</p>
    </section>
  );
}
