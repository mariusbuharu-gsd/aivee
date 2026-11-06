import { Link, useNavigate } from 'react-router';
import { AddCameraForm, DEFAULT_CAMERA_ID } from '../components/AddCameraForm';
import { useLiveData } from '../state/context';

export function DevicesPage() {
  const { cameras, loading, addCamera } = useLiveData();
  const navigate = useNavigate();
  // Prefill the edge default only while it is free; otherwise suggest the next id.
  const taken = new Set(cameras.map((c) => c.id));
  let next = DEFAULT_CAMERA_ID;
  for (let n = 2; taken.has(next); n++) next = `cam-${String(n).padStart(2, '0')}`;
  return (
    <div className="page">
      <header className="page-head">
        <h1>Dispozitive</h1>
      </header>
      {!loading && cameras.length === 0 && (
        <p className="muted">Nicio cameră încă. Adaug-o pe prima, apoi desenează mesele.</p>
      )}
      <AddCameraForm
        key={next}
        defaultId={next}
        onCreated={(c) => {
          addCamera(c);
          navigate(`/camere/${encodeURIComponent(c.id)}/zone`);
        }}
      />
      <ul className="cards">
        {cameras.map((c) => (
          <li key={c.id} className="card">
            <div className="side-head">
              <h2 className="h3">{c.name}</h2>
              <span className={`pill ${c.online ? 'pill-live' : 'pill-off'}`}>
                {c.online ? 'online' : 'offline'}
              </span>
            </div>
            <dl className="kv">
              <dt>Dispozitiv</dt>
              <dd className="mono">{c.device}</dd>
              <dt>Sursă</dt>
              <dd className="mono">{c.source}</dd>
              <dt>Zone</dt>
              <dd>{(c.zones ?? []).map((z) => z.name).join(', ') || '—'}</dd>
            </dl>
            <Link to={`/camere/${encodeURIComponent(c.id)}/zone`} className="btn">
              Editează zonele
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
