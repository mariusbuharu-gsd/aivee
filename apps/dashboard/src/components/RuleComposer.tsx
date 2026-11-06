import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import type { RuleDraft } from '../api/client';
import { useApi } from '../api/context';
import type { Condition, Rule } from '../contracts';
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
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState<Rule | null>(null);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const Speech = typeof window === 'undefined' ? null : speechCtor();

  useEffect(() => () => recRef.current?.stop(), []);

  const message = (err: unknown, fallback: string) =>
    err instanceof Error && err.message ? err.message : fallback;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    setEditing(false);
    try {
      setDraft(await api.draftRuleFromText(value, cameraId));
    } catch (err) {
      setDraft(null);
      setError(message(err, 'Nu am putut înțelege cererea'));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!draft || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createRule(draft.rule);
      setSaved(created);
      setDraft(null);
      setEditing(false);
      setText('');
      onCreated?.(created);
    } catch (err) {
      setError(message(err, 'Nu am putut salva regula'));
    } finally {
      setBusy(false);
    }
  }

  function discard() {
    setDraft(null);
    setEditing(false);
    setError(null);
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
            {busy && !draft ? 'Se analizează…' : 'Creează regula'}
          </button>
        </div>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {draft && (
        <div className="understood" role="region" aria-label="Ce am înțeles">
          <h3 className="understood-title">Ce am înțeles</h3>
          <p className="understood-name">
            <strong>{draft.rule.name}</strong> <span className="pill pill-muted">ciornă</span>
          </p>
          {draft.explanation_ro && <p data-testid="rule-explanation">{draft.explanation_ro}</p>}
          <p className="muted small" data-testid="rule-summary">
            {describeRule(draft.rule)}
          </p>
          {editing && (
            <RuleDraftEditor rule={draft.rule} onChange={(rule) => setDraft({ ...draft, rule })} />
          )}
          <div className="actions">
            <button className="btn btn-primary" onClick={confirm} disabled={busy}>
              <Icon name="check" /> {busy ? 'Se salvează…' : 'Confirmă și salvează'}
            </button>
            <button
              className="btn"
              onClick={() => setEditing((v) => !v)}
              aria-pressed={editing}
              disabled={busy}
            >
              <Icon name="edit" /> {editing ? 'Gata cu modificările' : 'Modifică'}
            </button>
            <button className="btn btn-ghost" onClick={discard} disabled={busy}>
              Renunță
            </button>
          </div>
          <details>
            <summary>Vezi regula JSON</summary>
            <pre className="mono json">{JSON.stringify(draft.rule, null, 2)}</pre>
          </details>
        </div>
      )}
      {saved && !draft && (
        <p className="small" role="status" aria-live="polite">
          <Icon name="check" /> Regula „{saved.name}” a fost salvată și trimisă dispozitivului.
        </p>
      )}
    </section>
  );
}

/** Small editor for the parts of a draft a manager is likely to correct. */
function RuleDraftEditor({ rule, onChange }: { rule: Rule; onChange: (rule: Rule) => void }) {
  const setCondition = (i: number, patch: Partial<Condition>) => {
    const all_of = rule.all_of.map((c, j) => (j === i ? { ...c, ...patch } : c)) as Rule['all_of'];
    onChange({ ...rule, all_of });
  };
  const seconds = (v: string) => Math.max(0, Math.round(Number(v) || 0));
  return (
    <fieldset className="draft-editor">
      <legend className="visually-hidden">Modifică regula</legend>
      <label className="field">
        <span>Nume</span>
        <input
          className="input"
          value={rule.name}
          onChange={(e) => onChange({ ...rule, name: e.target.value })}
          required
        />
      </label>
      {rule.all_of.map((c, i) =>
        c.min_duration_s === undefined ? null : (
          <label className="field" key={i}>
            <span>Durată condiția {i + 1} (secunde)</span>
            <input
              className="input"
              type="number"
              min={0}
              step={10}
              value={c.min_duration_s}
              onChange={(e) => setCondition(i, { min_duration_s: seconds(e.target.value) })}
            />
          </label>
        ),
      )}
      <label className="field">
        <span>Pauză între alerte (secunde)</span>
        <input
          className="input"
          type="number"
          min={0}
          step={30}
          value={rule.cooldown_s ?? 300}
          onChange={(e) => onChange({ ...rule, cooldown_s: seconds(e.target.value) })}
        />
      </label>
    </fieldset>
  );
}
