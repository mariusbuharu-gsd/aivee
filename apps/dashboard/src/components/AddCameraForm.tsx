import { useCallback, useState, type FormEvent } from 'react';
import type { CameraView } from '../api/client';
import { useApi } from '../api/context';
import {
  BRANDS,
  RTSP_PORT,
  brandInfo,
  buildRtspUrl,
  checkHost,
  maskPassword,
  type CameraBrand,
} from '../devices/rtsp';
import { CLOUD_FRAMES_SCHEME } from '../live/source';
import { useCameraTest } from '../devices/useCameraTest';
import { useCapabilities } from '../state/capabilitiesContext';
import { Banner } from '../ui/Banner';
import { BusyLabel } from '../ui/Eyes';
import { Select } from '../ui/Select';
import { PasswordInput, Segmented } from '../ui/controls';
import { CameraTestOutcome } from './CameraTestOutcome';
import { TapoGuide } from './TapoGuide';

/** The edge's CAMERA_ID default: the id here must match it or the edge ignores the config. */
export const DEFAULT_CAMERA_ID = 'cam-01';
export const DEFAULT_DEVICE = 'edge-01';
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

/** What the owner has: an IP camera (the usual case), this phone, or anything else (installer). */
export type CameraKind = 'ip' | 'phone' | 'raw';

const KINDS: { value: CameraKind; label: string }[] = [
  { value: 'ip', label: 'Cameră IP' },
  { value: 'phone', label: 'Telefon' },
  { value: 'raw', label: 'Altă sursă' },
];

type Field = 'name' | 'host' | 'user' | 'password' | 'path' | 'port' | 'source' | 'id' | 'device';

/**
 * "Adaugă cameră". For an IP camera the owner picks the brand and types IP, user and password;
 * the RTSP address of the detection substream is built from the brand's template and shown only
 * with the password masked. A phone becomes a cloud camera (the QR follows). "Altă sursă" keeps
 * the raw address for installers. Id and device sit under "Avansat", prefilled.
 */
export function AddCameraForm({
  onCreated,
  defaultId = DEFAULT_CAMERA_ID,
  defaultDevice = DEFAULT_DEVICE,
  onCancel,
}: {
  onCreated?: (camera: CameraView) => void;
  defaultId?: string;
  /** The device the location's other cameras use: a second camera goes on the same box. */
  defaultDevice?: string;
  /** Shown as "Renunță" when the form sits in a dialog. */
  onCancel?: () => void;
}) {
  const api = useApi();
  const caps = useCapabilities();
  const [kind, setKind] = useState<CameraKind>('ip');
  const [id, setId] = useState(defaultId);
  const [name, setName] = useState('');
  const [brand, setBrand] = useState<CameraBrand>('tapo');
  const [host, setHost] = useState('');
  const [user, setUser] = useState(brandInfo('tapo').user);
  const [password, setPassword] = useState('');
  const [path, setPath] = useState('');
  const [port, setPort] = useState(RTSP_PORT);
  const [source, setSource] = useState('');
  const [device, setDevice] = useState(defaultDevice);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Partial<Record<Field, string>>>({});
  const [guideOpen, setGuideOpen] = useState(false);
  const openGuide = useCallback(() => setGuideOpen(true), []);

  const info = brandInfo(brand);
  const ipSource = buildRtspUrl({ brand, host, user, password, path, port });
  const finalSource =
    kind === 'ip'
      ? ipSource
      : kind === 'phone'
        ? `${CLOUD_FRAMES_SCHEME}${id.trim()}`
        : source.trim();

  function pickBrand(next: CameraBrand) {
    // Swap the prefilled user only while the owner has not typed their own.
    if (user === info.user) setUser(brandInfo(next).user);
    setBrand(next);
  }

  function check() {
    const f: typeof fields = {};
    if (!name.trim()) f.name = 'Dă-i camerei un nume, de exemplu „Sala principală”.';
    if (kind === 'ip') {
      const h = checkHost(host);
      if (h) f.host = h;
      if (!user.trim()) f.user = 'Scrie utilizatorul contului camerei.';
      if (!password) f.password = 'Scrie parola contului camerei.';
      if (brand === 'other' && !/^\d{1,5}$/.test(port.trim()))
        f.port = 'Portul e un număr, de obicei 554.';
    }
    if (kind === 'raw' && !source.trim()) f.source = 'Scrie adresa sursei (RTSP/HTTP sau index).';
    if (!ID_RE.test(id.trim())) f.id = 'Fără spații: litere, cifre, „-” și „_”, de exemplu cam-01.';
    if (device.trim() && !ID_RE.test(device.trim())) {
      f.device = 'Fără spații: litere, cifre, „-” și „_”, de exemplu edge-01.';
    }
    setFields(f);
    return Object.keys(f).length === 0;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !check()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createCamera({
        id: id.trim(),
        name: name.trim(),
        source: finalSource,
        device: device.trim() || DEFAULT_DEVICE,
      });
      onCreated?.(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut adăuga camera');
    } finally {
      setBusy(false);
    }
  }

  const err = (k: Field) =>
    fields[k] ? { 'aria-invalid': true, 'aria-describedby': `cam-${k}-err` } : {};
  const msg = (k: Field) =>
    fields[k] && (
      <small id={`cam-${k}-err`} className="field-error">
        {fields[k]}
      </small>
    );

  return (
    <form className="stack-form add-camera" onSubmit={submit} noValidate>
      <Segmented label="Ce cameră adaugi?" value={kind} options={KINDS} onChange={setKind} />
      <div className="field">
        <label htmlFor="cam-name">Nume</label>
        <input
          id="cam-name"
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="ex. Sala principală"
          {...err('name')}
        />
        {msg('name')}
      </div>

      {kind === 'ip' && (
        <>
          <Select
            label="Marca"
            value={brand}
            options={BRANDS.map((b) => ({ value: b.value, label: b.label }))}
            onChange={pickBrand}
          />
          <div className="field">
            <label htmlFor="cam-host">Adresa IP</label>
            <input
              id="cam-host"
              className="input mono"
              value={host}
              inputMode="decimal"
              autoComplete="off"
              spellCheck={false}
              placeholder="192.168.1.20"
              onChange={(e) => setHost(e.target.value)}
              {...err('host')}
            />
            {msg('host') || (
              <small className="muted small">
                O găsești în aplicația camerei sau în lista de dispozitive a routerului.
              </small>
            )}
          </div>
          <div className="field-pair">
            <div className="field">
              <label htmlFor="cam-user">Utilizator</label>
              <input
                id="cam-user"
                className="input"
                value={user}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setUser(e.target.value)}
                {...err('user')}
              />
              {msg('user')}
            </div>
            <div>
              <PasswordInput
                id="cam-password"
                label="Parolă"
                value={password}
                autoComplete="new-password"
                onChange={(e) => setPassword(e.target.value)}
                {...err('password')}
              />
              {msg('password')}
            </div>
          </div>
          {brand === 'tapo' ? (
            <TapoGuide open={guideOpen} onToggle={setGuideOpen} />
          ) : (
            <p className="muted small">{info.hint}</p>
          )}
          {brand === 'other' && (
            <div className="field-pair">
              <div className="field">
                <label htmlFor="cam-path">Calea fluxului</label>
                <input
                  id="cam-path"
                  className="input mono"
                  value={path}
                  placeholder="/stream2"
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => setPath(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="cam-port">Port</label>
                <input
                  id="cam-port"
                  className="input mono"
                  value={port}
                  inputMode="numeric"
                  onChange={(e) => setPort(e.target.value)}
                  {...err('port')}
                />
                {msg('port')}
              </div>
            </div>
          )}
          {caps?.camera_test ? (
            <CameraTest
              source={ipSource}
              device={device.trim() || undefined}
              ready={!checkHost(host) && !!user.trim() && !!password}
              tapo={brand === 'tapo'}
              onAuthProblem={openGuide}
            />
          ) : (
            <p className="muted small">
              După ce o adaugi, imaginea apare pe cardul camerei în câteva secunde.
            </p>
          )}
        </>
      )}

      {kind === 'phone' && (
        <p className="muted">
          Primești un cod QR: îl scanezi cu telefonul, intri în cont și apeși „Pornește camera”.
          Telefonul trimite imagini cât timp pagina rămâne deschisă.
        </p>
      )}

      {kind === 'raw' && (
        <div className="field">
          <label htmlFor="cam-source">Adresa sursei (RTSP/HTTP sau index)</label>
          <input
            id="cam-source"
            className="input mono"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="rtsp://192.168.1.20:554/stream1"
            autoComplete="off"
            spellCheck={false}
            {...err('source')}
          />
          {msg('source') || (
            <small className="muted small">
              Cu utilizator și parolă, dacă are. În listă le ascundem.
            </small>
          )}
        </div>
      )}

      <details className="tech" open={!!(fields.id || fields.device)}>
        <summary>Avansat, pentru instalator</summary>
        {kind === 'ip' && (
          <p className="small">
            Adresa folosită: <span className="mono">{maskPassword(ipSource)}</span>
          </p>
        )}
        <div className="field-pair">
          <div className="field">
            <label htmlFor="cam-id">Id cameră</label>
            <input
              id="cam-id"
              className="input mono"
              value={id}
              onChange={(e) => setId(e.target.value)}
              {...err('id')}
            />
            {msg('id')}
          </div>
          <div className="field">
            <label htmlFor="cam-device">Dispozitiv</label>
            <input
              id="cam-device"
              className="input mono"
              value={device}
              onChange={(e) => setDevice(e.target.value)}
              {...err('device')}
            />
            {msg('device')}
          </div>
        </div>
        <p className="muted small">
          Id-ul trebuie să fie același cu CAMERA_ID de pe dispozitiv (implicit {DEFAULT_CAMERA_ID}).
          L-am completat noi; schimbă-l doar dacă l-ai schimbat și pe dispozitiv.
        </p>
      </details>
      {error && (
        <Banner tone="error" title="Camera nu a fost adăugată.">
          {error}
        </Banner>
      )}
      <div className="row-actions">
        <button className="btn btn-primary" type="submit" disabled={busy}>
          <BusyLabel busy={busy} idle="Adaugă camera">
            Se adaugă…
          </BusyLabel>
        </button>
        {onCancel && (
          <button className="btn btn-ghost" type="button" onClick={onCancel} disabled={busy}>
            Renunță
          </button>
        )}
      </div>
    </form>
  );
}

/** "Testează camera": the device opens the address once and sends back a blurred still. */
function CameraTest({
  source,
  device,
  ready,
  tapo,
  onAuthProblem,
}: {
  source: string;
  device?: string;
  /** IP, user and password are filled in. */
  ready: boolean;
  tapo: boolean;
  /** The camera refused the account: the form opens the Tapo guide. */
  onAuthProblem: () => void;
}) {
  const test = useCameraTest();
  // A result belongs to the address it was taken with; editing a field hides it.
  const stale = test.key !== source;

  async function run() {
    const problem = await test.run({ source, device: device ?? null }, source);
    if (problem?.code === 'camera_auth') onAuthProblem();
  }

  return (
    <div className="camera-test">
      <button
        type="button"
        className="btn"
        onClick={() => void run()}
        disabled={test.busy || !ready}
        title={ready ? undefined : 'Completează adresa IP, utilizatorul și parola'}
      >
        <BusyLabel busy={test.busy} idle="Testează camera">
          Se testează…
        </BusyLabel>
      </button>
      {!stale && <CameraTestOutcome frame={test.frame} problem={test.problem} tapo={tapo} />}
    </div>
  );
}
