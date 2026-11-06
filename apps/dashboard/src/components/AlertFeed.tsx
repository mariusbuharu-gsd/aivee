import type { AlertItem } from '../alerts/fold';
import { Icon } from './Icon';

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });

function waited(a: AlertItem): string {
  const end = a.closed_at ? Date.parse(a.closed_at) : Date.now();
  const s = Math.max(0, Math.round((end - Date.parse(a.opened_at)) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

export function AlertFeed({
  items,
  zoneName,
  showSnapshot = false,
  emptyText = 'Nicio alertă încă.',
}: {
  items: AlertItem[];
  zoneName: (zoneId: string) => string;
  showSnapshot?: boolean;
  emptyText?: string;
}) {
  if (items.length === 0) return <p className="muted empty">{emptyText}</p>;
  return (
    <ul className="feed" aria-label="Alerte">
      {items.map((a) => {
        const open = a.closed_at === null;
        return (
          <li key={a.key} className={`feed-item ${open ? 'is-open' : 'is-closed'}`}>
            {showSnapshot && (
              <div className="snapshot" role="img" aria-label="Captură cu fețele estompate">
                <Icon name="snapshot" size={22} />
              </div>
            )}
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
              <p className="muted small mono">
                {open ? `deschisă de ${waited(a)}` : `rezolvată în ${waited(a)}`}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
