import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import type { DurationStat, HeatCell, ServiceMetrics } from '../api/client';
import { useApi } from '../api/context';
import { useAuth, useLocationId } from '../auth/context';
import { duration } from '../alerts/format';
import {
  WEEKDAYS_SHORT,
  barTones,
  headline,
  heatHours,
  heatLabel,
  heatLevel,
  periodPhrase,
  pickTarget,
  serviceTarget,
  shortDuration,
  targetSeconds,
} from '../metrics/insight';
import { Banner } from '../ui/Banner';
import { useToast } from '../ui/toast';

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
 * then the wait per day against the owner's own target, then when in the week guests wait.
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
            'Se încarcă…'
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
                <span className="service-value">{fmt(s?.median_s ?? null)}</span>
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
            <span className="service-value">{data ? data.alerts : '—'}</span>
            <span className="small muted">{periodPhrase(days)}</span>
          </dd>
        </div>
      </dl>
      <WaitTrend />
      <WaitHeatmap days={days} />
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

/**
 * Median wait per day over the last 7 days, against the target: the location's own when the
 * owner set one, else the unserved-table rule's time.
 */
function WaitTrend() {
  const api = useApi();
  const locationId = useLocationId();
  const { can } = useAuth();
  const [days, setDays] = useState<{ day: Date; wait: number | null }[] | null>(null);
  const [ruleTarget, setRuleTarget] = useState<number | null>(null);
  const [own, setOwn] = useState<number | null>(null);
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
    // No rules (or no right to read them) just means no rule-based fallback.
    api.listRules().then(
      (rules) => alive && setRuleTarget(serviceTarget(rules)),
      () => alive && setRuleTarget(null),
    );
    api.listLocations().then(
      (locs) => alive && setOwn(locs.find((l) => l.id === locationId)?.service_target_s ?? null),
      () => alive && setOwn(null),
    );
    return () => {
      alive = false;
    };
  }, [api, locationId]);
  if (!days || days.every((d) => d.wait === null)) return null;
  const goal = pickTarget(own, ruleTarget);
  const target = goal?.seconds ?? null;
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
                    <span className="trend-value" style={{ bottom: `${pct(d.wait)}%` }}>
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
      <div className="trend-legend small muted">
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
        {goal?.source === 'rule' && <span>Ținta e timpul din regula pentru mese neservite.</span>}
        {can('rules.manage') && (
          <TargetControl locationId={locationId} own={own} shown={target} onSaved={setOwn} />
        )}
      </div>
    </figure>
  );
}

const TARGET_RANGE = 'Ținta trebuie să fie între 1 secundă și 60 de minute.';

/**
 * „Setează ținta” / „Schimbă ținta”: a small popover with minutes and seconds. Saves the
 * location's own target (`PATCH /api/locations/{id}`); „Folosește regula” clears it.
 */
function TargetControl({
  locationId,
  own,
  shown,
  onSaved,
}: {
  locationId: string;
  own: number | null;
  /** The target the chart draws now (own or the rule's), to start the fields from. */
  shown: number | null;
  onSaved: (seconds: number | null) => void;
}) {
  const api = useApi();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [min, setMin] = useState('');
  const [sec, setSec] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLInputElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    first.current?.focus();
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  function toggle() {
    if (!open) {
      const start = own ?? shown;
      setMin(start === null ? '' : String(Math.floor(start / 60)));
      setSec(start === null ? '' : String(start % 60));
      setError(null);
    }
    setOpen(!open);
  }

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  async function save(value: number | null) {
    setBusy(true);
    try {
      const loc = await api.updateLocation(locationId, { service_target_s: value });
      onSaved(loc.service_target_s ?? null);
      toast({
        title:
          value === null
            ? 'Ținta urmează din nou regula'
            : `Ținta e acum ${duration(value)} de la alertă`,
      });
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const value = targetSeconds(min, sec);
    if (value === null) return setError(TARGET_RANGE);
    void save(value);
  }

  return (
    <div className="target-wrap" ref={root}>
      <button
        ref={button}
        type="button"
        className="btn btn-ghost btn-sm target-btn"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={toggle}
      >
        {own === null ? 'Setează ținta' : 'Schimbă ținta'}
      </button>
      {open && (
        <form
          id={id}
          role="dialog"
          aria-label="Ținta de servire"
          className="target-pop"
          onSubmit={onSubmit}
          onKeyDown={(e) => e.key === 'Escape' && close()}
        >
          <p className="target-q">Cât poate aștepta un client după alertă?</p>
          <div className="target-fields">
            <label className="field">
              Minute
              <input
                ref={first}
                className="input input-sm"
                inputMode="numeric"
                value={min}
                onChange={(e) => setMin(e.target.value)}
                aria-invalid={error !== null}
              />
            </label>
            <span className="target-colon" aria-hidden="true">
              :
            </span>
            <label className="field">
              Secunde
              <input
                className="input input-sm"
                inputMode="numeric"
                value={sec}
                onChange={(e) => setSec(e.target.value)}
                aria-invalid={error !== null}
              />
            </label>
          </div>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <div className="actions">
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
              Salvează
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={close}>
              Renunță
            </button>
            {own !== null && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy}
                onClick={() => void save(null)}
              >
                Folosește regula
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

/**
 * When guests wait: alerts per weekday × hour over the period, coloured light to coral by
 * how many there were, each cell saying the usual wait. Team level only.
 */
function WaitHeatmap({ days }: { days: number }) {
  const api = useApi();
  const locationId = useLocationId();
  const [cells, setCells] = useState<HeatCell[][] | null>(null);
  // „Azi” has no week to spread over: the grid keeps the last 7 days.
  const span = Math.max(days, 7);
  useEffect(() => {
    let alive = true;
    const from = new Date();
    from.setHours(0, 0, 0, 0);
    from.setDate(from.getDate() - (span - 1));
    api.getServiceHeatmap({ location_id: locationId, from: from.toISOString() }).then(
      (m) => alive && setCells(m.cells),
      () => alive && setCells(null),
    );
    return () => {
      alive = false;
    };
  }, [api, locationId, span]);
  if (!cells || cells.length !== 7 || cells.every((row) => row.every((c) => c.alerts === 0))) {
    return null;
  }
  const hours = heatHours(cells);
  const max = Math.max(...cells.flat().map((c) => c.alerts));
  return (
    <figure className="card heat" aria-labelledby="heat-h">
      <figcaption className="trend-head">
        <strong id="heat-h">Când se așteaptă</strong>
        <span className="small muted">alerte pe zi și oră, {periodPhrase(span)}</span>
      </figcaption>
      <div className="heat-scroll">
        <table className="heat-grid">
          <thead>
            <tr>
              <td />
              {hours.map((h) => (
                <th key={h} scope="col" className="mono">
                  {String(h).padStart(2, '0')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cells.map((row, d) => (
              <tr key={WEEKDAYS_SHORT[d]}>
                <th scope="row">{WEEKDAYS_SHORT[d]}</th>
                {hours.map((h) => {
                  const c = row[h] ?? { alerts: 0, wait_median_s: null };
                  const label = heatLabel(d, h, c);
                  return (
                    <td
                      key={h}
                      className={`lv-${heatLevel(c.alerts, max)}`}
                      title={label}
                      aria-label={label}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="heat-legend small muted" aria-hidden="true">
        mai puține
        {[1, 2, 3, 4].map((l) => (
          <i key={l} className={`heat-sw lv-${l}`} />
        ))}
        mai multe alerte
      </p>
    </figure>
  );
}
