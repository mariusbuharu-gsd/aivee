import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useApi } from '../api/context';
import type { Rule } from '../contracts';
import { describeRule } from '../rules/describe';
import { Icon } from './Icon';

// Web Speech API is not in lib.dom yet; describe the small part we use.
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type SpeechCtor = new () => SpeechRecognitionLike;

function speechCtor(): SpeechCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function RuleComposer({
  cameraId,
  onCreated,
  compact = false,
}: {
  cameraId: string;
  onCreated?: (rule: Rule) => void;
  compact?: boolean;
}) {
  const api = useApi();
  const inputId = useId();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rule, setRule] = useState<Rule | null>(null);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const Speech = typeof window === 'undefined' ? null : speechCtor();

  useEffect(() => () => recRef.current?.stop(), []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createRuleFromText(value, cameraId);
      setRule(created);
      setText('');
      onCreated?.(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut crea regula');
    } finally {
      setBusy(false);
    }
  }

  function toggleMic() {
    if (!Speech) return;
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = new Speech();
    rec.lang = 'ro-RO';
    rec.interimResults = false;
    rec.onresult = (e) => {
      const transcript = Array.from(e.results)
        .map((r) => r[0]?.transcript ?? '')
        .join(' ');
      setText((t) => (t ? `${t} ${transcript}` : transcript).trim());
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  }

  return (
    <section className={`composer ${compact ? 'composer-compact' : ''}`} aria-label="Regulă nouă">
      <form className="composer-bar" onSubmit={submit}>
        <label htmlFor={inputId} className="composer-label">
          Spune-i camerei ce să vadă
        </label>
        <div className="composer-row">
          <input
            id={inputId}
            className="input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="ex. Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut"
            autoComplete="off"
          />
          <button
            type="button"
            className={`btn btn-icon ${listening ? 'btn-recording' : ''}`}
            onClick={toggleMic}
            disabled={!Speech}
            aria-pressed={listening}
            aria-label={listening ? 'Oprește dictarea' : 'Dictează regula'}
            title={Speech ? undefined : 'Dictarea nu e disponibilă în acest browser'}
          >
            <Icon name="mic" />
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
            {busy ? 'Se creează…' : 'Creează regula'}
          </button>
        </div>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {rule && (
        <div className="understood" role="status" aria-live="polite">
          <h3 className="understood-title">Ce am înțeles</h3>
          <p className="understood-name">
            <strong>{rule.name}</strong>{' '}
            <span className="pill pill-live">{rule.enabled === false ? 'inactivă' : 'activă'}</span>
          </p>
          <p data-testid="rule-summary">{describeRule(rule)}</p>
          <details>
            <summary>Vezi regula JSON</summary>
            <pre className="mono json">{JSON.stringify(rule, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}
