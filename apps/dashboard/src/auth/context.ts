import { createContext, useContext } from 'react';
import type { Me, MeLocation, Permission, RegisterInput } from '../api/client';

export interface AuthState {
  status: 'loading' | 'anon' | 'authed';
  me: Me | null;
  /** The location every page reads; null for an owner who has not created one yet. */
  location: MeLocation | null;
  setLocation: (id: string) => void;
  /** Whether the user holds `permission` at the current location. The API enforces; the UI hides. */
  can: (permission: Permission) => boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  acceptInvite: (token: string, input: { name: string; password: string }) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-read /api/auth/me (after creating a location or changing roles). */
  refresh: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth must be used inside <AuthProvider>');
  return auth;
}

/** Shorthand for the current location's id; pages only render inside RequireLocation. */
export function useLocationId(): string {
  return useAuth().location?.id ?? '';
}
