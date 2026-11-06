import { useEffect, useState } from 'react';
import type { AlertItem } from '../alerts/fold';
import { duration } from '../alerts/format';
import type { CameraView, DashboardMetrics } from '../api/client';

/** What a manager wants at a glance: what is open, for how long, and whether cameras see. */
export function LiveSummary({
  alerts,
  cameras,
  metrics,
}: {
  alerts: AlertItem[];
  cameras: CameraView[];
  metrics: DashboardMetrics | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(t);
  }, []);
  const open = alerts.filter((a) => a.closed_at === null);
  const oldest = open.reduce<number | null>((min, a) => {
    const t = Date.parse(a.opened_at);
    return min === null || t < min ? t : min;
  }, null);
  const online = cameras.filter((c) => c.online).length;
  const cells: { label: string; value: string; tone?: 'alert' | 'off' }[] = [
    {
      label: 'Alerte deschise',
      value: String(open.length),
      tone: open.length ? 'alert' : undefined,
    },
    {
      label: 'Cea mai veche',
      value: oldest === null ? '—' : duration((now - oldest) / 1000),
      tone: oldest !== null ? 'alert' : undefined,
    },
    {
      label: 'Camere online',
      value: cameras.length ? `${online}/${cameras.length}` : '—',
      tone: online < cameras.length ? 'off' : undefined,
    },
    { label: 'Alerte azi', value: metrics ? String(metrics.events_today) : '—' },
  ];
  return (
    <dl className="metrics metrics-4" aria-label="Pe scurt">
      {cells.map((c) => (
        <div key={c.label} className={`metric ${c.tone ? `is-${c.tone}` : ''}`}>
          <dt>{c.label}</dt>
          <dd className="mono">{c.value}</dd>
        </div>
      ))}
    </dl>
  );
}
