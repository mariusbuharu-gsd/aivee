import { Link } from 'react-router';
import { AlertFeed } from '../components/AlertFeed';
import { CameraTile } from '../components/CameraTile';
import { Icon } from '../components/Icon';
import { OpenAlerts } from '../components/OpenAlerts';
import { RoomStatus } from '../components/RoomStatus';
import { SetupChecklist } from '../components/SetupChecklist';
import { SuggestionCard } from '../components/SuggestionCard';
import { useAuth } from '../auth/context';
import { useLiveData, zoneName } from '../state/context';
import { openAlerts, elapsed, tick } from '../live/room';
import { useNow } from '../live/useNow';
import { EmptyState, Skeleton } from '../ui/controls';

/** What is happening now. Writing rules lives on Reguli, device numbers on Dispozitive. */
export function LivePage() {
  const { cameras, alerts, suggestions, metrics, loading, dropSuggestion, cases, ack } =
    useLiveData();
  const { can } = useAuth();
  // Open alerts lead the page as bands; the side column keeps the ones already closed.
  const open = openAlerts(alerts);
  const recent = alerts.filter((a) => a.closed_at !== null).slice(0, 8);
  const now = useNow(open.length > 0);
  const hotFor = (cameraId: string) =>
    Object.fromEntries(
      open.filter((a) => a.camera_id === cameraId).map((a) => [a.zone_id, tick(elapsed(a, now))]),
    );
  // Cameras that see come first; an offline one is a single row after them.
  const ordered = [...cameras].sort((a, b) => Number(b.online) - Number(a.online));
  return (
    <div className="page page-live">
      <header className="page-head">
        <h1>Live</h1>
        {can('rules.manage') && (
          <Link to="/reguli" className="btn">
            <Icon name="plus" /> Regulă nouă
          </Link>
        )}
      </header>
      <RoomStatus
        open={open.length}
        cameras={cameras}
        alertsToday={metrics ? metrics.events_today : null}
      />
      <OpenAlerts
        items={open}
        cases={cases}
        zoneName={(id) => zoneName(cameras, id)}
        cameraName={(id) => cameras.find((c) => c.id === id)?.name ?? id}
        onAck={can('alerts.ack') ? ack : undefined}
      />
      <SetupChecklist />
      <div className="live-grid">
        <section aria-label="Camere" className="cameras">
          {loading && cameras.length === 0 && <Skeleton rows={2} label="Se încarcă camerele" />}
          {!loading && cameras.length === 0 && (
            <EmptyState
              icon="devices"
              title="Nicio cameră încă"
              action={
                can('devices.manage') && (
                  <Link to="/dispozitive" className="btn btn-primary btn-sm">
                    Adaugă prima cameră
                  </Link>
                )
              }
            >
              Leagă o cameră din sală, apoi desenează mesele pe imagine.
            </EmptyState>
          )}
          {ordered.map((c) => (
            <CameraTile key={c.id} camera={c} hot={hotFor(c.id)} />
          ))}
        </section>
        <aside className="side-col" aria-labelledby="recent-h">
          <div className="side-head">
            <h2 id="recent-h">Alerte recente</h2>
            <Link to="/alerte" className="link">
              Toate
            </Link>
          </div>
          {can('staff.review') &&
            suggestions
              .slice(0, 1)
              .map((s) => (
                <SuggestionCard
                  key={s.suggestion_id}
                  suggestion={s}
                  cameraName={cameras.find((c) => c.id === s.camera_id)?.name}
                  onResolved={dropSuggestion}
                />
              ))}
          <AlertFeed
            items={recent}
            zoneName={(id) => zoneName(cameras, id)}
            cases={cases}
            onAck={can('alerts.ack') ? ack : undefined}
            empty={
              <EmptyState icon="alerts" title="Nicio alertă închisă încă">
                Când cineva așteaptă prea mult, alerta apare sus și pe telefoanele echipei.
              </EmptyState>
            }
          />
        </aside>
      </div>
    </div>
  );
}
