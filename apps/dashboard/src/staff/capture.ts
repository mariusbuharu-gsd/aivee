// State shared by the camera dialog ("Adaugă angajat") and the one-phone page (/angajat-nou).
import { useEffect, useState } from 'react';
import type { StaffCapture, StaffProfile } from '../api/client';
import { useApi } from '../api/context';

/** How long the employee turns around in front of the camera (the API accepts 5–30 s). */
export const CAPTURE_SECONDS = 20;
export const NEW_PROFILE = '';

/** Existing profiles to add to; empty when the list fails (adding to one is optional). */
export function useStaffProfiles(): StaffProfile[] {
  const api = useApi();
  const [profiles, setProfiles] = useState<StaffProfile[]>([]);
  useEffect(() => {
    let alive = true;
    api.listStaffProfiles().then(
      (p) => alive && setProfiles(p),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [api]);
  return profiles;
}

/** Seconds left of a countdown started at `startedAt` (`Date.now()`), or null when idle. */
export function useCountdown(startedAt: number | null, seconds = CAPTURE_SECONDS): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [startedAt]);
  if (startedAt === null) return seconds;
  const gone = Math.max(0, Math.floor((now - startedAt) / 1000));
  return Math.max(0, seconds - gone);
}

/** Which candidates are kept: `keepAll` on a new capture, then toggled one tap at a time. */
export function useKept() {
  const [kept, setKept] = useState<Set<number>>(new Set());
  const keepAll = (capture: StaffCapture) =>
    setKept(new Set(capture.candidates.map((c) => c.index)));
  const toggle = (index: number) =>
    setKept((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  return { kept, toggle, keepAll };
}
