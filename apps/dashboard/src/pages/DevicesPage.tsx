import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import type { CameraPatch, CameraView, DashboardMetrics, DeviceView } from '../api/client';
import { useApi } from '../api/context';
import { DEFAULT_CAMERA_ID, DEFAULT_DEVICE } from '../components/AddCameraForm';
import { AddCamera } from '../components/AddCameraWizard';
import { Icon } from '../components/Icon';
import { QrCode } from '../components/QrCode';
import { StaffCaptureButton } from '../components/StaffCapture';
import { TestCameraDialog } from '../components/TestCameraDialog';
import type { Metrics } from '../contracts';
import { CameraThumb } from '../devices/CameraThumb';
import { cameraHealth, type CameraHealth, type CameraHealthState } from '../devices/health';
import { lastSeenRo, sinceRo } from '../devices/lastSeen';
import { maskSource } from '../devices/maskSource';
import { checkHost, maskPassword, parseSourceUrl, replaceCredentials } from '../devices/rtsp';
import { useDevices } from '../devices/useDevices';
import { useNow } from '../live/useNow';
import { isCloudFrames } from '../live/source';
import { isCloudCamera } from '../phone/sender';
import { useCapabilities } from '../state/capabilitiesContext';
import { useLiveData } from '../state/context';
import { ConfirmDialog, Dialog } from '../ui/Dialog';
import { Menu } from '../ui/Menu';
import { EmptyState, PasswordInput, Skeleton } from '../ui/controls';
import { plural } from '../ui/plural';
import { useToast } from '../ui/toast';
import './DevicesPage.css';
import { BusyLabel } from '../ui/Eyes';

/** "1 zonă se șterge" / "3 zone se șterg" / "nicio zonă". */
function willGo(n: number, one: string, many: string, none: string): string {
  if (n === 0) return none;
  return n === 1 ? `1 ${one} se șterge.` : `${n} ${many} se șterg.`;
}

const zonesPath = (id: string) => `/camere/${encodeURIComponent(id)}/zone`;

export function DevicesPage() {
  const { cameras, rules, loading, addCamera, removeCamera, metrics } = useLiveData();
  const api = useApi();
  const [removing, setRemoving] = useState<CameraView | null>(null);
  const navigate = useNavigate();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<CameraView | null>(null);
  const [phone, setPhone] = useState<CameraView | null>(null);
  const [testing, setTesting] = useState<CameraView | null>(null);
  const devices = useDevices();
  const canTest = !!useCapabilities()?.camera_test;
  // Prefill the edge default only while it is free; otherwise suggest the next id.
  const taken = new Set(cameras.map((c) => c.id));
  let next = DEFAULT_CAMERA_ID;
  for (let n = 2; taken.has(next); n++) next = `cam-${String(n).padStart(2, '0')}`;
  // A second IP camera goes on the box that already serves this location's cameras.
  const device = cameras.find((c) => !isCloudCamera(c))?.device ?? DEFAULT_DEVICE;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Camere</h1>
        {cameras.length > 0 && (
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            <Icon name="plus" /> Adaugă cameră
          </button>
        )}
      </header>
      {loading && cameras.length === 0 && <Skeleton rows={2} label="Se încarcă camerele" />}
      {!loading && cameras.length === 0 && (
        <EmptyState
          icon="devices"
          title="Nicio cameră încă"
          action={
            <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
              <Icon name="plus" /> Adaugă cameră
            </button>
          }
        >
          Adaug-o pe prima, apoi desenează mesele pe imaginea ei.
        </EmptyState>
      )}
      <ul className="cards">
        {cameras.map((c) => (
          <CameraCard
            key={c.id}
            camera={c}
            device={devices[c.device] ?? null}
            health={metrics?.devices.find((d) => d.device === c.device) ?? null}
            onEdit={() => setEditing(c)}
            onPhone={isCloudCamera(c) ? () => setPhone(c) : undefined}
            onTest={canTest && !isCloudCamera(c) ? () => setTesting(c) : undefined}
            onZones={() => navigate(zonesPath(c.id))}
            onRemove={() => setRemoving(c)}
          />
        ))}
      </ul>

      {metrics && metrics.devices.length > 0 && (
        <details className="tech device-system-tech">
          <summary>Detalii tehnice</summary>
          <SystemLine metrics={metrics} />
        </details>
      )}

      {adding && (
        <Dialog title="Adaugă o cameră" icon="devices" onClose={() => setAdding(false)}>
          <AddCamera
            key={next}
            cameras={cameras}
            defaultId={next}
            defaultDevice={device}
            onCancel={() => setAdding(false)}
            onCreated={(c) => {
              addCamera(c);
              setAdding(false);
              // A phone first needs to be started with the QR; zones come once it sends images.
              if (isCloudCamera(c)) {
                toast({ title: `Camera „${c.name}” a fost adăugată`, text: 'Scanează codul.' });
                setPhone(c);
                return;
              }
              toast({
                title: `Camera „${c.name}” a fost adăugată`,
                text: 'Desenează acum mesele și intrarea pe imagine.',
              });
              navigate(zonesPath(c.id));
            }}
          />
        </Dialog>
      )}
      {removing && (
        <ConfirmDialog
          title={`Scoți camera „${removing.name}”?`}
          confirmLabel="Scoate camera"
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await api.deleteCamera(removing.id);
            removeCamera(removing.id);
            toast({ title: `Camera „${removing.name}” a fost scoasă` });
          }}
        >
          <ul>
            <li>{willGo(removing.zones?.length ?? 0, 'zonă', 'zone', 'Nu are zone desenate.')}</li>
            <li>
              {willGo(
                rules.filter((r) => r.camera_id === removing.id).length,
                'regulă',
                'reguli',
                'Nu are reguli.',
              )}
            </li>
            <li>Alertele deschise se închid; cele vechi rămân în Istoric.</li>
          </ul>
        </ConfirmDialog>
      )}
      {editing && <EditCamera camera={editing} onClose={() => setEditing(null)} />}
      {phone && <PhoneQr camera={phone} onClose={() => setPhone(null)} />}
      {testing && <TestCameraDialog camera={testing} onClose={() => setTesting(null)} />}
    </div>
  );
}

function CameraCard({
  camera,
  device,
  health,
  onEdit,
  onPhone,
  onTest,
  onZones,
  onRemove,
}: {
  camera: CameraView;
  /** This camera's device in the devices poll (state, last_seen); null until it answers. */
  device: DeviceView | null;
  /** This camera's device in the metrics poll; null when it reports nothing. */
  health: Metrics | null;
  onEdit: () => void;
  /** Cloud cameras only: show the QR that opens the phone-as-camera page. */
  onPhone?: () => void;
  /** IP cameras, when the server can test: the box opens it once and sends a still. */
  onTest?: () => void;
  onZones: () => void;
  onRemove: () => void;
}) {
  // The devices poll is fresher than the camera list, which loads once.
  const c = device ? { ...camera, online: device.state === 'online' } : camera;
  const now = useNow(device?.last_seen != null);
  const status = cameraHealth(camera, device, now);
  const state = status.state;
  // The freshness line speaks for a camera the edge says is not streaming (its last frame
  // stopped there); otherwise the device's last_seen is fresher than the edge's report.
  const cameraStopped = camera.stream_state === 'down' || camera.stream_state === 'reconnecting';
  const seen =
    cameraStopped && c.online && camera.last_frame_at !== undefined
      ? camera.last_frame_at
        ? `ultima imagine acum ${sinceRo(now - Date.parse(camera.last_frame_at))}`
        : 'nicio imagine încă'
      : lastSeenRo(c.online, device?.last_seen, now);
  return (
    <li className="card device-card" aria-label={`Camera ${c.name}`}>
      <CameraThumb cameraId={c.id} name={c.name} online={c.online} />
      <div className="side-head">
        <h2 className="h3">{c.name}</h2>
        <div className="rule-tools">
          <span className={`pill ${PILL[state].className}`}>{PILL[state].label}</span>
          <Menu
            label={`Acțiuni pentru camera ${c.name}`}
            items={[
              { label: 'Editează camera', onSelect: onEdit },
              ...(onPhone ? [{ label: 'Folosește telefonul', onSelect: onPhone }] : []),
              { label: 'Editează zonele', onSelect: onZones },
              { label: 'Scoate camera…', danger: true, onSelect: onRemove },
            ]}
          />
        </div>
      </div>
      <p className="device-sub">
        {seen && (
          <>
            <span className={state === 'online' ? undefined : 'device-gone'}>{seen}</span>
            {' · '}
          </>
        )}
        {plural(c.zones?.length ?? 0, 'zonă', 'zone')}
      </p>
      {state !== 'online' && <OfflineChecklist camera={c} health={status} />}
      <div className="row-actions device-card-actions">
        <Link to={zonesPath(c.id)} className="btn">
          Editează zonele
        </Link>
        {onTest && (
          <button type="button" className="btn" onClick={onTest}>
            Testează
          </button>
        )}
      </div>
      <StaffCaptureButton camera={c} />
      {/* For whoever installs or debugs; the owner at the demo only needs the lines above. */}
      <details className="tech device-tech">
        <summary>Detalii tehnice</summary>
        <p className="device-source mono">
          <span className="visually-hidden">Dispozitiv: </span>
          {c.device}
        </p>
        <p className="device-source mono" title="Adresa completă apare la „Editează camera”">
          <span className="visually-hidden">Sursă: </span>
          {maskSource(c.source)}
        </p>
        {state === 'online' && (
          <dl className="device-health">
            <div>
              <dt>FPS</dt>
              <dd className="mono">{health ? health.fps.toFixed(1) : '—'}</dd>
            </div>
            <div>
              <dt>CPU</dt>
              <dd className="mono">{health ? `${Math.round(health.cpu_percent)}%` : '—'}</dd>
            </div>
          </dl>
        )}
      </details>
    </li>
  );
}

const PILL: Record<CameraHealthState, { label: string; className: string }> = {
  online: { label: 'online', className: 'pill-live' },
  reconnecting: { label: 'se reconectează', className: 'pill-warn' },
  // Connected but silent: the sender (laptop script, phone page) stopped, not the device.
  stale: { label: 'fără imagine', className: 'pill-warn' },
  offline: { label: 'offline', className: 'pill-off' },
};

/**
 * What to check, in order, when a camera stops sending. Cloud cameras are fed by the laptop
 * connector or the /telefon page, so the edge-box steps would send people to look for a box
 * that is not there; when only this camera is down (its device still answers), the steps are
 * about the camera. The button asks the API again.
 */
function OfflineChecklist({ camera, health }: { camera: CameraView; health: CameraHealth }) {
  const stale = health.state === 'stale' || health.state === 'reconnecting';
  const api = useApi();
  const toast = useToast();
  const { addCamera } = useLiveData();
  const [checking, setChecking] = useState(false);

  async function retry() {
    setChecking(true);
    try {
      const fresh = (await api.listCameras()).find((x) => x.id === camera.id);
      if (fresh) addCamera(fresh);
      if (fresh?.online) {
        toast({ title: `Camera „${camera.name}” e din nou online` });
      } else {
        toast({
          title: `Camera „${camera.name}” tot nu răspunde`,
          text: 'Mai verifică o dată pașii, apoi încearcă din nou.',
        });
      }
    } catch (e) {
      toast({
        title: 'Nu am putut verifica dispozitivul',
        text: e instanceof Error ? e.message : undefined,
      });
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className={`device-offline${stale ? ' is-stale' : ''}`}>
      <h3 className="device-offline-title">
        {stale ? 'Nu mai vin imagini. Ce verifici:' : 'Ce verifici, în ordine'}
      </h3>
      {isCloudFrames(camera.source) ? (
        <ol>
          <li>Scriptul de pe laptop rulează? Laptopul are internet?</li>
          <li>Pagina „Telefonul ca cameră” e deschisă și ecranul aprins?</li>
        </ol>
      ) : health.cause === 'camera' ? (
        <ol>
          <li>Camera are curent (LED-ul din față)?</li>
          <li>Cablul de rețea al camerei e în priză la ambele capete.</li>
          <li>
            Adresa IP a camerei s-a schimbat? Verific-o în aplicația camerei, apoi la „Editează
            camera”.
          </li>
        </ol>
      ) : (
        <ol>
          <li>Dispozitivul AiVee din local e pornit? Lumina de pe carcasă e aprinsă.</li>
          <li>Cablul de rețea e în priză la ambele capete.</li>
          <li>Camera are curent (LED-ul din față).</li>
        </ol>
      )}
      <p className="muted small">
        {stale
          ? 'Cardul revine singur la „online” când sosesc imagini.'
          : 'Alertele de la această cameră nu vin până revine.'}
      </p>
      {!stale && (
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => void retry()}
          disabled={checking}
        >
          <BusyLabel busy={checking} idle="Am verificat, încearcă din nou">
            Se verifică…
          </BusyLabel>
        </button>
      )}
    </div>
  );
}

/** Alert latency and verified frames: one quiet line under the cards for whoever looks. */
function SystemLine({ metrics }: { metrics: DashboardMetrics }) {
  const ratios = metrics.devices.map((d) => d.verified_ratio);
  const verified = (ratios.reduce((a, b) => a + b, 0) / ratios.length) * 100;
  return (
    <p className="device-system">
      {metrics.alert_latency_ms != null && (
        <>
          Latență alertă{' '}
          {/* The unit stays out of the monospace span: its wide space read as "0.9  s". */}
          <span className="mono">{(metrics.alert_latency_ms / 1000).toFixed(1)}</span> s{' · '}
        </>
      )}
      cadre verificate <span className="mono">{verified.toFixed(1)}%</span> (trimise modelului greu;
      restul trec doar prin detecția rapidă)
    </p>
  );
}

/** A QR for the presenter's phone: it opens /telefon on this camera, already chosen. */
function PhoneQr({ camera, onClose }: { camera: CameraView; onClose: () => void }) {
  const url = `${window.location.origin}/telefon?camera=${encodeURIComponent(camera.id)}`;
  return (
    <Dialog title={`Folosește telefonul pentru „${camera.name}”`} icon="devices" onClose={onClose}>
      <figure className="phone-qr">
        <QrCode value={url} label={`Cod QR pentru camera ${camera.name} pe telefon`} size={200} />
        <figcaption className="small muted">
          Scanează cu telefonul, intră în cont (proprietar sau manager) și apasă „Pornește camera”.
          <br />
          <a className="mono" href={url}>
            {url}
          </a>
        </figcaption>
      </figure>
    </Dialog>
  );
}

/**
 * Name and source. A source with a password is edited as IP, user and a new password (empty
 * keeps the stored one), so the stored password is never shown; a phone camera's source is not
 * editable; any other source (no secret in it) stays one field.
 */
function EditCamera({ camera, onClose }: { camera: CameraView; onClose: () => void }) {
  const api = useApi();
  const toast = useToast();
  const { addCamera } = useLiveData();
  const parts = parseSourceUrl(camera.source);
  const mode: 'credentials' | 'raw' | 'none' = isCloudCamera(camera)
    ? 'none'
    : parts?.password
      ? 'credentials'
      : 'raw';
  const [name, setName] = useState(camera.name);
  const [source, setSource] = useState(mode === 'raw' ? camera.source : '');
  const [host, setHost] = useState(parts?.host ?? '');
  const [user, setUser] = useState(parts?.user ?? '');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    const n = name.trim();
    if (!n) return setError('Camera are nevoie de un nume.');
    let src = camera.source;
    if (mode === 'raw') src = source.trim();
    if (mode === 'credentials') {
      const bad = checkHost(host);
      if (bad) return setError(bad);
      src = replaceCredentials(camera.source, { host, user, password });
    }
    if (!src) return setError('Scrie adresa RTSP din aplicația camerei.');
    const patch: CameraPatch = {};
    if (n !== camera.name) patch.name = n;
    if (src !== camera.source) patch.source = src;
    if (!patch.name && !patch.source) return onClose();
    setBusy(true);
    try {
      addCamera(await api.updateCamera(camera.id, patch));
      toast({
        title: patch.name ? `Camera se numește acum „${n}”` : `Camera „${n}” a fost salvată`,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut salva camera.');
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={`Editezi „${camera.name}”`}
      icon="edit"
      onClose={() => !busy && onClose()}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Renunță
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={busy}
          >
            Salvează
          </button>
        </>
      }
    >
      <div className="stack-form">
        <label className="field">
          <span>Nume</span>
          <input
            className="input"
            value={name}
            data-autofocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void save();
            }}
          />
        </label>
        {mode === 'raw' && (
          <label className="field">
            <span>Adresa sursei</span>
            <input
              className="input mono"
              value={source}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void save();
              }}
            />
          </label>
        )}
        {mode === 'credentials' && (
          <>
            <label className="field">
              <span>Adresa IP</span>
              <input
                className="input mono"
                value={host}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setHost(e.target.value)}
              />
            </label>
            <div className="field-pair">
              <label className="field">
                <span>Utilizator</span>
                <input
                  className="input"
                  value={user}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => setUser(e.target.value)}
                />
              </label>
              <PasswordInput
                label="Parolă nouă"
                value={password}
                autoComplete="new-password"
                placeholder="neschimbată"
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <p className="muted small">
              Lasă parola goală ca să rămână cea salvată. Adresa:{' '}
              <span className="mono">
                {maskPassword(replaceCredentials(camera.source, { host, user, password }))}
              </span>
            </p>
          </>
        )}
        {error && (
          <small className="field-error" role="alert">
            {error}
          </small>
        )}
      </div>
    </Dialog>
  );
}
