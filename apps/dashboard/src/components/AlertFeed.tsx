import { useState, type ReactNode } from 'react';
import type { AlertItem } from '../alerts/fold';
import type { AlertCase } from '../api/client';
import { duration } from '../alerts/format';
import { useToast } from '../ui/toast';
import { Icon } from './Icon';

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
  const end = a.closed_at ? Date.parse(a.closed_at) : Date.now();
  return duration((end - Date.parse(a.opened_at)) / 1000);
}

export function AlertFeed({
  items,
  zoneName,
  showSnapshot = false,
  emptyText = 'Nicio alertă încă.',
  empty,
  cases = {},
  onAck,
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
}) {
  if (items.length === 0) return empty ?? <p className="muted empty">{emptyText}</p>;
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

function AckButton({ onAck, zone }: { onAck: () => Promise<void>; zone: string }) {
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
