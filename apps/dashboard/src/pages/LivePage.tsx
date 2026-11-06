import { useMemo } from 'react';
import { Link } from 'react-router';
import { limitsFor } from '../alerts/limit';
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
import './LivePage.css';

/** Closed alerts in the side column; "Toate alertele" opens Alerte for the rest. */
const RECENT_CLOSED = 5;

/** What is happening now. Writing rules lives on Reguli, device numbers on Dispozitive. */
export function LivePage() {
  const { cameras, rules, alerts, suggestions, metrics, loading, dropSuggestion, cases, ack } =
    useLiveData();
  const { can } = useAuth();
  // Open alerts lead the page as bands; the side column keeps the last few closed ones, in the
  // same rows as Alerte, which has the rest.
  const open = openAlerts(alerts);
  const closed = alerts.filter((a) => a.closed_at !== null);
  const recent = closed.slice(0, RECENT_CLOSED);
  const ruleById = useMemo(() => new Map(rules.map((r) => [r.id, r])), [rules]);
  // Bars without a rule threshold measure against the day's longest alert, as on Alerte.
  const today = new Date().toDateString();
  const limit = limitsFor(
    closed.filter((a) => new Date(a.opened_at).toDateString() === today),
    ruleById,
  );
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
        <aside className="side-col live-side" aria-labelledby="recent-h">
          <div className="side-head">
            <h2 id="recent-h">Alerte recente</h2>
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
            variant="rows"
            items={recent}
            zoneName={(id) => zoneName(cameras, id)}
            cases={cases}
            limit={limit}
            empty={
              <EmptyState icon="alerts" title="Nicio alertă închisă încă">
                Când cineva așteaptă prea mult, alerta apare sus și pe telefoanele echipei.
              </EmptyState>
            }
          />
          {recent.length > 0 && (
            <Link to="/alerte" className="link live-side-all">
              Toate alertele
            </Link>
          )}
        </aside>
      </div>
    </div>
  );
}
