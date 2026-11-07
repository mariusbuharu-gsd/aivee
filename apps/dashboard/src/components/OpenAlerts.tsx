import { useState } from 'react';
import type { AlertItem } from '../alerts/fold';
import type { AlertCase } from '../api/client';
import { elapsed, ringFill, tick } from '../live/room';
import { useNow } from '../live/useNow';
import { useToast } from '../ui/toast';
import './live.css';

/**
 * Open alerts as dark bands at the top of Live: a ring that fills while the table waits, who is
 * on the way, and "Preiau". The button only tells colleagues someone goes; the camera closes the
 * alert when staff reach the table.
 */
export function OpenAlerts({
  items,
  cases,
  zoneName,
  cameraName,
  onAck,
}: {
  items: AlertItem[];
  cases: Record<string, AlertCase>;
  zoneName: (zoneId: string) => string;
  cameraName: (cameraId: string) => string;
  onAck?: (eventId: string) => Promise<void>;
}) {
  const now = useNow(items.length > 0);
  if (items.length === 0) return null;
  return (
    <ul className="open-alerts" aria-label="Alerte deschise">
      {items.map((a) => {
        const s = elapsed(a, now);
        const zone = zoneName(a.zone_id);
        const taken = cases[a.key]?.acknowledged_by ?? null;
        return (
          <li key={a.key} className={`open-alert${taken ? ' is-taken' : ''}`}>
            <span
              className="ring"
              style={{ ['--fill' as string]: ringFill(s) }}
              role="timer"
              aria-label={`Deschisă de ${tick(s)}`}
            >
              <span className="ring-time mono">{tick(s)}</span>
            </span>
            <div className="open-alert-text">
              <span className="open-alert-where mono">
                {cameraName(a.camera_id)} · {zone}
              </span>
              <strong>{a.summary_ro}</strong>
              <span className="open-alert-who">
                {taken ? `${taken} merge la ${zone}` : 'Nimeni nu a ajuns încă'}
              </span>
            </div>
            {onAck && !taken && <GoButton zone={zone} onAck={() => onAck(a.key)} />}
          </li>
        );
      })}
    </ul>
  );
}

function GoButton({ zone, onAck }: { zone: string; onAck: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  return (
    <div className="open-alert-go">
      <button
        type="button"
        className="btn btn-accent"
        disabled={busy}
        aria-label={`Preiau ${zone}`}
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
        Preiau
      </button>
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
