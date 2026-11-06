import { useEffect, useState } from 'react';
import type { DurationStat, ServiceMetrics } from '../api/client';
import { useApi } from '../api/context';
import { useLocationId } from '../auth/context';
import { duration } from '../alerts/format';
import { Banner } from '../ui/Banner';

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
  const [prev, setPrev] = useState<ServiceMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const from = new Date();
    from.setHours(0, 0, 0, 0);
    from.setDate(from.getDate() - (days - 1));
    const before = new Date(from);
    before.setDate(before.getDate() - days);
    api.getServiceMetrics({ location_id: locationId, from: from.toISOString() }).then(
      (m) => alive && (setData(m), setError(null)),
      (e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)),
    );
    // The same span just before, so "1 min 44 s" has something to be compared with.
    api
      .getServiceMetrics({
        location_id: locationId,
        from: before.toISOString(),
        to: from.toISOString(),
      })
      .then(
        (m) => alive && setPrev(m),
        () => alive && setPrev(null),
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
        <Banner tone="error" title="Nu am putut încărca servirea.">
          {error}
        </Banner>
      )}
      <dl className="service-grid">
        {CELLS.map((c) => {
          const s: DurationStat | undefined = data?.[c.key];
          const p: DurationStat | undefined = prev?.[c.key];
          return (
            <div key={c.key} className="service-cell">
              <dt>{c.label}</dt>
              <dd>
                <span className="service-value mono">{fmt(s?.median_s ?? null)}</span>
                <span className="small muted">
                  mediană · p90 {fmt(s?.p90_s ?? null)}
                  {s ? ` · din ${s.count} ${s.count === 1 ? 'alertă' : 'alerte'}` : ''}
                </span>
                <Delta now={s?.median_s ?? null} before={p?.median_s ?? null} days={days} />
                <span className="small muted">{c.hint}</span>
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="muted small">{data ? `${data.alerts} alerte în perioadă.` : 'Se încarcă…'}</p>
      <WaitTrend />
    </section>
  );
}

const SINCE: Record<number, string> = {
  1: 'față de ieri',
  7: 'față de cele 7 zile dinainte',
  30: 'față de cele 30 de zile dinainte',
};

/** Shorter is better for every measure here: down is good news. */
function Delta({ now, before, days }: { now: number | null; before: number | null; days: number }) {
  if (now === null || before === null) return null;
  const d = Math.round(now - before);
  if (Math.abs(d) < 1) return <span className="delta small">la fel ca înainte</span>;
  const better = d < 0;
  return (
    <span className={`delta small ${better ? 'is-better' : 'is-worse'}`}>
      {better ? '↓' : '↑'} {duration(Math.abs(d))} {SINCE[days] ?? ''}
    </span>
  );
}

/** Median wait per day over the last 7 days. */
function WaitTrend() {
  const api = useApi();
  const locationId = useLocationId();
  const [days, setDays] = useState<{ day: Date; wait: number | null }[] | null>(null);
  useEffect(() => {
    let alive = true;
    const spans = Array.from({ length: 7 }, (_, i) => {
      const from = new Date();
      from.setHours(0, 0, 0, 0);
      from.setDate(from.getDate() - (6 - i));
      const to = new Date(from);
      to.setDate(to.getDate() + 1);
      return { from, to };
    });
    Promise.all(
      spans.map(({ from, to }) =>
        api
          .getServiceMetrics({
            location_id: locationId,
            from: from.toISOString(),
            to: to.toISOString(),
          })
          .then((m) => ({ day: from, wait: m.wait.median_s })),
      ),
    ).then(
      (rows) => alive && setDays(rows),
      () => alive && setDays(null),
    );
    return () => {
      alive = false;
    };
  }, [api, locationId]);
  if (!days || days.every((d) => d.wait === null)) return null;
  const max = Math.max(...days.map((d) => d.wait ?? 0), 1);
  return (
    <figure className="trend">
      <figcaption className="small muted">Așteptarea pe zile (mediană), ultimele 7 zile</figcaption>
      <ol className="trend-bars">
        {days.map((d) => {
          const label = d.day.toLocaleDateString('ro-RO', { weekday: 'short' });
          return (
            <li key={d.day.toISOString()} aria-label={`${label}: ${fmt(d.wait)}`}>
              <span className="trend-value mono small">{fmt(d.wait)}</span>
              <span
                className="trend-bar"
                style={{ height: `${d.wait === null ? 0 : Math.max(4, (d.wait / max) * 100)}%` }}
              />
              <span className="trend-day small muted">{label}</span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}
