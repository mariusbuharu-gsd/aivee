import type { CameraView } from '../api/client';
import { roomStatus } from '../live/room';
import './live.css';

/** One sentence instead of four equal numbers: is anyone waiting right now? */
export function RoomStatus({
  open,
  cameras,
  alertsToday,
}: {
  open: number;
  cameras: CameraView[];
  alertsToday: number | null;
}) {
  const { title, facts } = roomStatus(open, cameras, alertsToday);
  return (
    <p className={`room-status${open ? ' is-waiting' : ''}`} role="status">
      <span className="room-status-title">{title}</span>
      {facts.length > 0 && <span className="room-status-facts">{facts.join(' · ')}</span>}
    </p>
  );
}
