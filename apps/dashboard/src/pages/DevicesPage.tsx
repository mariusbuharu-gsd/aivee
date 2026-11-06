import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import type { CameraView } from '../api/client';
import { useApi } from '../api/context';
import { AddCameraForm, DEFAULT_CAMERA_ID } from '../components/AddCameraForm';
import { Icon } from '../components/Icon';
import { MetricsStrip } from '../components/MetricsStrip';
import { useLiveData } from '../state/context';
import { Banner } from '../ui/Banner';
import { Dialog } from '../ui/Dialog';
import { Menu } from '../ui/Menu';
import { EmptyState, Skeleton } from '../ui/controls';
import { useToast } from '../ui/toast';

const zonesPath = (id: string) => `/camere/${encodeURIComponent(id)}/zone`;

export function DevicesPage() {
  const { cameras, loading, addCamera, metrics } = useLiveData();
  const navigate = useNavigate();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<CameraView | null>(null);
  // Prefill the edge default only while it is free; otherwise suggest the next id.
  const taken = new Set(cameras.map((c) => c.id));
  let next = DEFAULT_CAMERA_ID;
  for (let n = 2; taken.has(next); n++) next = `cam-${String(n).padStart(2, '0')}`;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Dispozitive</h1>
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
          <li key={c.id} className="card">
            <div className="side-head">
              <h2 className="h3">{c.name}</h2>
              <div className="rule-tools">
                <span className={`pill ${c.online ? 'pill-live' : 'pill-off'}`}>
                  {c.online ? 'online' : 'offline'}
                </span>
                <Menu
                  label={`Acțiuni pentru camera ${c.name}`}
                  items={[
                    { label: 'Redenumește', onSelect: () => setRenaming(c) },
                    { label: 'Editează zonele', onSelect: () => navigate(zonesPath(c.id)) },
                  ]}
                />
              </div>
            </div>
            {!c.online && (
              <Banner tone="warn" title="Dispozitivul nu răspunde.">
                Verifică dacă {c.device} e pornit și legat la rețea. Alertele de la această cameră
                nu vin până revine.
              </Banner>
            )}
            <dl className="kv">
              <dt>Dispozitiv</dt>
              <dd className="mono">{c.device}</dd>
              <dt>Sursă</dt>
              <dd className="mono">{c.source}</dd>
              <dt>Zone</dt>
              <dd>{(c.zones ?? []).map((z) => z.name).join(', ') || '—'}</dd>
            </dl>
            <Link to={zonesPath(c.id)} className="btn">
              Editează zonele
            </Link>
          </li>
        ))}
      </ul>

      {metrics && metrics.devices.length > 0 && (
        <section aria-labelledby="system-h" className="rule-groups">
          <h2 id="system-h">Sistem</h2>
          <MetricsStrip metrics={metrics} />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Dispozitiv</th>
                  <th scope="col">FPS</th>
                  <th scope="col">Cadre verificate</th>
                  <th scope="col">CPU</th>
                </tr>
              </thead>
              <tbody>
                {metrics.devices.map((d) => (
                  <tr key={d.device}>
                    <th scope="row" className="mono">
                      {d.device}
                    </th>
                    <td className="mono">{d.fps.toFixed(1)}</td>
                    <td className="mono">{(d.verified_ratio * 100).toFixed(1)}%</td>
                    <td className="mono">{Math.round(d.cpu_percent)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Cadre verificate = procentul de cadre trimise modelului greu. Restul rulează doar
            detecția rapidă, pe dispozitiv.
          </p>
        </section>
      )}

      {adding && (
        <Dialog title="Adaugă o cameră" icon="devices" onClose={() => setAdding(false)}>
          <AddCameraForm
            key={next}
            defaultId={next}
            onCancel={() => setAdding(false)}
            onCreated={(c) => {
              addCamera(c);
              setAdding(false);
              toast({
                title: `Camera „${c.name}” a fost adăugată`,
                text: 'Desenează acum mesele și intrarea pe imagine.',
              });
              navigate(zonesPath(c.id));
            }}
          />
        </Dialog>
      )}
      {renaming && <RenameCamera camera={renaming} onClose={() => setRenaming(null)} />}
    </div>
  );
}

function RenameCamera({ camera, onClose }: { camera: CameraView; onClose: () => void }) {
  const api = useApi();
  const toast = useToast();
  const { addCamera } = useLiveData();
  const [name, setName] = useState(camera.name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    const v = name.trim();
    if (!v) return setError('Camera are nevoie de un nume.');
    if (v === camera.name) return onClose();
    setBusy(true);
    try {
      addCamera(await api.updateCamera(camera.id, { name: v }));
      toast({ title: `Camera se numește acum „${v}”` });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut redenumi camera.');
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={`Redenumești „${camera.name}”`}
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
      <label className="field">
        <span>Nume nou</span>
        <input
          className="input"
          value={name}
          data-autofocus
          aria-invalid={error ? true : undefined}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void save();
          }}
        />
        {error && <small className="field-error">{error}</small>}
      </label>
    </Dialog>
  );
}
