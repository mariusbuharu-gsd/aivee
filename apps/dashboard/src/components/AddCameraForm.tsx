import { useState, type FormEvent } from 'react';
import type { CameraView } from '../api/client';
import { useApi } from '../api/context';

/** The edge's CAMERA_ID default: the id here must match it or the edge ignores the config. */
export const DEFAULT_CAMERA_ID = 'cam-01';
export const DEFAULT_DEVICE = 'edge-01';
const ID_PATTERN = '[A-Za-z0-9_\\-]{1,64}';

export function AddCameraForm({
  onCreated,
  defaultId = DEFAULT_CAMERA_ID,
}: {
  onCreated?: (camera: CameraView) => void;
  defaultId?: string;
}) {
  const api = useApi();
  const [id, setId] = useState(defaultId);
  const [name, setName] = useState('');
  const [source, setSource] = useState('');
  const [device, setDevice] = useState(DEFAULT_DEVICE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
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

  return (
    <form className="card add-camera" onSubmit={submit} aria-labelledby="add-camera-h">
      <h2 id="add-camera-h" className="h3">
        Adaugă cameră
      </h2>
      <label className="field">
        <span>Nume</span>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="ex. Sala principală"
          required
        />
      </label>
      <label className="field">
        <span>Adresa sursei (RTSP/HTTP sau index)</span>
        <input
          className="input mono"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="rtsp://192.168.1.20:554/stream1"
          required
        />
      </label>
      <div className="field-pair">
        <label className="field">
          <span>Id cameră</span>
          <input
            className="input mono"
            value={id}
            onChange={(e) => setId(e.target.value)}
            pattern={ID_PATTERN}
            title="Litere, cifre, - și _ (max. 64)"
            required
          />
        </label>
        <label className="field">
          <span>Dispozitiv</span>
          <input
            className="input mono"
            value={device}
            onChange={(e) => setDevice(e.target.value)}
            pattern={ID_PATTERN}
            required
          />
        </label>
      </div>
      <p className="muted small">
        Id-ul trebuie să fie același cu CAMERA_ID de pe dispozitiv (implicit {DEFAULT_CAMERA_ID}).
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="btn btn-primary" type="submit" disabled={busy}>
        {busy ? 'Se adaugă…' : 'Adaugă camera'}
      </button>
    </form>
  );
}
