import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router';
import type { AlertItem } from '../alerts/fold';
import { limitsFor } from '../alerts/limit';
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

/** Closed rows per "Mai multe". */
const CLOSED_PAGE = 20;
/** Staff questions shown before "Încă N întrebări". */
const QUESTIONS_SHOWN = 5;

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
  const { alerts, cameras, rules, suggestions, dropSuggestion, cases, ack, hasOlder, loadOlder } =
    useLiveData();
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

  // Closed rows come a page at a time; when the loaded events run out, the API gives the next.
  // Unanswered staff questions pile up on a busy day; the first few, then the rest on demand.
  const [allQuestions, setAllQuestions] = useState(false);
  const [shown, setShown] = useState(CLOSED_PAGE);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const visible = closed.slice(0, shown);
  // A bar without a rule threshold measures against the day's longest loaded alert, shown or not.
  const sameDay = (items: AlertItem[]) => {
    const key = items[0] ? dayKey(items[0].opened_at) : '';
    return closed.filter((a) => dayKey(a.opened_at) === key);
  };
  const canShowMore = closed.length > shown || hasOlder;
  async function showMore() {
    setMoreBusy(true);
    setMoreError(null);
    try {
      if (closed.length < shown + CLOSED_PAGE && hasOlder) await loadOlder();
      setShown((n) => n + CLOSED_PAGE);
    } catch (e) {
      setMoreError(e instanceof Error ? e.message : 'Nu am putut încărca alertele mai vechi.');
    } finally {
      setMoreBusy(false);
    }
  }

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
                groupByDay(visible).map((g) => (
                  <section key={g.label} className="alerts-day" aria-label={`${g.label} · închise`}>
                    <h2 className="feed-group">{g.label} · închise</h2>
                    <AlertFeed
                      variant="rows"
                      items={g.items}
                      zoneName={zone}
                      showSnapshot
                      cases={cases}
                      limit={limitsFor(sameDay(g.items), ruleById)}
                    />
                  </section>
                ))}
              {showClosed && canShowMore && (
                <div className="alerts-more">
                  <button
                    type="button"
                    className="btn"
                    disabled={moreBusy}
                    aria-busy={moreBusy}
                    onClick={showMore}
                  >
                    {moreBusy ? 'Se încarcă…' : 'Mai multe'}
                  </button>
                  {moreError && (
                    <p className="error small" role="alert">
                      {moreError}
                    </p>
                  )}
                </div>
              )}
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
                (allQuestions ? suggestions : suggestions.slice(0, QUESTIONS_SHOWN)).map((s) => (
                  <SuggestionCard
                    key={s.suggestion_id}
                    variant="question"
                    suggestion={s}
                    cameraName={cameras.find((c) => c.id === s.camera_id)?.name}
                    onResolved={dropSuggestion}
                  />
                ))}
              {canReview && !allQuestions && suggestions.length > QUESTIONS_SHOWN && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm alerts-more-q"
                  onClick={() => setAllQuestions(true)}
                >
                  Încă {suggestions.length - QUESTIONS_SHOWN}{' '}
                  {suggestions.length - QUESTIONS_SHOWN === 1 ? 'întrebare' : 'întrebări'}
                </button>
              )}
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
