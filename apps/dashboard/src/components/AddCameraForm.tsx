import { useState, type FormEvent } from 'react';
import type { CameraView } from '../api/client';
import { useApi } from '../api/context';
import { Banner } from '../ui/Banner';

/** The edge's CAMERA_ID default: the id here must match it or the edge ignores the config. */
export const DEFAULT_CAMERA_ID = 'cam-01';
export const DEFAULT_DEVICE = 'edge-01';
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function AddCameraForm({
  onCreated,
  defaultId = DEFAULT_CAMERA_ID,
  onCancel,
}: {
  onCreated?: (camera: CameraView) => void;
  defaultId?: string;
  /** Shown as "Renunță" when the form sits in a dialog. */
  onCancel?: () => void;
}) {
  const api = useApi();
  const [id, setId] = useState(defaultId);
  const [name, setName] = useState('');
  const [source, setSource] = useState('');
  const [device, setDevice] = useState(DEFAULT_DEVICE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<
    Partial<Record<'name' | 'source' | 'id' | 'device', string>>
  >({});

  function check() {
    const f: typeof fields = {};
    if (!name.trim()) f.name = 'Dă-i camerei un nume, de exemplu „Sala principală”.';
    if (!source.trim()) f.source = 'Scrie adresa RTSP din aplicația camerei.';
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
        source: source.trim(),
        device: device.trim() || DEFAULT_DEVICE,
      });
      onCreated?.(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut adăuga camera');
    } finally {
      setBusy(false);
    }
  }

  const err = (k: keyof typeof fields) =>
    fields[k] ? { 'aria-invalid': true, 'aria-describedby': `cam-${k}-err` } : {};
  const msg = (k: keyof typeof fields) =>
    fields[k] && (
      <small id={`cam-${k}-err`} className="field-error">
        {fields[k]}
      </small>
    );

  return (
    <form className="stack-form add-camera" onSubmit={submit} noValidate>
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
      <div className="field">
        <label htmlFor="cam-source">Adresa sursei (RTSP/HTTP sau index)</label>
        <input
          id="cam-source"
          className="input mono"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="rtsp://192.168.1.20:554/stream1"
          {...err('source')}
        />
        {msg('source')}
      </div>
      <details className="tech" open={!!(fields.id || fields.device)}>
        <summary>Avansat: id cameră și dispozitiv</summary>
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
          {busy ? 'Se adaugă…' : 'Adaugă camera'}
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
