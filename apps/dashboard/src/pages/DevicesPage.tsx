import { Link } from 'react-router';
import { useLiveData } from '../state/context';

export function DevicesPage() {
  const { cameras } = useLiveData();
  return (
    <div className="page">
      <header className="page-head">
        <h1>Dispozitive</h1>
      </header>
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
