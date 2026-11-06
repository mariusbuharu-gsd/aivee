import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { RuleDraft } from '../api/client';
import { useApi } from '../api/context';
import type { Condition, Rule } from '../contracts';
import {
  ANYWHERE,
  ANYWHERE_LABEL,
  type ChipKey,
  type Phrase,
  type RuleChip,
  isOpenKind,
  ruleChips,
  rulePhrases,
} from '../rules/chips';
import { describeRule, ZONE_TAGS } from '../rules/describe';
import { RuleReader } from '../rules/RuleReader';
import { Select } from '../ui/Select';
import { Banner } from '../ui/Banner';
import { useToast } from '../ui/toast';
import { Icon } from './Icon';
import './RuleComposer.css';

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
  camera,
  examples = [],
  startHere = false,
}: {
  cameraId: string;
  onCreated?: (rule: Rule) => void;
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
  const editorId = useId();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [empty, setEmpty] = useState(false);
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  /** The sentence the draft was made from, with the phrases the eyes read in it. */
  const [read, setRead] = useState<{ text: string; phrases: Phrase[] } | null>(null);
  const [field, setField] = useState<ChipKey | null>(null);
  const [editing, setEditing] = useState(false);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  const focusInput = useRef(false);
  const Speech = typeof window === 'undefined' ? null : speechCtor();

  useEffect(() => () => recRef.current?.stop(), []);
  // Move focus only when the view switches (text field <-> draft), not on every draft edit.
  const hasDraft = draft !== null;
  useEffect(() => {
    if (hasDraft) titleRef.current?.focus();
    else if (focusInput.current) {
      focusInput.current = false;
      inputRef.current?.focus();
    }
  }, [hasDraft]);

  const message = (err: unknown, fallback: string) =>
    err instanceof Error && err.message ? err.message : fallback;

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const value = text.trim();
    if (busy) return;
    if (!value) {
      setEmpty(true);
      inputRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    setEditing(false);
    setField(null);
    try {
      const next = await api.draftRuleFromText(value, cameraId);
      setRead({ text: value, phrases: rulePhrases(value, next.rule) });
      setDraft(next);
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
      setField(null);
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
    setEmpty(false);
    setDraft(null);
    setEditing(false);
    setError(null);
    inputRef.current?.focus();
  }

  function backToText() {
    focusInput.current = true;
    setDraft(null);
    setEditing(false);
    setField(null);
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
      setEmpty(false);
      setText((t) => (t ? `${t} ${transcript}` : transcript).trim());
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  }

  const hintId = `${inputId}-hint`;
  const chips = draft ? ruleChips(draft.rule) : [];
  const openChip = chips.find((c) => c.key === field);

  return (
    <section className="composer" aria-label="Regulă nouă">
      {!draft && (
        <form className="composer-bar" onSubmit={submit} noValidate>
          <div className="composer-top">
            <label htmlFor={inputId} className="composer-label">
              Spune-i camerei ce să vadă
            </label>
            {camera}
          </div>
          <div className={`composer-field ${empty ? 'is-invalid' : ''}`}>
            <textarea
              id={inputId}
              ref={inputRef}
              className="composer-input"
              rows={3}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                if (e.target.value.trim()) setEmpty(false);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void submit();
                }
              }}
              placeholder="ex. Dacă la o masă stă un client și nu vine nimeni 2 minute, anunță ospătarul"
              autoComplete="off"
              aria-invalid={empty || undefined}
              aria-describedby={hintId}
            />
            <button
              type="button"
              className={`btn btn-icon composer-mic ${listening ? 'btn-recording' : ''}`}
              onClick={toggleMic}
              disabled={!Speech}
              aria-pressed={listening}
              aria-label={listening ? 'Oprește dictarea' : 'Dictează regula'}
              title={Speech ? undefined : 'Dictarea nu e disponibilă în acest browser'}
            >
              <Icon name="mic" />
            </button>
          </div>
          <div className="composer-foot">
            <p
              id={hintId}
              className={`small ${empty ? 'composer-hint' : 'muted'}`}
              aria-live="polite"
            >
              {empty
                ? 'Scrie mai întâi ce să urmărească camera, sau pornește de la un exemplu.'
                : 'Scrie cum i-ai spune unui coleg. Enter trimite, Shift+Enter trece pe rândul următor.'}
            </p>
            <button
              type="submit"
              className="btn btn-accent composer-go"
              aria-busy={busy || undefined}
            >
              {busy ? 'Se analizează…' : 'Creează regula'}
            </button>
          </div>
        </form>
      )}
      {!draft && examples.length > 0 && !startHere && (
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
      {!draft && examples.length > 0 && startHere && (
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
      {draft && read && (
        <div className="understood" role="region" aria-label="Ce am înțeles">
          <div className="composer-top">
            <h3 className="understood-title" ref={titleRef} tabIndex={-1}>
              Ce am înțeles
            </h3>
            <p className="understood-name">
              <strong>{draft.rule.name}</strong> <span className="pill pill-muted">ciornă</span>
            </p>
          </div>
          <RuleReader
            key={draft.rule.id}
            text={read.text}
            phrases={read.phrases}
            chips={chips}
            open={field}
            editorId={editorId}
            onPick={(key) => setField((f) => (f === key ? null : key))}
          />
          {openChip && (
            <ChipEditor
              id={editorId}
              chip={openChip}
              rule={draft.rule}
              onChange={(rule) => setDraft({ ...draft, rule })}
              onDone={() => setField(null)}
            />
          )}
          {draft.explanation_ro && <p data-testid="rule-explanation">{draft.explanation_ro}</p>}
          <p className="muted small" data-testid="rule-summary">
            {describeRule(draft.rule)}
          </p>
          {editing && (
            <RuleDraftEditor rule={draft.rule} onChange={(rule) => setDraft({ ...draft, rule })} />
          )}
          <div className="composer-foot">
            <p className="small muted">
              Așa a înțeles AiVee. Corectezi orice bucată cu un click; nimic nu e salvat încă.
            </p>
            <div className="actions">
              <button className="btn btn-ghost" onClick={backToText} disabled={busy}>
                Schimbă textul
              </button>
              <button
                className="btn"
                onClick={() => setEditing((v) => !v)}
                aria-pressed={editing}
                disabled={busy}
              >
                <Icon name="edit" /> {editing ? 'Gata cu modificările' : 'Modifică'}
              </button>
              <button className="btn btn-accent" onClick={confirm} disabled={busy}>
                <Icon name="check" /> {busy ? 'Se salvează…' : 'Pornește regula'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

const minutes = (s: number | undefined) => Math.round(((s ?? 0) / 60) * 100) / 100;
const fromMinutes = (v: string) => Math.max(0, Math.round((Number(v) || 0) * 60));

/** Opens only the values behind one chip, so a correction does not need the whole editor. */
function ChipEditor({
  id,
  chip,
  rule,
  onChange,
  onDone,
}: {
  id: string;
  chip: RuleChip;
  rule: Rule;
  onChange: (rule: Rule) => void;
  onDone: () => void;
}) {
  const setCondition = (i: number, patch: Partial<Condition>) => {
    const all_of = rule.all_of.map((c, j) => (j === i ? { ...c, ...patch } : c)) as Rule['all_of'];
    onChange({ ...rule, all_of });
  };
  const many = chip.fields.filter((f) => f.kind === 'duration').length > 1;
  // Open rules ("dacă e foc") may watch the whole image; their times are a few seconds.
  const open = rule.all_of.every((c) => isOpenKind(c.kind));
  const zoneOptions = [
    ...(open || rule.zone_tag === ANYWHERE ? [{ value: ANYWHERE, label: ANYWHERE_LABEL }] : []),
    ...ZONE_TAGS.map((t) => ({ value: t.value, label: t.label })),
  ];
  return (
    <fieldset className="chip-editor" id={id}>
      <legend>Corectezi: {chip.label}</legend>
      {chip.fields.length === 0 && (
        <p className="small muted">
          Aici nu e nimic de ajustat. Dacă vrei altceva, schimbă textul și creează regula din nou.
        </p>
      )}
      {chip.fields.map((f, n) => {
        const autoFocus = n === 0;
        switch (f.kind) {
          case 'zone':
            return (
              <Select
                key="zone"
                label="Zona"
                value={rule.zone_tag}
                options={zoneOptions}
                onChange={(zone_tag) => onChange({ ...rule, zone_tag })}
              />
            );
          case 'duration': {
            const c = rule.all_of[f.index];
            const inSeconds = c !== undefined && isOpenKind(c.kind);
            return (
              <label className="field" key={`d${f.index}`}>
                <span>
                  {many ? `Cât timp, condiția ${f.index + 1}` : 'Cât timp'} (
                  {inSeconds ? 'secunde' : 'minute'})
                </span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={inSeconds ? 1 : 0.5}
                  autoFocus={autoFocus}
                  value={inSeconds ? (c.min_duration_s ?? 0) : minutes(c?.min_duration_s)}
                  onChange={(e) =>
                    setCondition(f.index, {
                      min_duration_s: inSeconds
                        ? Math.max(0, Math.round(Number(e.target.value) || 0))
                        : fromMinutes(e.target.value),
                    })
                  }
                />
              </label>
            );
          }
          case 'count':
            return (
              <label className="field" key={`c${f.index}`}>
                <span>Câte persoane, cel puțin</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  step={1}
                  autoFocus={autoFocus}
                  value={rule.all_of[f.index]?.min_count ?? 1}
                  onChange={(e) =>
                    setCondition(f.index, {
                      min_count: Math.max(1, Math.round(Number(e.target.value) || 1)),
                    })
                  }
                />
              </label>
            );
          case 'cooldown':
            return (
              <label className="field" key="cooldown">
                <span>Pauză între alerte (minute)</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={1}
                  autoFocus={autoFocus}
                  value={minutes(rule.cooldown_s ?? 300)}
                  onChange={(e) => onChange({ ...rule, cooldown_s: fromMinutes(e.target.value) })}
                />
              </label>
            );
        }
      })}
      <button type="button" className="btn btn-ghost chip-editor-done" onClick={onDone}>
        Gata
      </button>
    </fieldset>
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
