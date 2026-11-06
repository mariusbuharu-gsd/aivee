// Small helpers shared by the sign-in forms. The session itself is an HttpOnly cookie set by
// the API (docs/plans/2026-11-06-auth-roles-audit.md); the browser never sees the token.
import type { Role } from '../api/client';

export const MIN_PASSWORD = 8;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LOCATION_KEY = 'aivee.location';

export const isEmail = (value: string) => EMAIL.test(value.trim());

/** 0 = empty, 1 = too short, 2 = long enough, 3 = mixed case and digits, 4 = long with symbols. */
export function passwordStrength(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0;
  if (password.length < MIN_PASSWORD) return 1;
  let score = 2;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password) && /\d/.test(password)) score++;
  if (password.length >= 12 && /[^A-Za-z0-9]/.test(password)) score++;
  return Math.min(score, 4) as 2 | 3 | 4;
}

export const ROLE_LABEL: Record<Role, string> = {
  owner: 'Proprietar',
  manager: 'Manager',
  staff: 'Personal',
};

/** Only same-app paths are followed after sign-in. */
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

export function loadLocationId(): string | null {
  try {
    return localStorage.getItem(LOCATION_KEY);
  } catch {
    return null;
  }
}

export function saveLocationId(id: string | null) {
  try {
    if (id) localStorage.setItem(LOCATION_KEY, id);
    else localStorage.removeItem(LOCATION_KEY);
  } catch {
    /* the choice holds for this visit */
  }
}
