import { useEffect, useState, type ReactNode } from 'react';
import type { AlertItem } from '../alerts/fold';
import type { AlertCase } from '../api/client';
import { clock, duration } from '../alerts/format';
import { openFor, type AlertLimit } from '../alerts/limit';
import { useToast } from '../ui/toast';
import { Icon } from './Icon';
import './AlertFeed.css';

const CLOSED_BY_SYSTEM: Record<string, string> = {
  device_offline: 'dispozitiv deconectat',
  device_restarted: 'dispozitivul a repornit',
  camera_deleted: 'camera a fost scoasă',
};

/** Badge per AI verification status; `unavailable` has none, the card stays a plain alert. */
const VERIFICATION: Record<string, { label: string; tone: string }> = {
  confirmed: { label: 'Confirmat de AI', tone: 'pill-live' },
  rejected: { label: 'Neconfirmat', tone: 'pill-muted' },
  pending: { label: 'Se verifică…', tone: 'pill-muted' },
};

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });

function waited(a: AlertItem): string {
  return duration(openFor(a));
}

/**
 * `list` (default): one card shape for every alert, as on Live.
 * `hero`: open alerts, large, with the snapshot, a running clock and "Merg eu".
 * `rows`: closed alerts, one line each with a duration bar; the details expand.
 */
export type AlertFeedVariant = 'list' | 'hero' | 'rows';

export function AlertFeed({
  items,
  zoneName,
  showSnapshot = false,
  emptyText = 'Nicio alertă încă.',
  empty,
  cases = {},
  onAck,
  variant = 'list',
  ruleName,
  limit,
}: {
  items: AlertItem[];
  zoneName: (zoneId: string) => string;
  showSnapshot?: boolean;
  emptyText?: string;
  /** Rendered instead of `emptyText` when given (an EmptyState). */
  empty?: ReactNode;
  /** Lifecycle per alert key; adds the timeline. */
  cases?: Record<string, AlertCase>;
  /** Shows "Merg eu" on open alerts nobody took yet (omit when the role cannot ack). */
  onAck?: (eventId: string) => Promise<void>;
  variant?: AlertFeedVariant;
  /** `hero`: names the rule under the summary. */
  ruleName?: (ruleId: string) => string | undefined;
  /** `rows`: scale of the duration bar; no bar when it returns null. */
  limit?: (a: AlertItem) => AlertLimit | null;
}) {
  if (items.length === 0) return empty ?? <p className="muted empty">{emptyText}</p>;
  if (variant === 'hero') {
    return (
      <HeroFeed
        items={items}
        zoneName={zoneName}
        cases={cases}
        onAck={onAck}
        ruleName={ruleName}
        showSnapshot={showSnapshot}
      />
    );
  }
  if (variant === 'rows') {
    return (
      <RowFeed
        items={items}
        zoneName={zoneName}
        cases={cases}
        limit={limit}
        showSnapshot={showSnapshot}
      />
    );
  }
  return (
    <ul className="feed" aria-label="Alerte">
      {items.map((a) => {
        const open = a.closed_at === null;
        const lifecycle = cases[a.key];
        const verdict = a.verification ? VERIFICATION[a.verification.status] : undefined;
        const aiSummary = verdict ? a.verification?.summary_ro?.trim() : undefined;
        return (
          <li key={a.key} className={`feed-item ${open ? 'is-open' : 'is-closed'}`}>
            {showSnapshot &&
              (verdict && a.before_snapshot_url ? (
                <BeforeAfter before={a.before_snapshot_url} after={a.snapshot_url} />
              ) : (
                <Snapshot url={a.snapshot_url} />
              ))}
            <div className="feed-body">
              <div className="feed-head">
                <span className={`pill ${open ? 'pill-alert' : 'pill-muted'}`}>
                  {open ? 'Deschisă' : 'Închisă'}
                </span>
                <span className="feed-zone">{zoneName(a.zone_id)}</span>
                <time className="mono muted" dateTime={a.opened_at}>
                  {time(a.opened_at)}
                </time>
              </div>
              <p className="feed-summary">{a.summary_ro}</p>
              {verdict && (
                <p className="feed-ai small">
                  <span className={`pill pill-ai ${verdict.tone}`}>{verdict.label}</span>
                  {aiSummary && aiSummary !== a.summary_ro && <span>{aiSummary}</span>}
                </p>
              )}
              <p className="muted small mono">
                {open
                  ? `deschisă de ${waited(a)}`
                  : a.closed_reason !== undefined
                    ? `închisă de sistem: ${CLOSED_BY_SYSTEM[a.closed_reason ?? ''] ?? 'fără motiv'}`
                    : `a durat ${waited(a)}`}
                {!open && lifecycle?.acknowledged_by ? ` · ${lifecycle.acknowledged_by}` : ''}
              </p>
              {lifecycle &&
                (open ? (
                  <Timeline c={lifecycle} />
                ) : (
                  <details className="feed-more">
                    <summary>Vezi desfășurarea</summary>
                    <Timeline c={lifecycle} />
                  </details>
                ))}
            </div>
            {open && onAck && !lifecycle?.acknowledged_at && (
              <AckButton onAck={() => onAck(a.key)} zone={zoneName(a.zone_id)} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The face-blurred JPEG; nothing at all when the edge sent none or it does not load, unless
 * `placeholder` asks for a neutral frame in its place (rows that must stay aligned).
 */
export function Snapshot({
  url,
  alt = 'Captură cu fețele estompate',
  placeholder = false,
}: {
  url: string | null;
  alt?: string;
  placeholder?: boolean;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!url || failed === url) {
    return placeholder ? (
      <span className="snapshot" aria-hidden="true">
        <Icon name="snapshot" />
      </span>
    ) : null;
  }
  return (
    <a className="snapshot snapshot-img" href={url} target="_blank" rel="noreferrer">
      <img src={url} alt={alt} loading="lazy" decoding="async" onError={() => setFailed(url)} />
    </a>
  );
}

/** `object_gone`: the table before and after, side by side. */
function BeforeAfter({ before, after }: { before: string; after: string | null }) {
  return (
    <div className="snapshot-pair">
      <figure>
        <Snapshot url={before} alt="Înainte, cu fețele estompate" />
        <figcaption className="mono">Înainte</figcaption>
      </figure>
      <figure>
        <Snapshot url={after} alt="După, cu fețele estompate" />
        <figcaption className="mono">După</figcaption>
      </figure>
    </div>
  );
}

function AckButton({
  onAck,
  zone,
  hint = false,
}: {
  onAck: () => Promise<void>;
  zone: string;
  /** Says "Merg eu" is optional: it only tells colleagues; the camera closes the alert. */
  hint?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  return (
    <div className="ack">
      <button
        type="button"
        className="btn btn-accent"
        disabled={busy}
        aria-label={`Merg eu la ${zone}`}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await onAck();
            toast({
              title: `Ai preluat ${zone}`,
              text: 'Colegii văd că vii. Alerta se închide când ajungi.',
            });
          } catch (e) {
            setError(e instanceof Error ? e.message : 'Nu am putut prelua alerta.');
            setBusy(false);
          }
        }}
      >
        Merg eu
      </button>
      {hint && (
        <span className="muted small">
          Opțional: colegii văd că vii. Camera închide alerta când ajungi.
        </span>
      )}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** opened → preluată → ajuns → închisă, with the time between steps. */
export function Timeline({ c }: { c: AlertCase }) {
  const skippedAck = c.unacknowledged_arrival;
  const steps: { label: string; at: string | null; note?: string; gap?: string }[] = [
    { label: 'Deschisă', at: c.opened_at },
    {
      label: 'Preluată',
      at: c.acknowledged_at,
      note: skippedAck ? 'fără preluare' : (c.acknowledged_by ?? undefined),
      gap: c.reaction_s !== null ? `reacție ${duration(c.reaction_s)}` : undefined,
    },
    {
      label: 'Ajuns',
      at: c.arrived_at,
      note: c.realerted_at ? 'reamintire trimisă' : undefined,
      gap: c.travel_s !== null ? `drum ${duration(c.travel_s)}` : undefined,
    },
    {
      label: 'Închisă',
      at: c.closed_at,
      gap: c.wait_s !== null ? `așteptare ${duration(c.wait_s)}` : undefined,
    },
  ];
  const current = steps.reduce((last, s, i) => (s.at ? i : last), 0);
  return (
    <ol className="timeline" aria-label="Desfășurarea alertei">
      {steps.map((s, i) => (
        <li
          key={s.label}
          className={`tl-step ${s.at ? 'is-done' : ''} ${i === current && !c.closed_at ? 'is-now' : ''}`}
        >
          <span className="tl-dot" aria-hidden="true" />
          <span className="tl-label">{s.label}</span>
          <span className="tl-meta mono">
            {s.at ? time(s.at) : (s.note ?? '—')}
            {s.at && s.note ? ` · ${s.note}` : ''}
          </span>
          {s.gap && <span className="tl-gap mono">{s.gap}</span>}
        </li>
      ))}
    </ol>
  );
}

/** Re-renders every `ms` while `active`, for clocks that run. */
function useNow(active: boolean, ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [active, ms]);
  return now;
}

/** "Masa 2: un client a ridicat mâna" → "un client a ridicat mâna" when the zone is shown apart. */
function withoutZone(summary: string, zone: string): string {
  const prefix = `${zone}:`;
  return summary.startsWith(prefix) ? summary.slice(prefix.length).trim() : summary;
}

function HeroFeed({
  items,
  zoneName,
  cases,
  onAck,
  ruleName,
  showSnapshot,
}: {
  items: AlertItem[];
  zoneName: (zoneId: string) => string;
  cases: Record<string, AlertCase>;
  onAck?: (eventId: string) => Promise<void>;
  ruleName?: (ruleId: string) => string | undefined;
  showSnapshot: boolean;
}) {
  const now = useNow(items.some((a) => a.closed_at === null));
  return (
    <ul className="feed alert-heroes" aria-label="Alerte deschise">
      {items.map((a) => {
        const lifecycle = cases[a.key];
        const zone = zoneName(a.zone_id);
        const verdict = a.verification ? VERIFICATION[a.verification.status] : undefined;
        const aiSummary = verdict ? a.verification?.summary_ro?.trim() : undefined;
        const rule = ruleName?.(a.rule_id);
        const coming = lifecycle?.acknowledged_by;
        const s = openFor(a, now);
        return (
          <li key={a.key} className="feed-item is-open alert-hero">
            {showSnapshot && (
              <div className="alert-hero-shot">
                {verdict && a.before_snapshot_url ? (
                  <BeforeAfter before={a.before_snapshot_url} after={a.snapshot_url} />
                ) : (
                  <Snapshot url={a.snapshot_url} placeholder />
                )}
              </div>
            )}
            <div className="feed-body">
              <div className="feed-head">
                <span className="pill pill-alert alert-hero-clock">
                  deschisă · <span className="sr-only">de {duration(s)}</span>
                  <span aria-hidden="true">{clock(s)}</span>
                </span>
                <time className="mono muted" dateTime={a.opened_at}>
                  {time(a.opened_at)}
                </time>
              </div>
              <h3 className="alert-hero-title">{a.summary_ro}</h3>
              <p className="muted small">
                <span className="feed-zone">{zone}</span>
                {rule ? ` · regula „${rule}”` : ''}
                {coming ? ` · vine ${coming}` : ''}
              </p>
              {verdict && (
                <p className="feed-ai small">
                  <span className={`pill pill-ai ${verdict.tone}`}>{verdict.label}</span>
                  {aiSummary && aiSummary !== a.summary_ro && <span>{aiSummary}</span>}
                </p>
              )}
              {onAck && !lifecycle?.acknowledged_at && (
                <AckButton onAck={() => onAck(a.key)} zone={zone} hint />
              )}
              {lifecycle && <Timeline c={lifecycle} />}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function RowFeed({
  items,
  zoneName,
  cases,
  limit,
  showSnapshot,
}: {
  items: AlertItem[];
  zoneName: (zoneId: string) => string;
  cases: Record<string, AlertCase>;
  limit?: (a: AlertItem) => AlertLimit | null;
  showSnapshot: boolean;
}) {
  return (
    <ul className="alert-rows" aria-label="Alerte închise">
      {items.map((a) => {
        const lifecycle = cases[a.key];
        const zone = zoneName(a.zone_id);
        const verdict = a.verification ? VERIFICATION[a.verification.status] : undefined;
        const aiSummary = verdict ? a.verification?.summary_ro?.trim() : undefined;
        const s = openFor(a);
        const scale = limit?.(a) ?? null;
        const note =
          a.closed_reason !== undefined
            ? `închisă de sistem: ${CLOSED_BY_SYSTEM[a.closed_reason ?? ''] ?? 'fără motiv'}`
            : lifecycle?.acknowledged_by
              ? `preluată de ${lifecycle.acknowledged_by}`
              : withoutZone(a.summary_ro, zone);
        return (
          <li key={a.key} className="alert-row">
            <details>
              <summary>
                <span className="alert-row-what">
                  <b>{zone}</b> <span className="muted">{note}</span>
                </span>
                <span className="alert-row-meta">
                  {verdict && (
                    <span className={`pill pill-ai ${verdict.tone}`}>{verdict.label}</span>
                  )}
                  {scale && <DurationBar seconds={s} limit={scale} />}
                  <span className="mono alert-row-time">
                    <span className="sr-only">a durat {duration(s)}, la </span>
                    <span aria-hidden="true">{clock(s)} · </span>
                    <time dateTime={a.opened_at}>{time(a.opened_at)}</time>
                  </span>
                </span>
              </summary>
              <div className="alert-row-more">
                {showSnapshot &&
                  (verdict && a.before_snapshot_url ? (
                    <BeforeAfter before={a.before_snapshot_url} after={a.snapshot_url} />
                  ) : (
                    <Snapshot url={a.snapshot_url} />
                  ))}
                <div className="feed-body">
                  <p className="feed-summary">{a.summary_ro}</p>
                  {aiSummary && aiSummary !== a.summary_ro && (
                    <p className="muted small">{aiSummary}</p>
                  )}
                  <p className="muted small mono">
                    a durat {duration(s)}
                    {scale?.ofRule ? ` · limita regulii ${duration(scale.seconds)}` : ''}
                  </p>
                  {lifecycle && <Timeline c={lifecycle} />}
                </div>
              </div>
            </details>
          </li>
        );
      })}
    </ul>
  );
}

/** How long the alert stayed open against its scale; past the rule's limit it turns coral. */
function DurationBar({ seconds, limit }: { seconds: number; limit: AlertLimit }) {
  const ratio = Math.min(1, seconds / limit.seconds);
  const over = limit.ofRule && seconds > limit.seconds;
  const title = limit.ofRule
    ? `${duration(seconds)} din limita regulii de ${duration(limit.seconds)}`
    : `${duration(seconds)} față de cea mai lungă alertă din zi`;
  return (
    <span
      className={`dur-bar${over ? ' is-over' : ''}`}
      title={title}
      aria-hidden="true"
      data-testid="dur-bar"
    >
      <i style={{ width: `${Math.max(4, Math.round(ratio * 100))}%` }} />
    </span>
  );
}
