import { useState } from 'react';
import { useApi } from '../api/context';
import type { StaffSuggestion } from '../contracts';
import { Icon } from './Icon';

export function SuggestionCard({
  suggestion,
  cameraName,
  onResolved,
}: {
  suggestion: StaffSuggestion;
  cameraName?: string;
  onResolved?: (id: string, decision: 'confirmed' | 'rejected') => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headingId = `sug-${suggestion.suggestion_id}`;

  async function decide(decision: 'confirmed' | 'rejected') {
    setBusy(true);
    setError(null);
    try {
      if (decision === 'confirmed') await api.confirmSuggestion(suggestion.suggestion_id);
      else await api.rejectSuggestion(suggestion.suggestion_id);
      onResolved?.(suggestion.suggestion_id, decision);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut trimite răspunsul');
      setBusy(false);
    }
  }

  return (
    <article className="suggestion" aria-labelledby={headingId}>
      <div className="suggestion-crop" role="img" aria-label={`Persoana #${suggestion.track_id}`}>
        <span className="mono">#{suggestion.track_id}</span>
      </div>
      <div className="suggestion-body">
        <h3 id={headingId}>Pare angajat — confirmi?</h3>
        <p>{suggestion.reason_ro}</p>
        <p className="muted small mono">
          scor {Math.round(suggestion.staff_score * 100)}%{cameraName ? ` · ${cameraName}` : ''}
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => decide('confirmed')}>
            <Icon name="check" /> Confirmă
          </button>
          <button className="btn" disabled={busy} onClick={() => decide('rejected')}>
            <Icon name="x" /> Respinge
          </button>
        </div>
      </div>
    </article>
  );
}
