import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router';
import type { AlertItem } from '../alerts/fold';
import { openFor, ruleLimitS, type AlertLimit } from '../alerts/limit';
import { AlertFeed } from '../components/AlertFeed';
import { PushToggle } from '../push/PushToggle';
import { browserPushService } from '../push/service';
import { StaffPhotoUpload } from '../components/StaffPhotoUpload';
import { SuggestionCard } from '../components/SuggestionCard';
import { useAuth } from '../auth/context';
import { useLiveData, zoneName } from '../state/context';
import { EmptyState, Segmented } from '../ui/controls';
import './AlertsPage.css';

type Filter = 'all' | 'open' | 'closed';

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
  const { alerts, cameras, rules, suggestions, dropSuggestion, cases, ack } = useLiveData();
  const { can, me } = useAuth();
  const [filter, setFilter] = useState<Filter>('all');
  const push = useMemo(() => browserPushService(), []);
  const { hash } = useLocation();
  // Deep links from the setup checklist (#notificari, #poze-personal) land on the right card.
  useEffect(() => {
    if (!hash) return;
    try {
      document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.({
        block: 'center',
      });
    } catch {
      /* a malformed hash just stays at the top */
    }
  }, [hash]);

  const open = alerts.filter((a) => a.closed_at === null);
  const closed = alerts.filter((a) => a.closed_at !== null);
  const zone = (id: string) => zoneName(cameras, id);
  const ruleById = useMemo(() => new Map(rules.map((r) => [r.id, r])), [rules]);

  // An alert carries no threshold of its own, so the bar uses its rule's longest
  // `min_duration_s` from listRules. Staff never load rules (403) and instant rules (a raised
  // hand) have no duration; those bars measure against the longest alert of the same day.
  const limitFor = (dayItems: AlertItem[]) => {
    const longest = Math.max(0, ...dayItems.map((a) => openFor(a)));
    return (a: AlertItem): AlertLimit | null => {
      const rule = ruleById.get(a.rule_id);
      const s = rule ? ruleLimitS(rule) : null;
      if (s) return { seconds: s, ofRule: true };
      return longest > 0 ? { seconds: longest, ofRule: false } : null;
    };
  };

  const showOpen = filter !== 'closed';
  const showClosed = filter !== 'open';
  const nothing = (showOpen ? open.length : 0) + (showClosed ? closed.length : 0) === 0;
  const canReview = can('staff.review');
  const canEnrol = can('staff.enrol');

  return (
    <div className="page alerts-page">
      <header className="page-head">
        <h1>Alerte</h1>
        <Segmented
          label="Filtru alerte"
          hideLabel
          value={filter}
          options={[
            { value: 'all', label: 'Toate' },
            { value: 'open', label: 'Deschise', count: open.length },
            { value: 'closed', label: 'Închise' },
          ]}
          onChange={setFilter}
        />
      </header>
      {me?.is_owner && <PushToggle service={push} variant="banner" />}
      <div className="two-col">
        <section className="alerts-main" aria-label="Alerte">
          {nothing ? (
            <EmptyState icon="alerts" title={EMPTY[filter].title}>
              {EMPTY[filter].text}
            </EmptyState>
          ) : (
            <>
              {showOpen && open.length > 0 && (
                <section aria-labelledby="open-h">
                  <h2 id="open-h" className="feed-group">
                    Deschise acum · {open.length}
                  </h2>
                  <AlertFeed
                    variant="hero"
                    items={open}
                    zoneName={zone}
                    showSnapshot
                    cases={cases}
                    ruleName={(id) => ruleById.get(id)?.name}
                    onAck={can('alerts.ack') ? ack : undefined}
                  />
                </section>
              )}
              {showClosed &&
                groupByDay(closed).map((g) => (
                  <section key={g.label} className="alerts-day" aria-label={`${g.label} · închise`}>
                    <h2 className="feed-group">{g.label} · închise</h2>
                    <AlertFeed
                      variant="rows"
                      items={g.items}
                      zoneName={zone}
                      showSnapshot
                      cases={cases}
                      limit={limitFor(g.items)}
                    />
                  </section>
                ))}
            </>
          )}
        </section>
        <aside className="alerts-side" aria-label="Personal și notificări">
          {(canReview || canEnrol) && (
            <section className="card alerts-staff" aria-labelledby="staff-h">
              <h2 id="staff-h">Personal</h2>
              {canReview && suggestions.length === 0 && (
                <p className="muted small">
                  Nicio întrebare nouă. AiVee te întreabă când pare că cineva e angajat.
                </p>
              )}
              {canReview &&
                suggestions.map((s) => (
                  <SuggestionCard
                    key={s.suggestion_id}
                    variant="question"
                    suggestion={s}
                    cameraName={cameras.find((c) => c.id === s.camera_id)?.name}
                    onResolved={dropSuggestion}
                  />
                ))}
              {canEnrol && <StaffPhotoUpload />}
            </section>
          )}
          <PushToggle service={push} variant="actionable" />
          {!me?.is_owner && <PushToggle service={push} variant="note" />}
        </aside>
      </div>
    </div>
  );
}
