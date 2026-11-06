import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import type { CameraView, Location } from '../api/client';
import { useApi } from '../api/context';
import { TelegramConnect } from '../components/TelegramConnect';
import { camerasCount } from '../rules/count';
import { useAuth } from '../auth/context';
import { LOCATION_TYPES, locationTypeLabel as typeLabel } from '../auth/session';
import { Banner } from '../ui/Banner';
import { ConfirmDialog, Dialog } from '../ui/Dialog';
import { Menu } from '../ui/Menu';
import { Select } from '../ui/Select';
import { EmptyState } from '../ui/controls';
import { useToast } from '../ui/toast';
import './LocationsPage.css';

const slug = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40);

/** The id comes from the name and is never shown; a short suffix keeps it valid and unique. */
function locationId(name: string, taken: readonly string[]) {
  const base = slug(name).slice(0, 34).replace(/-$/, '');
  const ok = (id: string) => /^[a-z0-9-]{2,40}$/.test(id) && !taken.includes(id);
  if (ok(base)) return base;
  for (let n = 2; n < 100; n++) {
    const id = base ? `${base}-${n}` : `locatie-${n}`;
    if (ok(id)) return id;
  }
  return `locatie-${Date.now().toString(36)}`;
}

const isToday = (iso: string) => new Date(iso).toDateString() === new Date().toDateString();

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "2/3 camere online", "nicio cameră". */
const camerasLabel = ({ total, online }: { total: number; online: number }) =>
  total === 0 ? camerasCount(0) : `${online}/${camerasCount(total)} online`;

export function LocationsPage() {
  const api = useApi();
  const { me, location, setLocation, refresh } = useAuth();
  const [locations, setLocations] = useState<Location[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Location | null>(null);
  const [adding, setAdding] = useState(false);
  /** Cameras are listed for the current location only. */
  const [cameras, setCameras] = useState<CameraView[] | null>(null);
  /** Alerts opened today, by location; missing when the API refuses or fails. */
  const [alertsToday, setAlertsToday] = useState<Record<string, number>>({});
  const toast = useToast();
  const navigate = useNavigate();
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

  const currentId = location?.id;
  useEffect(() => {
    if (!currentId) return;
    let live = true;
    api.listCameras().then(
      (c) => live && setCameras(c),
      () => live && setCameras(null),
    );
    return () => {
      live = false;
    };
  }, [api, currentId]);

  const ids = locations.map((l) => l.id).join(',');
  useEffect(() => {
    let live = true;
    for (const id of ids ? ids.split(',') : []) {
      api.listAlertCases({ location_id: id, limit: 200 }).then(
        (cases) =>
          live &&
          setAlertsToday((a) => ({ ...a, [id]: cases.filter((c) => isToday(c.opened_at)).length })),
        () => undefined,
      );
    }
    return () => {
      live = false;
    };
  }, [api, ids]);

  function addFirstCamera(l: Location) {
    if (location?.id !== l.id) setLocation(l.id);
    navigate('/dispozitive');
  }

  async function create(v: Location) {
    await run(async () => {
      const created = await api.createLocation({
        ...v,
        telegram_chat_id: v.telegram_chat_id || null,
      });
      setAdding(false);
      await refresh();
      setLocation(created.id);
      toast({
        title: `„${created.name}” a fost adăugată`,
        text: 'Acum leagă dispozitivul și camerele ei din Dispozitive.',
      });
    });
  }

  const taken = locations.map((l) => l.id);

  /** Every location's counts from `GET /api/locations`; else the current one's camera list. */
  const cameraCounts = (l: Location) => {
    if (l.cameras_total !== undefined) {
      return { total: l.cameras_total, online: l.cameras_online ?? 0 };
    }
    if (location?.id !== l.id || !cameras) return null;
    return { total: cameras.length, online: cameras.filter((c) => c.online).length };
  };

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
        <div className="locations-intro">
          <h1>Locații</h1>
          <p className="muted">
            {first
              ? 'Începe cu prima locație. Apoi conectezi dispozitivul și camerele ei.'
              : `Toate locațiile firmei ${me?.org.name ?? ''}. Fiecare are camerele, regulile și echipa ei.`}
          </p>
        </div>
        {!first && (
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            + Locație nouă
          </button>
        )}
      </header>
      <div className="locations-page">
        <section aria-labelledby="loc-h">
          <h2 id="loc-h">{first ? 'Prima locație' : 'Locațiile tale'}</h2>
          {error && <Banner tone="error" title={error} />}
          {first ? (
            <div className="card locations-first">
              <LocationForm taken={taken} submitLabel="Adaugă locația" onSubmit={create} />
            </div>
          ) : locations.length === 0 ? (
            <EmptyState icon="location" title="Nicio locație încă">
              Adaugă restaurantul, terasa sau evenimentul unde pui camerele, din „Locație nouă”.
            </EmptyState>
          ) : (
            <ul className="locations">
              {locations.map((l) => {
                const counts = cameraCounts(l);
                return editing === l.id ? (
                  <li key={l.id} className="location-row">
                    <LocationForm
                      initial={l}
                      taken={taken}
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
                    className={`location-row location-card ${location?.id === l.id ? 'is-current' : ''}`}
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
                        {[
                          typeLabel(l.type),
                          counts ? camerasLabel(counts) : null,
                          l.id in alertsToday
                            ? plural(alertsToday[l.id] ?? 0, 'alertă azi', 'alerte azi')
                            : null,
                          l.telegram_chat_id ? 'Telegram conectat' : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
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
                    {(!l.telegram_chat_id || counts?.total === 0) && (
                      <div className="location-needs">
                        {counts?.total === 0 && (
                          <button
                            type="button"
                            className="btn btn-primary"
                            onClick={() => addFirstCamera(l)}
                          >
                            Adaugă prima cameră
                          </button>
                        )}
                        {!l.telegram_chat_id && (
                          <TelegramConnect locationId={l.id} onConnected={() => void load()} />
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
      {adding && (
        <Dialog
          title="Locație nouă"
          icon="location"
          className="dialog-sheet"
          onClose={() => setAdding(false)}
        >
          <LocationForm
            taken={taken}
            submitLabel="Adaugă locația"
            onSubmit={create}
            onCancel={() => setAdding(false)}
          />
        </Dialog>
      )}
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
  taken,
  submitLabel,
  onSubmit,
  onCancel,
  onTelegramConnected,
}: {
  initial?: Location;
  taken: readonly string[];
  submitLabel: string;
  onSubmit: (v: Location) => Promise<void> | void;
  onCancel?: () => void;
  onTelegramConnected?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [type, setType] = useState(initial?.type ?? 'restaurant');
  const [telegram, setTelegram] = useState(initial?.telegram_chat_id ?? '');
  const [telegramTouched, setTelegramTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prefix = initial ? `loc-${initial.id}` : 'loc-new';

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError('Scrie numele locației.');
    setError(null);
    void onSubmit({
      id: initial?.id ?? locationId(name, taken),
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
          data-autofocus={initial ? undefined : true}
        />
      </label>
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
