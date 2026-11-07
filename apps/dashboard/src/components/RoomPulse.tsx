import { Link } from 'react-router';
import type { AlertItem } from '../alerts/fold';
import { elapsed, ringFill, tick } from '../live/room';
import { useNow } from '../live/useNow';
import './live.css';

/**
 * "Sala acum" in the sidebar (and above the phone's tab bar): the table waiting longest and for
 * how long, or a quiet line when nobody waits. The logo's eyes look at it while an alert is open.
 */
export function RoomPulse({
  open,
  zoneName,
  takenBy,
  compact = false,
}: {
  open: AlertItem[];
  zoneName: (zoneId: string) => string;
  takenBy: (key: string) => string | null;
  compact?: boolean;
}) {
  const now = useNow(open.length > 0);
  const first = open[0];
  if (!first) {
    if (compact) return null;
    return (
      <p className="pulse is-quiet">
        <span className="pulse-kicker">Sala acum</span>
        <span className="pulse-title">Sala e liniștită</span>
      </p>
    );
  }
  const s = elapsed(first, now);
  const zone = zoneName(first.zone_id);
  const taken = takenBy(first.key);
  const more = open.length - 1;
  return (
    <Link to="/" className={`pulse${compact ? ' is-compact' : ''}`}>
      <span className="pulse-kicker">Sala acum</span>
      <span className="pulse-title">
        {zone} așteaptă{more > 0 ? ` · încă ${more}` : ''}
      </span>
      <span className="pulse-bar" aria-hidden="true">
        <i style={{ width: `${ringFill(s) * 100}%` }} />
      </span>
      <span className="pulse-meta">
        <span className="mono">{tick(s)}</span>
        <span>{taken ? `${taken} merge` : 'nimeni nu a ajuns'}</span>
      </span>
    </Link>
  );
}
