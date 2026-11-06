import { useCallback, useEffect, useState, type FormEvent } from 'react';
import type { Location } from '../api/client';
import { useApi } from '../api/context';
import { TelegramConnect } from '../components/TelegramConnect';
import { useAuth } from '../auth/context';
import { LOCATION_TYPES, locationTypeLabel as typeLabel } from '../auth/session';
import { Banner } from '../ui/Banner';
import { ConfirmDialog } from '../ui/Dialog';
import { Menu } from '../ui/Menu';
import { Select } from '../ui/Select';
import { EmptyState } from '../ui/controls';
import { useToast } from '../ui/toast';

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
  const [deleting, setDeleting] = useState<Location | null>(null);
  const toast = useToast();
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
          {error && <Banner tone="error" title={error} />}
          {locations.length === 0 ? (
            <EmptyState icon="location" title="Nicio locație încă">
              Adaug-o pe prima din dreapta: restaurantul, terasa sau evenimentul unde pui camerele.
            </EmptyState>
          ) : (
            <ul className="locations">
              {locations.map((l) =>
                editing === l.id ? (
                  <li key={l.id} className="location-row">
                    <LocationForm
                      initial={l}
                      submitLabel="Salvează"
                      onCancel={() => setEditing(null)}
                      onTelegramConnected={() => void load()}
                      onSubmit={(v) =>
                        run(async () => {
                          await api.updateLocation(l.id, {
                            name: v.name,
                            type: v.type,
                            // Only a typed chat id is sent: the bot may have linked one meanwhile.
                            ...(v.telegram_chat_id === undefined
                              ? {}
                              : { telegram_chat_id: v.telegram_chat_id || null }),
                          });
                          setEditing(null);
                          toast({ title: `„${v.name}” a fost salvată` });
                        })
                      }
                    />
                  </li>
                ) : (
                  <li
                    key={l.id}
                    className={`location-row ${location?.id === l.id ? 'is-current' : ''}`}
                  >
                    <button
                      type="button"
                      className="location-open"
                      onClick={() => setLocation(l.id)}
                      disabled={location?.id === l.id}
                      aria-label={location?.id === l.id ? undefined : `Deschide ${l.name}`}
                    >
                      <strong>{l.name}</strong>
                      <span className="small muted">
                        {typeLabel(l.type)}
                        {l.telegram_chat_id ? ' · Telegram conectat' : ' · fără Telegram'}
                      </span>
                    </button>
                    {location?.id === l.id && <span className="pill pill-live">curentă</span>}
                    <Menu
                      label={`Acțiuni pentru ${l.name}`}
                      items={[
                        ...(location?.id === l.id
                          ? []
                          : [{ label: 'Deschide', onSelect: () => setLocation(l.id) }]),
                        { label: 'Modifică', onSelect: () => setEditing(l.id) },
                        { label: 'Șterge locația…', danger: true, onSelect: () => setDeleting(l) },
                      ]}
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
                  toast({
                    title: `„${created.name}” a fost adăugată`,
                    text: 'Acum leagă dispozitivul și camerele ei din Dispozitive.',
                  });
                })
              }
            />
          </div>
        </aside>
      </div>
      {deleting && (
        <ConfirmDialog
          title={`Ștergi definitiv locația „${deleting.name}”?`}
          confirmLabel="Șterge locația"
          confirmText={deleting.name}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await api.deleteLocation(deleting.id);
            await Promise.all([load(), refresh()]);
            toast({ title: `Locația „${deleting.name}” a fost ștearsă` });
          }}
        >
          <ul>
            <li>Camerele, zonele și regulile ei se șterg; dispozitivul nu mai trimite alerte.</li>
            <li>Echipa ei pierde accesul la locație.</li>
            <li>Istoricul și metricile ei nu se mai pot vedea.</li>
          </ul>
          <p className="small muted">Nu se poate anula.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function LocationForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  onTelegramConnected,
}: {
  initial?: Location;
  submitLabel: string;
  onSubmit: (v: Location) => Promise<void> | void;
  onCancel?: () => void;
  onTelegramConnected?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [id, setId] = useState(initial?.id ?? '');
  const [idTouched, setIdTouched] = useState(!!initial);
  const [type, setType] = useState(initial?.type ?? 'restaurant');
  const [telegram, setTelegram] = useState(initial?.telegram_chat_id ?? '');
  const [telegramTouched, setTelegramTouched] = useState(false);
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
    void onSubmit({
      id: finalId,
      name: name.trim(),
      type,
      telegram_chat_id: telegramTouched || !initial ? telegram.trim() : undefined,
    });
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
        <details className="tech">
          <summary>Avansat: id {idTouched ? id : slug(name) || '—'}</summary>
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
        </details>
      )}
      <Select
        id={`${prefix}-type`}
        label="Tip"
        value={type}
        options={LOCATION_TYPES}
        onChange={setType}
      />
      {initial && (
        <fieldset className="telegram-fieldset">
          <legend>Alerte pe Telegram</legend>
          <TelegramConnect locationId={initial.id} onConnected={onTelegramConnected} />
          <details className="tech">
            <summary>Avansat: id-ul chatului</summary>
            <label className="field">
              <span>Chat Telegram (opțional)</span>
              <input
                id={`${prefix}-tg`}
                className="input mono"
                value={telegram}
                onChange={(e) => {
                  setTelegramTouched(true);
                  setTelegram(e.target.value);
                }}
                placeholder="-1001234567890"
              />
              <small className="muted">
                Doar dacă știi deja id-ul grupului. Altfel folosește „Conectează Telegram”.
              </small>
            </label>
          </details>
        </fieldset>
      )}
      {error && <Banner tone="error" title={error} />}
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
