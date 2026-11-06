import { useState } from 'react';
import { AlertFeed } from '../components/AlertFeed';
import { PushToggle } from '../push/PushToggle';
import { StaffPhotoUpload } from '../components/StaffPhotoUpload';
import { SuggestionCard } from '../components/SuggestionCard';
import { useAuth } from '../auth/context';
import { useLiveData, zoneName } from '../state/context';

type Filter = 'all' | 'open' | 'closed';
const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'Toate' },
  { value: 'open', label: 'Deschise' },
  { value: 'closed', label: 'Închise' },
];

export function AlertsPage() {
  const { alerts, cameras, suggestions, dropSuggestion, cases, ack } = useLiveData();
  const { can } = useAuth();
  const [filter, setFilter] = useState<Filter>('all');
  const shown = alerts.filter((a) =>
    filter === 'all' ? true : filter === 'open' ? a.closed_at === null : a.closed_at !== null,
  );
  return (
    <div className="page">
      <header className="page-head">
        <h1>Alerte</h1>
      </header>
      <div className="two-col">
        <section aria-labelledby="alerts-h">
          <div className="side-head">
            <h2 id="alerts-h">Istoric</h2>
            <div className="segmented" role="group" aria-label="Filtru alerte">
              {FILTERS.map((f) => (
                <button
                  key={f.value}
                  className="btn btn-seg"
                  aria-pressed={filter === f.value}
                  onClick={() => setFilter(f.value)}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <AlertFeed
            items={shown}
            zoneName={(id) => zoneName(cameras, id)}
            showSnapshot
            emptyText="Nicio alertă pentru acest filtru."
            cases={cases}
            onAck={can('alerts.ack') ? ack : undefined}
          />
        </section>
        <aside className="side-col" aria-label="Notificări și personal">
          <PushToggle />
          {(can('staff.review') || can('staff.enrol')) && (
            <>
              <h2 id="staff-h">Personal</h2>
              {can('staff.review') && suggestions.length === 0 && (
                <p className="muted">
                  Nicio sugestie nouă. AiVee te întreabă când pare că cineva e angajat.
                </p>
              )}
              {can('staff.review') &&
                suggestions.map((s) => (
                  <SuggestionCard
                    key={s.suggestion_id}
                    suggestion={s}
                    cameraName={cameras.find((c) => c.id === s.camera_id)?.name}
                    onResolved={dropSuggestion}
                  />
                ))}
              {can('staff.enrol') && <StaffPhotoUpload />}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
