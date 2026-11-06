import { useApiReachable } from './reachability';

/** Shown while the API does not answer; the app shell keeps working from the cache. */
export function OfflineBanner({ reachable }: { reachable?: boolean }) {
  const probed = useApiReachable();
  const ok = reachable ?? probed;
  if (ok) return null;
  return (
    <p className="banner-error" role="status" aria-live="polite">
      <strong>Offline</strong> · serverul AiVee nu răspunde. Reîncerc singur; alertele noi apar când
      revine conexiunea.
    </p>
  );
}
