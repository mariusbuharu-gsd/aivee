// Is the API reachable? Combines the browser's online flag with a light `/healthz` probe, so
// the PWA can say "Offline" when the phone has Wi-Fi but the restaurant's server is down.
import { useEffect, useState } from 'react';

export const PROBE_ONLINE_MS = 15_000;
export const PROBE_OFFLINE_MS = 5_000;
const PROBE_TIMEOUT_MS = 4_000;

export async function probe(apiBase: string, doFetch: typeof fetch = fetch): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return false;
  if (!apiBase) return true; // mock mode: nothing to reach
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await doFetch(`${apiBase.replace(/\/$/, '')}/healthz`, {
      cache: 'no-store',
      signal: ctrl.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** `true` while the API answers; re-probes faster while offline and on `online`/`offline`. */
export function useApiReachable(
  apiBase: string = import.meta.env.VITE_API_URL ?? '',
  doFetch: typeof fetch = fetch,
): boolean {
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      clearTimeout(timer);
      const ok = await probe(apiBase, doFetch);
      if (!alive) return;
      setReachable(ok);
      timer = setTimeout(check, ok ? PROBE_ONLINE_MS : PROBE_OFFLINE_MS);
    };
    const now = () => void check();
    const offline = () => {
      setReachable(false);
    };
    void check();
    window.addEventListener('online', now);
    window.addEventListener('offline', offline);
    document.addEventListener('visibilitychange', now);
    return () => {
      alive = false;
      clearTimeout(timer);
      window.removeEventListener('online', now);
      window.removeEventListener('offline', offline);
      document.removeEventListener('visibilitychange', now);
    };
  }, [apiBase, doFetch]);

  return reachable;
}
