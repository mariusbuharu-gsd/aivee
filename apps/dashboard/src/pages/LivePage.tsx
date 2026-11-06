import { Link } from 'react-router';
import { AlertFeed } from '../components/AlertFeed';
import { CameraTile } from '../components/CameraTile';
import { Icon } from '../components/Icon';
import { LiveSummary } from '../components/LiveSummary';
import { SetupChecklist } from '../components/SetupChecklist';
import { SuggestionCard } from '../components/SuggestionCard';
import { useAuth } from '../auth/context';
import { useLiveData, zoneName } from '../state/context';
import { EmptyState, Skeleton } from '../ui/controls';

/** What is happening now. Writing rules lives on Reguli, device numbers on Dispozitive. */
export function LivePage() {
  const { cameras, alerts, suggestions, metrics, loading, dropSuggestion, cases, ack } =
    useLiveData();
  const { can } = useAuth();
  // Open alerts first, so the sidebar never hides one under older closed ones.
  const recent = [...alerts]
    .sort((a, b) => Number(a.closed_at !== null) - Number(b.closed_at !== null))
    .slice(0, 8);
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
      <SetupChecklist />
      <LiveSummary alerts={alerts} cameras={cameras} metrics={metrics} />
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
          {cameras.map((c) => (
            <CameraTile key={c.id} camera={c} />
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
              <EmptyState icon="alerts" title="Nicio alertă încă">
                Când cineva așteaptă prea mult, alerta apare aici și pe telefoanele echipei.
              </EmptyState>
            }
          />
        </aside>
      </div>
    </div>
  );
}
