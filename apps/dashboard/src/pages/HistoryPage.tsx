import { useCallback, useEffect, useId, useState } from 'react';
import { useSearchParams } from 'react-router';
import type { AuditEntry, AuditQuery, Member } from '../api/client';
import { useApi } from '../api/context';
import { useAuth, useLocationId } from '../auth/context';
import { ROLE_LABEL } from '../auth/session';
import { duration } from '../alerts/format';
import { Icon } from '../components/Icon';
import { describeChanges } from '../history/diff';
import {
  foldHistory,
  itemTime,
  type AlertThread,
  type HistoryItem,
  type Stage,
} from '../history/threads';
import { Banner } from '../ui/Banner';
import { Select } from '../ui/Select';
import { EmptyState, Segmented, Skeleton } from '../ui/controls';
import './HistoryPage.css';

const KINDS: { value: string; label: string }[] = [
  { value: '', label: 'Toate' },
  { value: 'alert', label: 'Alerte' },
  { value: 'staff', label: 'Personal' },
  { value: 'rule', label: 'Reguli' },
  { value: 'zones', label: 'Zone' },
  { value: 'camera', label: 'Camere' },
  { value: 'device', label: 'Dispozitive' },
  { value: 'user', label: 'Invitații' },
  { value: 'member', label: 'Echipă' },
  { value: 'location', label: 'Locații' },
  { value: 'auth', label: 'Autentificări' },
];

const PERIODS: { value: string; label: string; days: number | null }[] = [
  { value: 'today', label: 'Azi', days: 0 },
  { value: '7', label: '7 zile', days: 7 },
  { value: '30', label: '30 de zile', days: 30 },
  { value: 'all', label: 'Tot', days: null },
];

function periodStart(days: number | null): string | undefined {
  if (days === null) return undefined;
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

const when = (iso: string) =>
  new Date(iso).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' });

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Azi';
  if (d.toDateString() === yesterday.toDateString()) return 'Ieri';
  return d.toLocaleDateString('ro-RO', { weekday: 'long', day: 'numeric', month: 'long' });
}

function byDay(items: HistoryItem[]): { label: string; items: HistoryItem[] }[] {
  const out: { label: string; items: HistoryItem[] }[] = [];
  for (const i of items) {
    const label = dayLabel(itemTime(i));
    const last = out[out.length - 1];
    if (last?.label === label) last.items.push(i);
    else out.push({ label, items: [i] });
  }
  return out;
}

export function HistoryPage() {
  const api = useApi();
  const locationId = useLocationId();
  const { can, me } = useAuth();
  const ownOnly = !can('audit.view');
  const [kind, setKind] = useState('');
  const [params] = useSearchParams();
  // "Vezi ce a făcut în Istoric" from Echipă opens the page filtered on that person.
  const [actor, setActor] = useState(() => params.get('cine') ?? '');
  const [period, setPeriod] = useState('7');
  const [members, setMembers] = useState<Member[]>([]);
  const [result, setResult] = useState<{
    key: string;
    items: AuditEntry[];
    next: string | null;
    error: string | null;
  } | null>(null);

  const query = useCallback(
    (before?: string): AuditQuery => ({
      location_id: locationId,
      kind: kind || undefined,
      actor: actor || undefined,
      from: periodStart(PERIODS.find((p) => p.value === period)?.days ?? null),
      before,
      limit: 50,
    }),
    [locationId, kind, actor, period],
  );
  const key = `${locationId}|${kind}|${actor}|${period}`;
  const loading = result?.key !== key;
  const items = result?.items ?? [];
  const next = result?.next ?? null;
  const error = result?.error ?? null;

  useEffect(() => {
    let alive = true;
    api.listAudit(query()).then(
      (page) => alive && setResult({ key, items: page.items, next: page.next_before, error: null }),
      (e: unknown) =>
        alive &&
        setResult({
          key,
          items: [],
          next: null,
          error: e instanceof Error ? e.message : String(e),
        }),
    );
    return () => {
      alive = false;
    };
  }, [api, query, key]);

  useEffect(() => {
    if (!can('users.manage')) return;
    let alive = true;
    api.listMembers(locationId).then(
      (m) => alive && setMembers(m),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [api, can, locationId]);

  const actors = [
    { value: '', label: 'Oricine' },
    ...(me
      ? [
          {
            value: me.user.id,
            label: `${me.user.name} (tu)`,
            leading: <span className="avatar">{initials(me.user.name)}</span>,
          },
        ]
      : []),
    ...members
      .filter((m) => m.user_id !== me?.user.id)
      .map((m) => ({
        value: m.user_id,
        label: m.name,
        hint: ROLE_LABEL[m.role],
        leading: <span className="avatar">{initials(m.name)}</span>,
      })),
  ];

  async function more() {
    if (!next) return;
    const page = await api.listAudit(query(next));
    setResult((prev) =>
      prev ? { ...prev, items: [...prev.items, ...page.items], next: page.next_before } : prev,
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Istoric</h1>
        <p className="muted">
          {ownOnly
            ? 'Ce ai făcut tu în această locație.'
            : 'Tot ce s-a întâmplat în locație: cine, ce și când. Istoricul nu se poate modifica.'}
        </p>
      </header>
      <form className="filters" aria-label="Filtre istoric" onSubmit={(e) => e.preventDefault()}>
        <KindFilter value={kind} onChange={setKind} />
        {!ownOnly && (
          <Select
            id="audit-actor"
            label="Cine"
            searchable={actors.length > 6}
            searchPlaceholder="Caută o persoană"
            emptyText="Nimeni cu numele ăsta."
            value={actor}
            options={actors}
            onChange={setActor}
          />
        )}
        <Segmented
          label="Perioadă"
          value={period}
          options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
          onChange={setPeriod}
        />
      </form>
      {(kind || actor) && (
        <div className="chips" aria-label="Filtre active">
          {actor && (
            <button type="button" className="chip" onClick={() => setActor('')}>
              {actors.find((x) => x.value === actor)?.label}
              <span aria-hidden="true">×</span>
              <span className="sr-only">Scoate filtrul</span>
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setKind('');
              setActor('');
            }}
          >
            Șterge filtrele
          </button>
        </div>
      )}
      {error && (
        <Banner tone="error" title="Nu am putut încărca istoricul.">
          {error}
        </Banner>
      )}
      {loading ? (
        <Skeleton rows={4} label="Se încarcă istoricul" />
      ) : items.length === 0 ? (
        <EmptyState icon="history" title="Nimic în această perioadă">
          {kind || actor
            ? 'Încearcă fără filtre sau o perioadă mai lungă.'
            : 'Ce se întâmplă în locație apare aici.'}
        </EmptyState>
      ) : (
        byDay(foldHistory(items)).map((g) => (
          <section key={g.label} aria-label={g.label}>
            <h2 className="feed-group">{g.label}</h2>
            <ol className="audit" aria-label={`Intrări în istoric, ${g.label}`}>
              {g.items.map((i) =>
                i.type === 'thread' ? (
                  <ThreadRow key={`t-${i.id}`} t={i} />
                ) : (
                  <AuditRow key={i.entry.id} e={i.entry} />
                ),
              )}
            </ol>
          </section>
        ))
      )}
      {next && (
        <button type="button" className="btn" onClick={more}>
          Mai vechi
        </button>
      )}
    </div>
  );
}

function AuditRow({ e }: { e: AuditEntry }) {
  const machine = e.actor.kind !== 'user';
  const changes = describeChanges(e.before, e.after);
  const changed = e.before !== null && e.after !== null;
  return (
    <li className={`audit-row${machine ? ' is-machine' : ''}`}>
      <time className="mono small muted" dateTime={e.at}>
        {when(e.at)}
      </time>
      <ActorBadge actor={e.actor} />
      <div className="audit-body">
        <p>{e.summary_ro}</p>
        {changed && changes.length > 0 && (
          <ul className="changes">
            {changes.slice(0, 4).map((c) => (
              <li key={c.label}>
                <span className="muted">{c.label}:</span> <s>{c.from}</s> → <strong>{c.to}</strong>
              </li>
            ))}
          </ul>
        )}
        {(e.before !== null || e.after !== null) && (
          <details className="tech">
            <summary>Detalii tehnice</summary>
            <span className="mono small muted">{e.kind}</span>
            <div className="diff">
              <div>
                <span className="small muted">Înainte</span>
                <pre className="json">{JSON.stringify(e.before, null, 2)}</pre>
              </div>
              <div>
                <span className="small muted">După</span>
                <pre className="json">{JSON.stringify(e.after, null, 2)}</pre>
              </div>
            </div>
          </details>
        )}
      </div>
    </li>
  );
}

/** People get their initials; the edge device and AiVee itself get an icon, in grey. */
function ActorBadge({ actor }: { actor: AuditEntry['actor'] }) {
  if (actor.kind === 'user') {
    return (
      <span className="audit-actor is-user" title={actor.name} aria-hidden="true">
        {initials(actor.name)}
      </span>
    );
  }
  const what = actor.kind === 'device' ? `Dispozitivul ${actor.name}` : 'AiVee (sistem)';
  return (
    <span className={`audit-actor is-${actor.kind}`} title={what}>
      <Icon name={actor.kind === 'device' ? 'devices' : 'info'} size={16} label={what} />
    </span>
  );
}

/** Filter by kind with one press: buttons instead of a dropdown. */
function KindFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <div className="kind-field">
      <span id={id} className="seg-label">
        Tip
      </span>
      <div className="kind-filter" role="group" aria-labelledby={id}>
        {KINDS.map((k) => (
          <button
            key={k.value}
            type="button"
            className="kind-btn"
            aria-pressed={value === k.value}
            onClick={() => onChange(k.value)}
          >
            {k.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The four stages a guest cares about; a re-alert slots in when it happened. */
const STAGE_ORDER: Stage[] = ['opened', 'acknowledged', 'realerted', 'arrived', 'closed'];

const offset = (s: number) => `+${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

function stageLabel(t: AlertThread, stage: Stage): { text: string; reached: boolean } | null {
  const step = t.steps.find((s) => s.stage === stage);
  switch (stage) {
    case 'opened':
      return { text: 'pornită', reached: !!step };
    case 'acknowledged':
      if (step) {
        const who =
          step.entry.actor.kind === 'user'
            ? `${step.entry.actor.name.split(/\s+/)[0]} a preluat`
            : 'preluată';
        return { text: who, reached: true };
      }
      return {
        text: t.steps.some((s) => s.stage === 'arrived') ? 'fără preluare' : 'preluată',
        reached: false,
      };
    case 'realerted':
      return step ? { text: 'reamintită', reached: true } : null;
    case 'arrived':
      return { text: 'a ajuns', reached: !!step };
    case 'closed':
      return { text: 'închisă', reached: !!step };
  }
}

/** One alert, one row: a mini timeline and how long it lasted; the raw entries on demand. */
function ThreadRow({ t }: { t: AlertThread }) {
  const stages = STAGE_ORDER.map((s) => ({ s, l: stageLabel(t, s) })).filter(
    (x): x is { s: Stage; l: { text: string; reached: boolean } } => x.l !== null,
  );
  const closed = t.steps.some((s) => s.stage === 'closed');
  return (
    <li className="audit-row is-thread">
      <time className="mono small muted" dateTime={t.start}>
        {when(t.start)}
      </time>
      <span className="audit-actor is-alert" title="Alertă">
        <Icon name="alerts" size={16} label="Alertă" />
      </span>
      <div className="audit-body">
        <p>
          <strong>{t.title}</strong>
        </p>
        <ol className="thread-tl" aria-label={`Cronologia alertei de la ${t.label}`}>
          {stages.map(({ s, l }) => {
            const step = t.steps.find((x) => x.stage === s);
            return (
              <li key={s} className={`is-${s}${l.reached ? ' is-reached' : ''}`}>
                <span className="th-dot" aria-hidden="true" />
                <span className="th-text">
                  {l.text}
                  {step && step.offset_s > 0 && (
                    <span className="mono muted"> {offset(step.offset_s)}</span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
        <details className="tech">
          <summary>Toate intrările ({t.entries.length})</summary>
          <ol className="audit thread-entries">
            {[...t.entries].reverse().map((e) => (
              <AuditRow key={e.id} e={e} />
            ))}
          </ol>
        </details>
      </div>
      <span className="thread-total">
        {t.duration_s !== null ? (
          <>
            <span className="mono">{duration(t.duration_s)}</span>
            <span className="small muted">în total</span>
          </>
        ) : (
          !closed && <span className="small muted">încă deschisă</span>
        )}
      </span>
    </li>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}
