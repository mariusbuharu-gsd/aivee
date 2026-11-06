import { useCallback, useEffect, useRef, useState } from 'react';
import type { TelegramLink } from '../api/client';
import { useApi } from '../api/context';
import { Banner } from '../ui/Banner';

/** How often the page asks whether the group has joined, and for how long at most. */
const POLL_MS = 3_000;
const WAIT_MS = 15 * 60_000;

type Phase =
  | { kind: 'idle' }
  | { kind: 'creating' }
  | { kind: 'waiting'; link: TelegramLink; blocked: boolean }
  | { kind: 'expired' }
  | { kind: 'error'; message: string };

/**
 * "Conectează Telegram": one click opens Telegram on the bot with a single-use code; the bot
 * saves the group on the location. The page polls the status until the group joins.
 */
export function TelegramConnect({
  locationId,
  onConnected,
  pollMs = POLL_MS,
  waitMs = WAIT_MS,
}: {
  locationId: string;
  onConnected?: () => void;
  pollMs?: number;
  waitMs?: number;
}) {
  const api = useApi();
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [connected, setConnected] = useState<{ title: string | null } | null>(null);
  const onConnectedRef = useRef(onConnected);
  useEffect(() => {
    onConnectedRef.current = onConnected;
  });

  useEffect(() => {
    let live = true;
    api.getTelegramStatus(locationId).then(
      (s) => live && setConnected(s.connected ? { title: s.chat_title ?? null } : null),
      () => undefined, // the button still works; the status shows after connecting
    );
    return () => {
      live = false;
    };
  }, [api, locationId]);

  const waiting = phase.kind === 'waiting';
  useEffect(() => {
    if (!waiting) return;
    const deadline = Date.now() + waitMs;
    let busy = false;
    const timer = window.setInterval(() => {
      if (busy) return;
      if (Date.now() >= deadline) {
        window.clearInterval(timer);
        setPhase({ kind: 'expired' });
        return;
      }
      busy = true;
      api
        .getTelegramStatus(locationId)
        .then((s) => {
          if (!s.connected) return;
          window.clearInterval(timer);
          setConnected({ title: s.chat_title ?? null });
          setPhase({ kind: 'idle' });
          onConnectedRef.current?.();
        })
        .catch(() => undefined) // a missed poll is retried on the next tick
        .finally(() => {
          busy = false;
        });
    }, pollMs);
    return () => window.clearInterval(timer);
  }, [api, locationId, waiting, pollMs, waitMs]);

  const connect = useCallback(async () => {
    // Open the tab inside the click (popup blockers), then point it at the link.
    const tab = window.open('about:blank', '_blank');
    setPhase({ kind: 'creating' });
    try {
      const link = await api.createTelegramLink(locationId);
      if (tab) {
        tab.opener = null;
        tab.location.href = link.url;
      }
      setPhase({ kind: 'waiting', link, blocked: !tab });
    } catch (e) {
      tab?.close();
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : String(e) });
    }
  }, [api, locationId]);

  return (
    <div className="telegram-connect" aria-live="polite">
      {connected && (
        <p className="small">
          <strong>Conectat: {connected.title ?? 'chat Telegram'}</strong>
          <span className="muted"> · aici vin alertele locației</span>
        </p>
      )}
      {phase.kind === 'waiting' ? (
        <>
          <Banner tone="info" title="Aștept grupul din Telegram…">
            {phase.blocked ? 'Deschide linkul de mai jos, ' : 'În fereastra Telegram, '}
            alege grupul echipei și adaugă botul. Linkul e valabil 15 minute.
          </Banner>
          <div className="row-actions">
            <a className="btn btn-primary" href={phase.link.url} target="_blank" rel="noreferrer">
              Deschide Telegram
            </a>
            <a
              className="btn btn-ghost"
              href={phase.link.private_url}
              target="_blank"
              rel="noreferrer"
            >
              Doar pentru mine (chat privat)
            </a>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setPhase({ kind: 'idle' })}
            >
              Renunță
            </button>
          </div>
        </>
      ) : (
        <button
          type="button"
          className={`btn ${connected ? 'btn-ghost' : 'btn-primary'}`}
          onClick={() => void connect()}
          disabled={phase.kind === 'creating'}
        >
          {phase.kind === 'creating'
            ? 'Se deschide Telegram…'
            : connected
              ? 'Conectează alt grup Telegram'
              : 'Conectează Telegram'}
        </button>
      )}
      {phase.kind === 'expired' && (
        <Banner tone="warn" title="Linkul a expirat">
          Nu a venit niciun grup în 15 minute. Apasă din nou „Conectează Telegram”.
        </Banner>
      )}
      {phase.kind === 'error' && <Banner tone="error" title={phase.message} />}
    </div>
  );
}
