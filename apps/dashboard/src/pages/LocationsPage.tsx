import { useCallback, useEffect, useState, type FormEvent } from 'react';
import type { Location, LocationType } from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';

const LOCATION_TYPES: { value: LocationType; label: string }[] = [
  { value: 'restaurant', label: 'Restaurant' },
  { value: 'terrace', label: 'Terasă / bar' },
  { value: 'event', label: 'Eveniment' },
  { value: 'shop', label: 'Magazin' },
  { value: 'other', label: 'Altceva' },
];
const typeLabel = (t: string) => LOCATION_TYPES.find((x) => x.value === t)?.label ?? t;

const slug = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40);

export function LocationsPage() {
  const api = useApi();
  const { me, location, setLocation, refresh } = useAuth();
  const [locations, setLocations] = useState<Location[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const first = me?.locations.length === 0;

  const load = useCallback(
    () =>
      api
        .listLocations()
        .then(setLocations, (e: unknown) => setError(e instanceof Error ? e.message : String(e))),
    [api],
  );
  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await Promise.all([load(), refresh()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Locații</h1>
        <p className="muted">
          {first
            ? 'Începe cu prima locație. Apoi conectezi dispozitivul și camerele ei.'
            : `Toate locațiile firmei ${me?.org.name ?? ''}. Fiecare are camerele, regulile și echipa ei.`}
        </p>
      </header>
      <div className="two-col">
        <section aria-labelledby="loc-h">
          <h2 id="loc-h">Locațiile tale</h2>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {locations.length === 0 ? (
            <p className="muted empty">Nicio locație încă.</p>
          ) : (
            <ul className="locations">
              {locations.map((l) =>
                editing === l.id ? (
                  <li key={l.id} className="location-row">
                    <LocationForm
                      initial={l}
                      submitLabel="Salvează"
                      onCancel={() => setEditing(null)}
                      onSubmit={(v) =>
                        run(async () => {
                          await api.updateLocation(l.id, {
                            name: v.name,
                            type: v.type,
                            telegram_chat_id: v.telegram_chat_id || null,
                          });
                          setEditing(null);
                        })
                      }
                    />
                  </li>
                ) : (
                  <li
                    key={l.id}
                    className={`location-row ${location?.id === l.id ? 'is-current' : ''}`}
                  >
                    <div className="member-who">
                      <strong>{l.name}</strong>
                      <span className="small muted mono">
                        {l.id} · {typeLabel(l.type)}
                        {l.telegram_chat_id ? ' · Telegram conectat' : ''}
                      </span>
                    </div>
                    {location?.id === l.id ? (
                      <span className="pill pill-live">curentă</span>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setLocation(l.id)}
                      >
                        Deschide
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setEditing(l.id)}
                    >
                      Modifică
                    </button>
                    <DeleteButton
                      name={l.name}
                      onConfirm={() => run(() => api.deleteLocation(l.id))}
                    />
                  </li>
                ),
              )}
            </ul>
          )}
        </section>
        <aside className="side-col">
          <div className="card">
            <h2 className="h3">{first ? 'Prima locație' : 'Locație nouă'}</h2>
            <LocationForm
              submitLabel="Adaugă locația"
              onSubmit={(v) =>
                run(async () => {
                  const created = await api.createLocation({
                    ...v,
                    telegram_chat_id: v.telegram_chat_id || null,
                  });
                  await refresh();
                  setLocation(created.id);
                })
              }
            />
          </div>
        </aside>
      </div>
    </div>
  );
}

function DeleteButton({ name, onConfirm }: { name: string; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  return asking ? (
    <span className="confirm">
      <span className="small muted">Ștergi {name}?</span>
      <button type="button" className="btn btn-danger btn-sm" onClick={onConfirm}>
        Șterge
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(false)}>
        Anulează
      </button>
    </span>
  ) : (
    <button
      type="button"
      className="btn btn-ghost btn-sm btn-danger"
      onClick={() => setAsking(true)}
    >
      Șterge
    </button>
  );
}

function LocationForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: Location;
  submitLabel: string;
  onSubmit: (v: Location) => Promise<void> | void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [id, setId] = useState(initial?.id ?? '');
  const [idTouched, setIdTouched] = useState(!!initial);
  const [type, setType] = useState(initial?.type ?? 'restaurant');
  const [telegram, setTelegram] = useState(initial?.telegram_chat_id ?? '');
  const [error, setError] = useState<string | null>(null);
  const prefix = initial ? `loc-${initial.id}` : 'loc-new';

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError('Scrie numele locației.');
    const finalId = idTouched ? id : slug(name);
    if (!/^[a-z0-9-]{2,40}$/.test(finalId)) {
      return setError('Id-ul poate avea litere mici, cifre și cratimă (2–40).');
    }
    setError(null);
    void onSubmit({ id: finalId, name: name.trim(), type, telegram_chat_id: telegram.trim() });
  }

  return (
    <form className="stack-form" onSubmit={submit} noValidate>
      <label className="field">
        <span>Nume</span>
        <input
          id={`${prefix}-name`}
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="ex. Terasa din parc"
        />
      </label>
      {!initial && (
        <label className="field">
          <span>Id (apare în configurarea dispozitivului)</span>
          <input
            id={`${prefix}-id`}
            className="input mono"
            value={idTouched ? id : slug(name)}
            onChange={(e) => {
              setIdTouched(true);
              setId(e.target.value);
            }}
          />
        </label>
      )}
      <label className="field">
        <span>Tip</span>
        <select
          id={`${prefix}-type`}
          className="input"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          {LOCATION_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Chat Telegram (opțional)</span>
        <input
          id={`${prefix}-tg`}
          className="input mono"
          value={telegram}
          onChange={(e) => setTelegram(e.target.value)}
          placeholder="-1001234567890"
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="row-actions">
        <button type="submit" className="btn btn-primary">
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Anulează
          </button>
        )}
      </div>
    </form>
  );
}
