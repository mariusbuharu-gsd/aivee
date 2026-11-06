import { useState } from 'react';
import { useApi } from '../api/context';
import type { SuggestionView } from '../api/client';
import { Banner } from '../ui/Banner';
import { useToast } from '../ui/toast';
import { Icon } from './Icon';
import './SuggestionCard.css';

export function SuggestionCard({
  suggestion,
  cameraName,
  onResolved,
  variant = 'card',
}: {
  suggestion: SuggestionView;
  cameraName?: string;
  onResolved?: (id: string, decision: 'confirmed' | 'rejected') => void;
  /** `card` (default, Live): night card with the score. `question`: one Da/Nu line (Alerte). */
  variant?: 'card' | 'question';
}) {
  const api = useApi();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headingId = `sug-${suggestion.suggestion_id}`;
  // The edge's face-blurred crop; without one (older API, failed load) a blurred stand-in.
  const [failed, setFailed] = useState<string | null>(null);
  const url = suggestion.snapshot_url;
  const photo = url && failed !== url ? url : null;
  const n = suggestion.track_id;
  const img = photo && (
    <img
      className="suggestion-photo"
      src={photo}
      alt={`Persoana #${n}, fața estompată`}
      decoding="async"
      onError={() => setFailed(photo)}
    />
  );

  async function decide(decision: 'confirmed' | 'rejected') {
    setBusy(true);
    setError(null);
    try {
      if (decision === 'confirmed') await api.confirmSuggestion(suggestion.suggestion_id);
      else await api.rejectSuggestion(suggestion.suggestion_id);
      onResolved?.(suggestion.suggestion_id, decision);
      toast({
        title:
          decision === 'confirmed'
            ? `#${suggestion.track_id} e din personal`
            : `#${suggestion.track_id} nu e din personal`,
        text:
          decision === 'confirmed'
            ? 'De acum o numără ca personal, nu ca client.'
            : 'O numără în continuare drept client.',
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut trimite răspunsul');
      setBusy(false);
    }
  }

  if (variant === 'question') {
    return (
      <article className="suggestion-q" aria-labelledby={headingId}>
        {img ? (
          <div className="suggestion-q-crop has-photo">
            {img}
            <span className="mono" aria-hidden="true">
              #{n}
            </span>
          </div>
        ) : (
          <div className="suggestion-q-crop" role="img" aria-label={`Persoana #${n}, estompată`}>
            <span className="mono">#{n}</span>
          </div>
        )}
        <div className="suggestion-q-body">
          <h3 id={headingId}>#{suggestion.track_id} pare să fie din personal?</h3>
          <p className="muted small">
            {suggestion.reason_ro}
            {cameraName ? ` · ${cameraName}` : ''}
          </p>
          {error && <Banner tone="error" title={error} />}
        </div>
        <div className="suggestion-q-actions">
          <button
            className="btn btn-primary"
            disabled={busy}
            aria-label={`Da, #${suggestion.track_id} e din personal`}
            onClick={() => decide('confirmed')}
          >
            Da
          </button>
          <button
            className="btn"
            disabled={busy}
            aria-label={`Nu, #${suggestion.track_id} e client`}
            onClick={() => decide('rejected')}
          >
            Nu
          </button>
        </div>
      </article>
    );
  }

  return (
    <article className="suggestion" aria-labelledby={headingId}>
      {img ? (
        <div className="suggestion-crop has-photo">
          {img}
          <span className="mono" aria-hidden="true">
            #{n}
          </span>
        </div>
      ) : (
        <div className="suggestion-crop" role="img" aria-label={`Persoana #${n}`}>
          <span className="mono">#{n}</span>
        </div>
      )}
      <div className="suggestion-body">
        <h3 id={headingId}>Pare angajat — confirmi?</h3>
        <p>{suggestion.reason_ro}</p>
        <p className="muted small mono">
          scor {Math.round(suggestion.staff_score * 100)}%{cameraName ? ` · ${cameraName}` : ''}
        </p>
        {error && <Banner tone="error" title={error} />}
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
