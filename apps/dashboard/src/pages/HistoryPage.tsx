import { useCallback, useEffect, useState } from 'react';
import type { AuditEntry, AuditQuery, Member } from '../api/client';
import { useApi } from '../api/context';
import { useAuth, useLocationId } from '../auth/context';

const KINDS: { value: string; label: string }[] = [
  { value: '', label: 'Toate' },
  { value: 'alert.', label: 'Alerte' },
  { value: 'staff.', label: 'Personal' },
  { value: 'rule.', label: 'Reguli' },
  { value: 'zones.', label: 'Zone' },
  { value: 'camera.', label: 'Camere' },
  { value: 'device.', label: 'Dispozitive' },
  { value: 'user.', label: 'Invitații' },
  { value: 'member.', label: 'Echipă' },
  { value: 'location.', label: 'Locații' },
  { value: 'auth.', label: 'Autentificări' },
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
  new Date(iso).toLocaleString('ro-RO', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });

export function HistoryPage() {
  const api = useApi();
  const locationId = useLocationId();
  const { can, me } = useAuth();
  const ownOnly = !can('audit.view');
  const [kind, setKind] = useState('');
  const [actor, setActor] = useState('');
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
        <label className="field">
          <span>Tip</span>
          <select
            id="audit-kind"
            className="input"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        {!ownOnly && (
          <label className="field">
            <span>Cine</span>
            <select
              id="audit-actor"
              className="input"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            >
              <option value="">Oricine</option>
              {me && <option value={me.user.id}>{me.user.name} (tu)</option>}
              {members
                .filter((m) => m.user_id !== me?.user.id)
                .map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.name}
                  </option>
                ))}
            </select>
          </label>
        )}
        <div className="field">
          <span id="period-l">Perioadă</span>
          <div className="segmented" role="group" aria-labelledby="period-l">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                type="button"
                className="btn btn-seg"
                aria-pressed={period === p.value}
                onClick={() => setPeriod(p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p className="muted" role="status">
          Se încarcă istoricul…
        </p>
      ) : items.length === 0 ? (
        <p className="muted empty">Nimic în această perioadă.</p>
      ) : (
        <ol className="audit" aria-label="Intrări în istoric">
          {items.map((e) => (
            <li key={e.id} className="audit-row">
              <time className="mono small muted" dateTime={e.at}>
                {when(e.at)}
              </time>
              <span className={`audit-actor is-${e.actor.kind}`} title={e.actor.name}>
                {e.actor.kind === 'user'
                  ? initials(e.actor.name)
                  : e.actor.kind === 'device'
                    ? 'ED'
                    : 'SY'}
              </span>
              <div className="audit-body">
                <p>{e.summary_ro}</p>
                <span className="mono small muted">{e.kind}</span>
                {(e.before !== null || e.after !== null) && (
                  <details className="audit-diff">
                    <summary>Vezi modificarea</summary>
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
          ))}
        </ol>
      )}
      {next && (
        <button type="button" className="btn" onClick={more}>
          Mai vechi
        </button>
      )}
    </div>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}
