import type { DashboardMetrics } from '../api/client';

const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

export function MetricsStrip({ metrics }: { metrics: DashboardMetrics | null }) {
  const fps = avg(metrics?.devices.map((d) => d.fps) ?? []);
  const verified = avg(metrics?.devices.map((d) => d.verified_ratio) ?? []);
  const cells: { label: string; value: string }[] = [
    {
      label: 'Dispozitive online',
      value: metrics ? `${metrics.devices_online}/${metrics.devices_total}` : '—',
    },
    { label: 'FPS', value: fps === null ? '—' : fps.toFixed(1) },
    {
      label: 'Cadre verificate',
      value: verified === null ? '—' : `${(verified * 100).toFixed(1)}%`,
    },
    { label: 'Evenimente azi', value: metrics ? String(metrics.events_today) : '—' },
    {
      label: 'Latență alertă',
      value:
        metrics?.alert_latency_ms == null
          ? '—'
          : `${(metrics.alert_latency_ms / 1000).toFixed(1)} s`,
    },
  ];
  return (
    <dl className="metrics" aria-label="Metrici">
      {cells.map((c) => (
        <div key={c.label} className="metric">
          <dt>{c.label}</dt>
          <dd className="mono">{c.value}</dd>
        </div>
      ))}
    </dl>
  );
}
