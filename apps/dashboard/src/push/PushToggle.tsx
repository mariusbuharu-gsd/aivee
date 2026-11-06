import { useEffect, useMemo, useState } from 'react';
import { browserPushService, PushError, type PushService, type PushState } from './service';
import './push.css';

const STATUS: Record<PushState, { pill: string; label: string; text: string }> = {
  unsupported: {
    pill: 'pill-muted',
    label: 'indisponibil',
    text: 'Browserul acesta nu primește notificări. Pe Android deschide AiVee în Chrome (prin HTTPS), pe iPhone adaug-o pe ecranul principal.',
  },
  unavailable: {
    pill: 'pill-muted',
    label: 'indisponibil',
    text: 'Serverul nu trimite încă notificări push. Alertele ajung pe Telegram.',
  },
  denied: {
    pill: 'pill-off',
    label: 'blocate',
    text: 'Ai blocat notificările pentru AiVee. Le permiți din setările site-ului în browser, apoi revii aici.',
  },
  off: {
    pill: 'pill-muted',
    label: 'oprite',
    text: 'Primești pe acest telefon fiecare alertă nouă, chiar cu aplicația închisă.',
  },
  on: {
    pill: 'pill-live',
    label: 'active',
    text: 'Primești alertele pe acest dispozitiv. Atingi notificarea și ajungi la Alerte.',
  },
};

/** "Activează notificările" card for the Alerte page. */
export function PushToggle({ service }: { service?: PushService }) {
  const push = useMemo(() => service ?? browserPushService(), [service]);
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    push.state().then(
      (s) => alive && setState(s),
      (e: unknown) => {
        if (!alive) return;
        setState(push.supported ? 'off' : 'unsupported');
        setError(e instanceof Error ? e.message : String(e));
      },
    );
    return () => {
      alive = false;
    };
  }, [push]);

  const run = async (action: () => Promise<PushState | string>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const out = await action();
      if (out in STATUS) setState(out as PushState);
      else setMessage(out);
    } catch (e) {
      setError(e instanceof PushError || e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    const r = await push.sendTest();
    return r.sent > 0
      ? `Am trimis un test pe ${r.sent} ${r.sent === 1 ? 'dispozitiv' : 'dispozitive'}.`
      : 'Niciun dispozitiv abonat nu a primit testul.';
  };

  const status = state ? STATUS[state] : null;
  const on = state === 'on';
  const canToggle = state === 'on' || state === 'off';

  return (
    <section className="card push-card" aria-labelledby="push-h">
      <div className="push-head">
        <h3 id="push-h">Notificări pe telefon</h3>
        {status && <span className={`pill ${status.pill}`}>{status.label}</span>}
      </div>
      <p className="muted small" aria-live="polite">
        {status ? status.text : 'Verific dacă browserul primește notificări…'}
      </p>
      {canToggle && (
        <div className="actions">
          <button
            type="button"
            role="switch"
            aria-checked={on}
            className={on ? 'btn' : 'btn btn-primary'}
            disabled={busy}
            onClick={() => run(() => (on ? push.disable() : push.enable()))}
          >
            {on ? 'Oprește notificările' : 'Activează notificările'}
          </button>
          {on && (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => run(test)}
            >
              Trimite un test
            </button>
          )}
        </div>
      )}
      {message && (
        <p className="small" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
