import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { RuleDraft } from '../api/client';
import { useApi } from '../api/context';
import type { Condition, Rule } from '../contracts';
import { describeRule } from '../rules/describe';
import { Banner } from '../ui/Banner';
import { useToast } from '../ui/toast';
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
  camera,
  examples = [],
  startHere = false,
}: {
  cameraId: string;
  onCreated?: (rule: Rule) => void;
  compact?: boolean;
  /** The camera picker, shown inside the composer so it is clear what it applies to. */
  camera?: ReactNode;
  /** Example requests; picking one fills the text (nothing is translated or saved yet). */
  examples?: string[];
  /** The camera has no rules yet: show the examples as a "start here" list, not as chips. */
  startHere?: boolean;
}) {
  const api = useApi();
  const toast = useToast();
  const inputId = useId();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [editing, setEditing] = useState(false);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
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
      toast({
        title: `Regula „${created.name}” a fost salvată și pornită`,
        text: 'Dispozitivul o folosește de acum.',
      });
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

  function pickExample(example: string) {
    setText(example);
    setDraft(null);
    setEditing(false);
    setError(null);
    inputRef.current?.focus();
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
        <div className="composer-top">
          <label htmlFor={inputId} className="composer-label">
            Spune-i camerei ce să vadă
          </label>
          {camera}
        </div>
        <div className="composer-row">
          <input
            id={inputId}
            ref={inputRef}
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
      {examples.length > 0 && !startHere && (
        <div className="chips composer-examples" role="group" aria-labelledby={`${inputId}-ex`}>
          <span id={`${inputId}-ex`} className="small muted">
            Exemple
          </span>
          {examples.map((ex) => (
            <button
              key={ex}
              type="button"
              className="chip chip-tap"
              onClick={() => pickExample(ex)}
            >
              {ex}
            </button>
          ))}
        </div>
      )}
      {examples.length > 0 && startHere && (
        <div className="rule-starters" role="group" aria-labelledby={`${inputId}-start`}>
          <p id={`${inputId}-start`} className="small muted">
            Camera nu are încă nicio regulă. Pornește de la un exemplu și adaptează-l:
          </p>
          <ul>
            {examples.map((ex) => (
              <li key={ex}>
                <button type="button" className="rule-starter" onClick={() => pickExample(ex)}>
                  <Icon name="rules" />
                  <span>{ex}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && <Banner tone="error" title={error} />}
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
          <details className="tech">
            <summary>Detalii tehnice</summary>
            <pre className="mono json">{JSON.stringify(draft.rule, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}

/** Small editor for the parts of a draft a manager is likely to correct. */
export function RuleDraftEditor({
  rule,
  onChange,
}: {
  rule: Rule;
  onChange: (rule: Rule) => void;
}) {
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
