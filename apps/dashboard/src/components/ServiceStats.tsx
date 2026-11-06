import { useEffect, useState } from 'react';
import type { DurationStat, ServiceMetrics } from '../api/client';
import { useApi } from '../api/context';
import { useLocationId } from '../auth/context';
import { duration } from '../alerts/format';
import { barTones, headline, periodPhrase, serviceTarget, shortDuration } from '../metrics/insight';
import { Banner } from '../ui/Banner';
import { LookingEyes } from '../ui/Eyes';

const TILES: { key: 'reaction' | 'travel'; label: string; hint: string }[] = [
  { key: 'reaction', label: 'Reacție', hint: 'de la alertă până apasă cineva „Merg eu”' },
  { key: 'travel', label: 'Drum', hint: 'de la „Merg eu” până ajunge cineva' },
];

const fmt = (s: number | null) => (s === null ? '—' : duration(s));
const based = (s: DurationStat | undefined) =>
  s ? ` · din ${s.count} ${s.count === 1 ? 'alertă' : 'alerte'}` : '';

/**
 * How fast guests were served over the last `days` days: a sentence with the median wait and
 * how it compares with the span just before, then reaction, travel and alert count as tiles,
 * then the wait per day against the owner's own target.
 */
export function ServiceStats({ days }: { days: number }) {
  const api = useApi();
  const locationId = useLocationId();
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

  const h = data ? headline(days, data.wait.median_s, prev?.wait.median_s ?? null) : null;

  return (
    <section aria-labelledby="service-h" className="service">
      <h2 id="service-h" className="sr-only">
        Servire
      </h2>
      {error && (
        <Banner tone="error" title="Nu am putut încărca servirea.">
          {error}
        </Banner>
      )}
      <div className="service-lead">
        <p className="service-headline">
          {!h ? (
            <span className="loading">
              <LookingEyes size={36} />
              Se încarcă…
            </span>
          ) : h.value === null ? (
            h.rest
          ) : (
            <>
              Clienții au așteptat de obicei <strong>{h.value}</strong>
              {h.rest}
            </>
          )}
        </p>
        {data && data.wait.median_s !== null && (
          <p className="small muted">
            Așteptare: mediană · p90 {fmt(data.wait.p90_s)}
            {based(data.wait)} · de la alertă până ajunge cineva (sau se închide alerta)
          </p>
        )}
      </div>
      <dl className="service-grid">
        {TILES.map((c) => {
          const s: DurationStat | undefined = data?.[c.key];
          const p: DurationStat | undefined = prev?.[c.key];
          return (
            <div key={c.key} className="service-cell">
              <dt>{c.label}</dt>
              <dd>
                <span className="service-value mono">{fmt(s?.median_s ?? null)}</span>
                <Delta now={s?.median_s ?? null} before={p?.median_s ?? null} />
                <span className="small muted">
                  mediană · p90 {fmt(s?.p90_s ?? null)}
                  {based(s)}
                </span>
                <span className="small muted service-hint">{c.hint}</span>
              </dd>
            </div>
          );
        })}
        <div className="service-cell">
          <dt>Alerte</dt>
          <dd>
            <span className="service-value mono">{data ? data.alerts : '—'}</span>
            <span className="small muted">{periodPhrase(days)}</span>
          </dd>
        </div>
      </dl>
      <WaitTrend />
    </section>
  );
}

/** Shorter is better for every measure here: down is good news. */
function Delta({ now, before }: { now: number | null; before: number | null }) {
  if (now === null || before === null) return null;
  const d = Math.round(now - before);
  if (Math.abs(d) < 1) return <span className="delta small">la fel ca înainte</span>;
  const better = d < 0;
  return (
    <span className={`delta small ${better ? 'is-better' : 'is-worse'}`}>
      <span aria-hidden="true">{better ? '↓' : '↑'}</span> {duration(Math.abs(d))}
      <span className="sr-only">{better ? ' mai puțin' : ' mai mult'} decât înainte</span>
    </span>
  );
}

const TONE_WORDS = {
  slowest: 'cea mai lentă zi',
  over: 'peste țintă',
  under: 'sub țintă',
  empty: 'fără alerte',
} as const;

/** Median wait per day over the last 7 days, against the unserved-table rule's time. */
function WaitTrend() {
  const api = useApi();
  const locationId = useLocationId();
  const [days, setDays] = useState<{ day: Date; wait: number | null }[] | null>(null);
  const [target, setTarget] = useState<number | null>(null);
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
    // No rules (or no right to read them) just means no target line.
    api.listRules().then(
      (rules) => alive && setTarget(serviceTarget(rules)),
      () => alive && setTarget(null),
    );
    return () => {
      alive = false;
    };
  }, [api, locationId]);
  if (!days || days.every((d) => d.wait === null)) return null;
  // Headroom above the tallest bar for its value label.
  const top = Math.max(...days.map((d) => d.wait ?? 0), target ?? 0, 1) * 1.12;
  const pct = (s: number) => Math.max(3, (s / top) * 100);
  const tones = barTones(
    days.map((d) => d.wait),
    target,
  );
  const weekday = (d: Date) => d.toLocaleDateString('ro-RO', { weekday: 'short' });
  return (
    <figure className="card trend">
      <figcaption className="trend-head">
        <strong>Așteptarea pe zile</strong>
        <span className="small muted">mediană, ultimele 7 zile</span>
      </figcaption>
      <div className="trend-plot">
        {target !== null && (
          <div className="trend-target" style={{ bottom: `${pct(target)}%` }} aria-hidden="true" />
        )}
        <ol className="trend-bars" aria-label="Așteptarea pe zile">
          {days.map((d, i) => {
            const tone = tones[i] ?? 'empty';
            const label = weekday(d.day);
            return (
              <li
                key={d.day.toISOString()}
                className={`is-${tone}`}
                aria-label={`${label}: ${fmt(d.wait)}${tone === 'empty' ? '' : `, ${TONE_WORDS[tone]}`}`}
              >
                {d.wait !== null && (
                  <>
                    <span className="trend-bar" style={{ height: `${pct(d.wait)}%` }} />
                    <span className="trend-value mono" style={{ bottom: `${pct(d.wait)}%` }}>
                      {shortDuration(d.wait)}
                    </span>
                  </>
                )}
              </li>
            );
          })}
        </ol>
      </div>
      <ol className="trend-days" aria-hidden="true">
        {days.map((d, i) => (
          <li key={d.day.toISOString()} className={i === days.length - 1 ? 'is-today' : undefined}>
            {i === days.length - 1 ? 'azi' : weekday(d.day)}
          </li>
        ))}
      </ol>
      <p className="trend-legend small muted">
        {target !== null && (
          <>
            <span>
              <i className="sw is-target" aria-hidden="true" />{' '}
              <strong>ținta ta · {duration(target)}</strong>
            </span>
            <span>
              <i className="sw is-over" aria-hidden="true" /> peste țintă
            </span>
            <span>
              <i className="sw is-under" aria-hidden="true" /> sub țintă
            </span>
          </>
        )}
        <span>
          <i className="sw is-slowest" aria-hidden="true" /> cea mai lentă zi
        </span>
        {target !== null && <span>Ținta e timpul din regula pentru mese neservite.</span>}
      </p>
    </figure>
  );
}
