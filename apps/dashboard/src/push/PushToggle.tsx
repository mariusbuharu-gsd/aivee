import { Link } from 'react-router';
import { Banner } from '../ui/Banner';
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

/** No push on this device or server: a fact about the setup, not something to toggle. */
const isUnavailable = (s: PushState | null) => s === 'unsupported' || s === 'unavailable';

/** What the owner can do when push cannot work; Telegram still carries the alerts. */
const UNAVAILABLE_FIX: Record<'unsupported' | 'unavailable', string> = {
  unsupported:
    'Pe Android deschide AiVee în Chrome (prin HTTPS), pe iPhone adaug-o pe ecranul principal.',
  unavailable:
    'Alertele ajung pe Telegram. Leagă grupul echipei la Locații ca să le primească toți.',
};

/**
 * Where the push state shows:
 * - `card` (default): the full card in every state.
 * - `actionable`: the card only when there is something to switch (off, on, blocked).
 * - `banner`: a discreet owner banner only when push cannot work, with what to do.
 * - `note`: one muted line only when push cannot work (everyone else).
 * `actionable` pairs with `banner` or `note`: exactly one of them renders, carrying `#notificari`.
 */
export type PushToggleVariant = 'card' | 'actionable' | 'banner' | 'note';

/** "Activează notificările" card for the Alerte page. */
export function PushToggle({
  service,
  variant = 'card',
}: {
  service?: PushService;
  variant?: PushToggleVariant;
}) {
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

  if (variant === 'banner' || variant === 'note') {
    if (state !== 'unsupported' && state !== 'unavailable') return null;
    if (variant === 'note') {
      return (
        <p id="notificari" className="muted small push-note">
          Notificările pe telefon nu merg aici; alertele ajung pe Telegram.
        </p>
      );
    }
    return (
      <div id="notificari" className="push-banner">
        <Banner tone="info" title="Notificări pe telefon: indisponibile">
          {UNAVAILABLE_FIX[state]}{' '}
          {state === 'unavailable' && (
            <Link to="/locatii" className="push-banner-link">
              Mergi la Locații
            </Link>
          )}
        </Banner>
      </div>
    );
  }
  if (variant === 'actionable' && (state === null || isUnavailable(state))) return null;

  return (
    <section id="notificari" className="card push-card" aria-labelledby="push-h">
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
      {error && <Banner tone="error" title={error} />}
    </section>
  );
}
