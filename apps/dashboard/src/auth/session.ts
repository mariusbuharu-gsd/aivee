// Demo sign-in: the backend has no accounts yet (multi-tenant auth is out of scope for the
// hackathon), so the session lives in the browser. Swap `saveSession`/`loadSession` for API
// calls when the backend grows an auth endpoint; the pages only use the AuthContext.

export type VenueType = 'restaurant' | 'bar' | 'event';

export interface Session {
  name: string;
  email: string;
  venue: string;
  venueType: VenueType;
}

export const SESSION_KEY = 'aivee.session';
export const MIN_PASSWORD = 10;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const isEmail = (value: string) => EMAIL.test(value.trim());

/** 0 = empty, 1 = too short, 2 = long enough, 3 = mixed case and digits, 4 = long with symbols. */
export function passwordStrength(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0;
  if (password.length < MIN_PASSWORD) return 1;
  let score = 2;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password) && /\d/.test(password)) score++;
  if (password.length >= 14 && /[^A-Za-z0-9]/.test(password)) score++;
  return Math.min(score, 4) as 2 | 3 | 4;
}

function isSession(value: unknown): value is Session {
  const s = value as Partial<Session> | null;
  return !!s && typeof s.email === 'string' && typeof s.name === 'string';
}

export function loadSession(): Session | null {
  for (const store of [localStorage, sessionStorage]) {
    try {
      const raw = store.getItem(SESSION_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : null;
      if (isSession(parsed)) return parsed;
    } catch {
      /* storage blocked or corrupt: treat as signed out */
    }
  }
  return null;
}

export function saveSession(session: Session | null, remember = true) {
  try {
    localStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(SESSION_KEY);
    if (session)
      (remember ? localStorage : sessionStorage).setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* the session still holds in memory for this visit */
  }
}
