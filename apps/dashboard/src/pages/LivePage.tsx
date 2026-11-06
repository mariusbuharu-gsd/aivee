import { Link } from 'react-router';
import { AlertFeed } from '../components/AlertFeed';
import { CameraTile } from '../components/CameraTile';
import { MetricsStrip } from '../components/MetricsStrip';
import { RuleComposer } from '../components/RuleComposer';
import { SuggestionCard } from '../components/SuggestionCard';
import { useLiveData, zoneName } from '../state/context';

export function LivePage() {
  const { cameras, alerts, suggestions, metrics, loading, addRule, dropSuggestion } = useLiveData();
  const firstOnline = cameras.find((c) => c.online) ?? cameras[0];
  return (
    <div className="page page-live">
      <header className="page-head">
        <h1>Live</h1>
      </header>
      {firstOnline && <RuleComposer cameraId={firstOnline.id} onCreated={addRule} compact />}
      <MetricsStrip metrics={metrics} />
      <div className="live-grid">
        <section aria-label="Camere" className="cameras">
          {loading && cameras.length === 0 && <p className="muted">Se încarcă camerele…</p>}
          {cameras.map((c) => (
            <CameraTile key={c.id} camera={c} />
          ))}
        </section>
        <aside className="side-col" aria-labelledby="recent-h">
          <div className="side-head">
            <h2 id="recent-h">Alerte recente</h2>
            <Link to="/alerte" className="link">
              Toate
            </Link>
          </div>
          {suggestions.slice(0, 1).map((s) => (
            <SuggestionCard
              key={s.suggestion_id}
              suggestion={s}
              cameraName={cameras.find((c) => c.id === s.camera_id)?.name}
              onResolved={dropSuggestion}
            />
          ))}
          <AlertFeed items={alerts.slice(0, 8)} zoneName={(id) => zoneName(cameras, id)} />
        </aside>
      </div>
    </div>
  );
}
