import { useState } from 'react';
import type { AlertItem } from '../alerts/fold';
import { AlertFeed } from '../components/AlertFeed';
import { PushToggle } from '../push/PushToggle';
import { StaffPhotoUpload } from '../components/StaffPhotoUpload';
import { SuggestionCard } from '../components/SuggestionCard';
import { useAuth } from '../auth/context';
import { useLiveData, zoneName } from '../state/context';
import { EmptyState, Segmented } from '../ui/controls';

type Filter = 'all' | 'open' | 'closed';
const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'Toate' },
  { value: 'open', label: 'Deschise' },
  { value: 'closed', label: 'Închise' },
];

const EMPTY: Record<Filter, { title: string; text: string }> = {
  all: {
    title: 'Nicio alertă încă',
    text: 'Când cineva așteaptă prea mult, alerta apare aici și pe telefoanele echipei.',
  },
  open: { title: 'Nicio alertă deschisă', text: 'Toți clienții sunt serviți.' },
  closed: { title: 'Nicio alertă închisă încă', text: 'Alertele rezolvate apar aici.' },
};

const dayKey = (iso: string) => new Date(iso).toDateString();

/** Closed alerts under "Azi", "Ieri" or the date. */
function groupByDay(items: AlertItem[]): { label: string; items: AlertItem[] }[] {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const groups: { key: string; label: string; items: AlertItem[] }[] = [];
  for (const a of items) {
    const key = dayKey(a.opened_at);
    let g = groups.find((x) => x.key === key);
    if (!g) {
      const label =
        key === today.toDateString()
          ? 'Azi'
          : key === yesterday.toDateString()
            ? 'Ieri'
            : new Date(a.opened_at).toLocaleDateString('ro-RO', {
                weekday: 'long',
                day: 'numeric',
                month: 'short',
              });
      g = { key, label, items: [] };
      groups.push(g);
    }
    g.items.push(a);
  }
  return groups;
}

export function AlertsPage() {
  const { alerts, cameras, suggestions, dropSuggestion, cases, ack } = useLiveData();
  const { can } = useAuth();
  const [filter, setFilter] = useState<Filter>('all');
  const open = alerts.filter((a) => a.closed_at === null);
  const closed = alerts.filter((a) => a.closed_at !== null);
  const feed = (items: AlertItem[], empty = true) => (
    <AlertFeed
      items={items}
      zoneName={(id) => zoneName(cameras, id)}
      showSnapshot
      cases={cases}
      onAck={can('alerts.ack') ? ack : undefined}
      empty={
        empty ? (
          <EmptyState icon="alerts" title={EMPTY[filter].title}>
            {EMPTY[filter].text}
          </EmptyState>
        ) : null
      }
    />
  );
  const showOpen = filter !== 'closed';
  const showClosed = filter !== 'open';
  const nothing = (showOpen ? open.length : 0) + (showClosed ? closed.length : 0) === 0;
  return (
    <div className="page">
      <header className="page-head">
        <h1>Alerte</h1>
      </header>
      <div className="two-col">
        <section aria-labelledby="alerts-h">
          <div className="side-head">
            <h2 id="alerts-h">Istoric</h2>
            <Segmented
              label="Filtru alerte"
              hideLabel
              value={filter}
              options={FILTERS}
              onChange={setFilter}
            />
          </div>
          {nothing ? (
            feed([])
          ) : (
            <>
              {showOpen && open.length > 0 && (
                <>
                  <h3 className="feed-group">Deschise acum · {open.length}</h3>
                  {feed(open, false)}
                </>
              )}
              {showClosed &&
                groupByDay(closed).map((g) => (
                  <div key={g.label}>
                    <h3 className="feed-group">{g.label}</h3>
                    {feed(g.items, false)}
                  </div>
                ))}
            </>
          )}
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
