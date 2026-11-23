import { useEffect, useState } from 'react';

/** The current time, refreshed every `everyMs` (a second by default) while `active`. */
export function useNow(active = true, everyMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [active, everyMs]);
  return now;
}
